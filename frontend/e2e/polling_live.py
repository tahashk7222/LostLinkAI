"""Live check of notification polling and session handling against the production backend.

    python frontend/e2e/polling_live.py --web https://lost-link-ai-three.vercel.app --api https://lostlinkai-98em.onrender.com

Registers ONE throwaway account (no reports) and uses its real token. It records real /notifications responses.

  A. Valid session: the poller runs (a request at mount and about 20 s later).
  B. Token removed mid-session (another tab signed out): no further notification requests.
  C. Token expires mid-session: the next poll gets 401, the user is sent to /login?expired=1, polling stops.
  D. No token at load: no notification request.
"""

import argparse
import json
import secrets
import sys
import time
import urllib.request
import uuid

from playwright.sync_api import sync_playwright


def register(api):
    email = f"poll-{uuid.uuid4().hex[:8]}@example.com"
    body = json.dumps({"name": "Poll Check", "email": email, "password": secrets.token_urlsafe(16)}).encode()
    req = urllib.request.Request(api + "/auth/register", data=body, headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=240).read())["access_token"]


def run(browser, web, api, scenario, token, window):
    page = browser.new_page()
    responses = []
    page.on("response", lambda r: responses.append((time.time(), r.status)) if "/notifications" in r.url and r.url.startswith(api) else None)
    page.goto(web + "/login")
    if token:
        page.evaluate("t => localStorage.setItem('lostlink_token', t)", token)
    page.goto(web + "/dashboard")
    if scenario == "D":
        page.wait_for_timeout(window * 1000)  # Playwright's wait lets response events be recorded; time.sleep would not
        page.close()
        return len(responses) == 0, f"{len(responses)} notification responses with no token (expected 0)"
    page.get_by_role("button", name="Log out").first.wait_for(timeout=240000)  # the signed-in view has mounted
    t_mount = time.time()
    if scenario == "B":
        page.wait_for_timeout(3000)
        page.evaluate("localStorage.removeItem('lostlink_token')")
        t_event = time.time()
    elif scenario == "C":
        page.wait_for_timeout(3000)
        page.evaluate("localStorage.setItem('lostlink_token', 'expired-session-token')")
        t_event = time.time()
    else:
        t_event = t_mount
    page.wait_for_timeout(window * 1000)
    after = [s for t, s in responses if t >= t_event]
    url = page.url
    page.close()
    if scenario == "A":
        n = len([1 for t, s in responses if t >= t_mount])
        return n >= 2, f"{n} notification responses in the window (expected at least 2: at mount and about 20 s later)"
    if scenario == "B":
        return len(after) == 0, f"{len(after)} notification responses after the token was removed (expected 0)"
    if scenario == "C":
        redirected = "/login" in url and "expired=1" in url
        return redirected and len(after) <= 1, f"401 responses after expiry: {after.count(401)}; sent to sign-in: {redirected}; total after expiry: {len(after)} (expected one 401 and a redirect)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="https://lost-link-ai-three.vercel.app")
    ap.add_argument("--api", default="https://lostlinkai-98em.onrender.com")
    args = ap.parse_args()
    token = register(args.api)
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for scenario, name, tok in (("A", "valid session polls", token), ("B", "token removed mid-session stops polling", token),
                                    ("C", "expiry redirects to sign-in and stops", token), ("D", "no token, no notification request", None)):
            ok, detail = run(browser, args.web, args.api, scenario, tok, 45)
            failures += 0 if ok else 1
            print(("PASS " if ok else "FAIL ") + scenario + " " + name + " - " + detail)
        browser.close()
    print("live polling checks:", "all passed" if failures == 0 else f"{failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

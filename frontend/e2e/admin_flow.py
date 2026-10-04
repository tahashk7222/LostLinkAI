"""Admin portal walkthrough in the browser: dashboard, report review and rejection, verification monitor, recovery.

Requires the API and the web app running, and an admin account (set ADMIN_EMAIL and ADMIN_PASSWORD on the API, or pass
--admin-email and --admin-password). Reports, verification and recovery are created through the API, as the existing
browser checks do. Run it against a scratch database, because it adds rows.

    python frontend/e2e/admin_flow.py --api http://localhost:8000 --web http://localhost:3000 \
        --admin-email admin@lostlink.test --admin-password adminpass123
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

RUN = str(int(time.time()))[-6:]
PRIVATE_ANSWER = "flow-secret-9417 notebook"  # the owner's verification answer: must never appear in the admin portal


def api(base, method, path, body=None, token=None, **kw):
    body = body if body is not None else kw.get("json")  # accept body= or json=
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:200]}") from None


def register(base, name, email):
    return api(base, "POST", "/auth/register", {"name": name, "email": email, "password": "password123"})["access_token"]


def login_ui(page, web, email, password):
    page.goto(f"{web}/login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button:has-text('Log in')")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:3000")
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "screenshots"))
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = []

    # --- data through the API: a recovered case, and a joke report for the rejection step ---
    owner = register(args.api, "Ayesha Khan", f"adm-owner{RUN}@example.com")
    finder = register(args.api, "Bilal Ahmed", f"adm-finder{RUN}@example.com")
    lost = api(args.api, "POST", "/reports", {
        "report_type": "LOST", "category": "Backpack", "name": "Black JanSport backpack",
        "description": "Lost my black JanSport backpack near the lecture theatre.", "color": "Black", "brand": "JanSport",
        "distinctive_features": "Name tag with initials inside the front pocket", "private_details": PRIVATE_ANSWER,
        "date_time": "2026-10-01T15:00:00Z", "location": "Lecture Theatre", "place_key": "lecture-theatre"}, owner)
    found = api(args.api, "POST", "/reports", {
        "report_type": "FOUND", "category": "Bag", "name": "Black JanSport backpack",
        "description": "Found a black JanSport backpack near the lecture theatre.", "color": "black", "brand": "Jansport",
        "distinctive_features": "Has a name tag with initials inside the front pocket",
        "date_time": "2026-10-01T16:00:00Z", "location": "Lecture Theatre", "place_key": "lecture-theatre"}, finder)
    joke = api(args.api, "POST", "/reports", {
        "report_type": "FOUND", "category": "Other", "name": "Flying teapot",
        "description": "Found a flying teapot that sings opera.", "date_time": "2026-10-01T10:00:00Z",
        "location": "Lecture Theatre", "place_key": "lecture-theatre"}, finder)
    # The database may hold found reports from earlier runs, so pick the match for this run's found report.
    matches = api(args.api, "GET", f"/reports/{lost['id']}/matches", token=owner)["matches"]
    m = next(x for x in matches if x["other_report"]["id"] == found["id"])
    api(args.api, "POST", f"/matches/{m['id']}/verification", token=owner)
    api(args.api, "POST", f"/matches/{m['id']}/verification/answers", token=owner,
        json={"answers": {"contents": PRIVATE_ANSWER, "hidden_feature": "Small tear inside the front pocket"}})
    case_id = api(args.api, "POST", f"/matches/{m['id']}/verify", token=finder, json={"decision": "ACCEPT"})["case_id"]
    api(args.api, "PUT", f"/cases/{case_id}/status", token=owner, json={"status": "RECOVERED"})

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)

        # --- an ordinary user cannot reach the portal ---
        user_page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login_ui(user_page, args.web, f"adm-owner{RUN}@example.com", "password123")
        user_page.goto(f"{args.web}/admin")
        expect(user_page.get_by_text("Admin dashboard")).to_have_count(0, timeout=8000)
        if user_page.get_by_text("Recovered (archived)").count():
            failures.append("ordinary user sees admin dashboard cards")
        print("1. Ordinary user: admin dashboard not shown")

        # --- admin: dashboard ---
        admin_page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login_ui(admin_page, args.web, args.admin_email, args.admin_password)
        admin_page.goto(f"{args.web}/admin")
        expect(admin_page.get_by_text("Recovered (archived)")).to_be_visible(timeout=15000)
        expect(admin_page.get_by_text("Recent admin and recovery actions")).to_be_visible()
        admin_page.screenshot(path=str(out / "admin-dashboard.png"), full_page=True)
        print("2. Admin dashboard shows the operational cards and recent activity")

        # --- admin: review and reject the joke report with a reason ---
        admin_page.goto(f"{args.web}/admin/reports/{joke['id']}")
        expect(admin_page.get_by_text(f"Review report #{joke['id']}")).to_be_visible(timeout=15000)
        admin_page.select_option("#reason", "FAKE_OR_JOKE")
        admin_page.fill("#note", "Obvious joke submission.")
        admin_page.once("dialog", lambda d: d.accept())
        admin_page.get_by_role("button", name="Reject report").click()
        expect(admin_page.get_by_text("Rejected. The report no longer takes part in matching.")).to_be_visible(timeout=10000)
        expect(admin_page.get_by_text("Rejected: Fake or joke")).to_be_visible()
        admin_page.screenshot(path=str(out / "admin-rejected.png"), full_page=True)
        print("3. Joke report rejected with reason FAKE_OR_JOKE, shown on the review page")

        # --- admin: verification monitor shows progress, never the answers ---
        admin_page.goto(f"{args.web}/admin")
        admin_page.get_by_role("button", name="Verification", exact=True).click()
        expect(admin_page.get_by_text("Verification passed", exact=True).first).to_be_visible(timeout=10000)
        body = admin_page.inner_text("body")
        if PRIVATE_ANSWER in body or "Small tear inside" in body:
            failures.append("verification answer visible in the admin portal")
        print("4. Verification monitor shows 'Verification passed' and no owner answers")

        # --- admin: recovery confirmation ---
        admin_page.goto(f"{args.web}/admin/cases/{case_id}")
        expect(admin_page.get_by_text("Item recovered")).to_be_visible(timeout=15000)
        expect(admin_page.get_by_text("Not in active listings")).to_have_count(2)
        expect(admin_page.get_by_text("Not eligible for matching")).to_have_count(2)
        expect(admin_page.get_by_text("Archived ").first).to_be_visible()
        if PRIVATE_ANSWER in admin_page.inner_text("body"):
            failures.append("owner's private answer visible on the recovery page")
        admin_page.screenshot(path=str(out / "admin-recovery.png"), full_page=True)
        print("5. Recovery confirmed: inactive listings, not matching-eligible, archived")

        browser.close()

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("admin flow passed; screenshots in", out)


if __name__ == "__main__":
    main()

"""Ownership verification in the browser: match notification, owner answers, finder decides, owner retries, finder
confirms, item recovered, and privacy checks on both sides.

Requires the API and the web app running, and an admin account for the recovery checks (ADMIN_EMAIL and ADMIN_PASSWORD
on the API). Reports are created through the API, as the other browser checks do. Run it against a scratch database.

    python frontend/e2e/verification_flow.py --api http://localhost:8000 --web http://localhost:3000 \
        --admin-email admin@example.com --admin-password <password>
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
PASSWORD = "password123"
SECRET = "flow-private-7421 calculus notebook"  # the owner's correct answer
WRONG = "guessing a random answer"
EXTRA = "flow-tear-3307 inside the front pocket"  # second private answer


def api(base, method, path, body=None, token=None):
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


def login_ui(page, web, email, password):
    page.goto(f"{web}/login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button:has-text('Log in')")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)


def answer(page, contents, extra):
    page.fill("#contents", contents)
    page.fill("#hidden_feature", extra)
    page.get_by_role("button", name="Send answers to finder").click()


def wait_for(predicate, what: str, timeout: float = 15.0):
    """Poll a state check until it holds. Used for real state transitions, not page text."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for: {what}")


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

    owner_email, finder_email = f"ver-owner{RUN}@example.com", f"ver-finder{RUN}@example.com"
    owner = api(args.api, "POST", "/auth/register", {"name": "Ayesha Khan", "email": owner_email, "password": PASSWORD})["access_token"]
    finder = api(args.api, "POST", "/auth/register", {"name": "Bilal Ahmed", "email": finder_email, "password": PASSWORD})["access_token"]
    admin = api(args.api, "POST", "/auth/login", {"email": args.admin_email, "password": args.admin_password})["access_token"]
    lost = api(args.api, "POST", "/reports", {
        "report_type": "LOST", "category": "Backpack", "name": "Black JanSport backpack",
        "description": "Lost my black JanSport backpack near the lecture theatre.", "color": "Black", "brand": "JanSport",
        "distinctive_features": "Name tag with initials inside the front pocket", "private_details": SECRET,
        "date_time": "2026-10-01T15:00:00Z", "location": "Lecture Theatre", "place_key": "lecture-theatre"}, owner)
    found = api(args.api, "POST", "/reports", {
        "report_type": "FOUND", "category": "Bag", "name": "Black JanSport backpack",
        "description": "Found a black JanSport backpack near the lecture theatre.", "color": "black", "brand": "Jansport",
        "distinctive_features": "Has a name tag with initials inside the front pocket",
        "date_time": "2026-10-01T16:00:00Z", "location": "Lecture Theatre", "place_key": "lecture-theatre"}, finder)
    matches = api(args.api, "GET", f"/reports/{lost['id']}/matches", token=owner)["matches"]
    mid = next(m["id"] for m in matches if m["other_report"]["id"] == found["id"])

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)

        # 1. The owner is told about the potential match
        owner_page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login_ui(owner_page, args.web, owner_email, PASSWORD)
        owner_page.goto(f"{args.web}/notifications")
        expect(owner_page.get_by_text("Potential match for your lost item").first).to_be_visible(timeout=15000)
        print("1. Owner notified of the potential match")

        # 2. The owner starts verification and sends a wrong answer
        owner_page.goto(f"{args.web}/matches/{mid}")
        owner_page.get_by_role("button", name="Verify ownership").click()
        owner_page.wait_for_url(lambda url: "/verify" in url, timeout=15000)
        answer(owner_page, WRONG, WRONG)
        expect(owner_page.get_by_text("Your answers were sent")).to_be_visible(timeout=15000)
        print("2. Owner sends answers; the page says they were sent and reveals nothing")

        # 3. The finder decides. The owner's answers must not be on the finder's page at all.
        finder_page = browser.new_context(viewport={"width": 390, "height": 900}).new_page()
        login_ui(finder_page, args.web, finder_email, PASSWORD)
        finder_page.goto(f"{args.web}/matches/{mid}/verify")
        expect(finder_page.get_by_role("button", name="This is not the owner")).to_be_visible(timeout=15000)
        finder_body = finder_page.inner_text("body")
        for leaked in (WRONG, SECRET, EXTRA, owner_email):
            if leaked in finder_body:
                failures.append(f"finder's page shows {leaked[:24]!r}")
        finder_page.get_by_role("button", name="This is not the owner").click()
        finder_page.get_by_role("button", name="Confirm: reject claim").click()
        expect(finder_page.get_by_text("You rejected this claim")).to_be_visible(timeout=15000)
        print("3. Finder rejects the claim; the finder's page shows none of the owner's answers")

        # 4. The owner sees the safe outcome and can retry (attempts left are shown)
        owner_page.goto(f"{args.web}/matches/{mid}")
        expect(owner_page.get_by_text("Try verification again")).to_be_visible(timeout=15000)
        if "2 attempts left" not in owner_page.inner_text("body"):
            failures.append("attempts left not shown to owner after a rejection")
        owner_page.get_by_role("button", name="Try verification again").click()
        owner_page.wait_for_url(lambda url: "/verify" in url, timeout=15000)
        answer(owner_page, SECRET, EXTRA)
        expect(owner_page.get_by_text("Your answers were sent")).to_be_visible(timeout=15000)
        print("4. Owner retries with the correct answers (second attempt)")

        # 5. The finder confirms the owner
        finder_page.goto(f"{args.web}/matches/{mid}/verify")
        expect(finder_page.get_by_role("button", name="Confirm this person is the owner")).to_be_visible(timeout=15000)
        finder_page.get_by_role("button", name="Confirm this person is the owner").click()
        expect(finder_page.get_by_role("heading", name="Verification passed")).to_be_visible(timeout=15000)
        expect(finder_page.get_by_text("Please confirm whether you still have this item.")).to_be_visible()
        case_id = api(args.api, "GET", f"/matches/{mid}", token=owner)["case_id"]
        assert case_id, "a verified match must have a case"
        # Possession, not ownership: the finder confirms they still have the item.
        finder_page.get_by_role("button", name="I still have this item").click()
        expect(finder_page.get_by_text("The owner has been asked to arrange the handover")).to_be_visible(timeout=15000)
        case_state = api(args.api, "GET", f"/cases/{case_id}", token=finder)
        if case_state["status"] != "CONNECTED" or not case_state["possession_confirmed_at"]:
            failures.append("finder's possession confirmation did not reach the case")
        owner_types = [n["type"] for n in api(args.api, "GET", "/notifications", token=owner)["notifications"]]
        if "possession_confirmed" not in owner_types:
            failures.append("owner was not told the finder still has the item")
        print("5. Verification passed; finder confirms possession; case", case_id, "connected and confirmed")

        # 6. The owner sees 'verified' and no advisory score
        owner_page.goto(f"{args.web}/matches/{mid}/verify")
        expect(owner_page.get_by_text("Verification completed successfully")).to_be_visible(timeout=15000)
        if "Consistency with your notes" in owner_page.inner_text("body"):
            failures.append("advisory score shown to the owner")
        owner_page.screenshot(path=str(out / "verification-owner-verified.png"), full_page=True)
        print("6. Owner sees 'Verification completed'; no advisory score on the owner's side")

        # 7. Recovery through the existing case flow, then state checks against the API
        owner_page.goto(f"{args.web}/cases/{case_id}")
        owner_page.get_by_role("button", name="Item returned: mark recovered").click()
        owner_page.get_by_role("button", name="Confirm", exact=True).click()

        def case_recovered():
            return api(args.api, "GET", f"/cases/{case_id}", token=owner)["status"] == "RECOVERED"
        wait_for(case_recovered, f"case {case_id} becomes RECOVERED")

        for report_id, label in ((lost["id"], "lost"), (found["id"], "found")):
            r = api(args.api, "GET", f"/admin/reports/{report_id}", token=admin)
            if r["status"] != "RECOVERED":
                failures.append(f"{label} report status is {r['status']}, expected RECOVERED")
            if r["archived_at"] is None:
                failures.append(f"{label} report is not archived")

        listed = [x["id"] for x in api(args.api, "GET", "/reports", token=finder)["items"]]
        if lost["id"] in listed or found["id"] in listed:
            failures.append("recovered items still in the public listing")

        cv = api(args.api, "GET", f"/admin/cases/{case_id}", token=admin)
        if not (cv["recovery_confirmed"] and cv["status"] == "RECOVERED"):
            failures.append("admin case view does not confirm recovery")
        for side in ("lost", "found"):
            item = cv[side]
            if item["active_listing"] or item["matching_eligible"] or not item["archived"]:
                failures.append(f"admin view: {side} item is still active or not archived")
        print("7. Case RECOVERED; both reports RECOVERED and archived; admin view confirms it")

        # 8. Notifications: the finder is told the item was recovered, and no page or notification leaks private data
        finder_notes = api(args.api, "GET", "/notifications", token=finder)["notifications"]
        if "case_recovered" not in [n["type"] for n in finder_notes]:
            failures.append("finder did not receive the case_recovered notification")
        finder_page.goto(f"{args.web}/notifications")
        expect(finder_page.get_by_text("Item marked recovered").first).to_be_visible(timeout=15000)
        for name, token, page in (("owner", owner, owner_page), ("finder", finder, finder_page)):
            notes = api(args.api, "GET", "/notifications", token=token)["notifications"]
            text = json.dumps(notes)
            for leaked in (SECRET, EXTRA, WRONG, owner_email, finder_email):
                if leaked in text:
                    failures.append(f"{leaked[:20]}... in the {name}'s notifications")
        finder_page.screenshot(path=str(out / "verification-finder-notifications.png"), full_page=True)
        print("8. Finder notified of recovery; no answers or emails in notifications")

        # 9. The admin sees the same lifecycle in the browser
        admin_page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        login_ui(admin_page, args.web, args.admin_email, args.admin_password)
        admin_page.goto(f"{args.web}/admin/cases/{case_id}")
        expect(admin_page.get_by_text("Item recovered")).to_be_visible(timeout=15000)
        expect(admin_page.get_by_text("Not in active listings")).to_have_count(2)
        expect(admin_page.get_by_text("Not eligible for matching")).to_have_count(2)
        expect(admin_page.get_by_role("button", name="Close case")).to_be_visible()
        if SECRET in admin_page.inner_text("body"):
            failures.append("owner's private answer visible in the admin case view")
        admin_page.screenshot(path=str(out / "verification-admin-case.png"), full_page=True)
        print("9. Admin case view: recovered, inactive, not matching-eligible, close action available")

        browser.close()

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("verification flow passed; screenshots in", out)


if __name__ == "__main__":
    main()

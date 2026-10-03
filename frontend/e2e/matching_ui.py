"""Browser check for the matching UI (lead labels, structured evidence, warnings, privacy).

Requires the API and the web app to be running, and Playwright (Python) with Chromium installed:

    pip install playwright && python -m playwright install chromium
    python frontend/e2e/matching_ui.py --api http://localhost:8000 --web http://localhost:3000

By default it uses the installed Google Chrome (--channel chrome).

The script seeds its own accounts and reports through the API, checks the lead labels it gets back, and
then checks what the browser shows. It does not touch existing data. Screenshots go to --out.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

CANARY = "canary-ledger-9q7"  # private detail: must never appear on any matching page
RUN = str(int(time.time()))[-6:]  # unique emails per run so the script can be repeated


def api(base, method, path, body=None, token=None):
    req = urllib.request.Request(f"{base}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"null")


def seed(base):
    owner_email, finder_email = f"owner{RUN}@example.com", f"finder{RUN}@example.com"
    owner = api(base, "POST", "/auth/register", {"name": "Ayesha Khan", "email": owner_email, "password": "password123"})["access_token"]
    finder = api(base, "POST", "/auth/register", {"name": "Bilal Ahmed", "email": finder_email, "password": "password123"})["access_token"]
    when = "2026-10-01T15:00:00Z"
    # Strong or Possible lead: same brand, colour, matching feature and description, same place.
    lost_bag = api(base, "POST", "/reports", {
        "report_type": "LOST", "category": "Backpack", "name": "Black JanSport backpack",
        "description": "Lost my black JanSport backpack with a calculus notebook inside near the Lecture Theatre.",
        "color": "Black", "brand": "JanSport", "distinctive_features": "Name tag with initials inside the front pocket",
        "private_details": f"{CANARY} notebook and calculator", "date_time": when, "location": "Lecture Theatre",
        "place_key": "lecture-theatre"}, owner)
    api(base, "POST", "/reports", {
        "report_type": "FOUND", "category": "Bag", "name": "Black JanSport backpack",
        "description": "Found a black JanSport backpack with a calculus notebook on a bench near the library.",
        "color": "black", "brand": "Jansport", "distinctive_features": "Has a name tag with initials inside the front pocket",
        "date_time": "2026-10-01T15:30:00Z", "location": "Bench near Allah Wala Chowk", "location_type": "gps",
        "latitude": 31.578850, "longitude": 74.356760}, finder)
    # Weak lead: only colour and brand match, nothing identifying.
    lost_watch = api(base, "POST", "/reports", {
        "report_type": "LOST", "category": "Watch", "name": "Black Casio watch",
        "description": "Lost my black watch somewhere in the academic block.", "color": "Black", "brand": "Casio",
        "date_time": when, "location": "Lecture Theatre", "place_key": "lecture-theatre"}, owner)
    # Several more found watches: the owner then has more Weak leads than the list shows at first (5).
    for i in range(7):
        api(base, "POST", "/reports", {
            "report_type": "FOUND", "category": "Watch", "name": f"Watch {i + 1}",
            "description": f"Found a watch on a bench, copy {i + 1}.", "color": "black", "brand": "Casio",
            "date_time": "2026-10-01T16:00:00Z", "location": "Lecture Theatre", "place_key": "lecture-theatre"}, finder)
    return owner_email, finder_email, owner, lost_bag["id"], lost_watch["id"]


def check_api(base, owner_token, bag_id, watch_id):
    bag = api(base, "GET", f"/reports/{bag_id}/matches", token=owner_token)["matches"]
    watch = api(base, "GET", f"/reports/{watch_id}/matches", token=owner_token)["matches"]
    assert bag and bag[0]["lead"] in ("STRONG", "POSSIBLE"), bag
    assert len(watch) >= 6 and all(m["lead"] == "WEAK" for m in watch), watch
    assert CANARY not in json.dumps(bag) and CANARY not in json.dumps(watch), "private detail leaked by the API"
    # A Weak lead must not start ownership verification, even when called directly.
    blocked = urllib.request.Request(f"{base}/matches/{watch[0]['id']}/verification", method="POST",
                                     headers={"Authorization": f"Bearer {owner_token}"})
    try:
        urllib.request.urlopen(blocked)
        raise AssertionError("verification started from a Weak lead")
    except urllib.error.HTTPError as e:
        assert e.code == 409, e.code
    return bag[0]["id"], watch[0]["id"], bag[0]["lead"], len(watch)


def login(page, web, email):
    page.goto(f"{web}/login")
    page.fill("#email", email)
    page.fill("#password", "password123")
    page.click("button:has-text('Log in')")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:3000")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "screenshots"))
    ap.add_argument("--channel", default="chrome", help="installed browser: chrome, msedge, or chromium (after playwright install)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    owner_email, _, owner_token, bag_id, watch_id = seed(args.api)
    bag_match, watch_match, lead, weak_count = check_api(args.api, owner_token, bag_id, watch_id)
    print(f"API: bag match lead={lead}, {weak_count} watch matches all WEAK, verification blocked (409), "
          f"no private detail in API output")

    failures = []
    weak_cards = "a[href^='/matches/']:has-text('Weak lead')"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)
        for width, name in [(1280, "desktop"), (390, "mobile")]:
            page = browser.new_page(viewport={"width": width, "height": 900})
            login(page, args.web, owner_email)
            page.goto(f"{args.web}/matches")
            expect(page.get_by_text("Weak lead").first).to_be_visible(timeout=15000)
            expect(page.get_by_text("cannot be verified as yours").first).to_be_visible()
            # Only five weak leads are listed at first; "Show more" lists the rest.
            shown = page.locator(weak_cards).count()
            if shown != 5:
                failures.append(f"{shown} weak leads listed at {width}px, expected 5 before Show more")
            show_more = page.get_by_role("button", name="Show", exact=False).filter(has_text="more weak")
            expect(show_more.first).to_be_visible()
            show_more.first.click()
            if page.locator(weak_cards).count() != weak_count:
                failures.append(f"Show more did not list all {weak_count} weak leads at {width}px")
            if page.locator(weak_cards).filter(has_text="Potential match").count():
                failures.append(f"a Weak lead card shows 'Potential match' at {width}px")
            if page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"):
                failures.append(f"horizontal scroll on matches page at {width}px")
            page.screenshot(path=str(out / f"matches-{name}.png"), full_page=True)

            page.goto(f"{args.web}/matches/{bag_match}")
            expect(page.get_by_text("Matching details")).to_be_visible(timeout=15000)
            expect(page.get_by_text("Why LostLink suggested this")).to_be_visible()
            expect(page.get_by_text("Signal values come from fixed rules")).to_be_visible()
            expect(page.get_by_text("Item type, place and time")).to_be_visible()
            if page.get_by_text("Same item category").count() and page.locator("h3:has-text('Matching details')").count() == 0:
                failures.append("category shown as a matching identity detail")
            if page.get_by_text("Strong lead").count() == 0 and page.get_by_text("Possible lead").count() == 0:
                failures.append("bag match shows neither Strong nor Possible lead")
            if page.get_by_text("Earlier suggestion").count():
                failures.append("bag match shows 'Earlier suggestion' although it has a lead label")
            if page.get_by_role("button", name="Verify ownership").count() == 0 and page.get_by_text("Continue verification").count() == 0:
                failures.append("bag match (not Weak) offers no verification")
            body = page.inner_text("body")
            if CANARY in body.lower():
                failures.append("private detail visible on match page")
            if page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"):
                failures.append(f"horizontal scroll on match page at {width}px")
            page.screenshot(path=str(out / f"match-strong-{name}.png"), full_page=True)

            page.goto(f"{args.web}/matches/{watch_match}")
            expect(page.get_by_text("Weak lead.").first).to_be_visible(timeout=15000)
            expect(page.get_by_text("Do not treat this as a match").first).to_be_visible()
            expect(page.get_by_text("Shared details (not enough to notify you)")).to_be_visible()
            if page.get_by_role("button", name="Verify ownership").count():
                failures.append(f"Verify ownership shown for a Weak lead at {width}px")
            expect(page.get_by_text("cannot be verified", exact=False).first).to_be_visible()
            if CANARY in page.inner_text("body").lower():
                failures.append("private detail visible on Weak lead page")
            page.screenshot(path=str(out / f"match-weak-{name}.png"), full_page=True)
            page.close()

        # Existing functionality still renders for the logged-in owner.
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        login(page, args.web, owner_email)
        for path in ["/dashboard", "/reports", f"/reports/{bag_id}"]:
            page.goto(f"{args.web}{path}")
            page.wait_for_load_state("networkidle")
            if "application error" in page.inner_text("body").lower():
                failures.append(f"{path} shows an application error")
        browser.close()

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("browser checks passed; screenshots in", out)


if __name__ == "__main__":
    main()

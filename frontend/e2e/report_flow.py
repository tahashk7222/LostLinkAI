"""Browser flow through the UI: two users, a lost report, a found report with a photo, and the match.

Requires the API and the web app to be running (see README, "Browser checks"). Uses the installed Google Chrome by
default (--channel chrome). Creates its own accounts and reports with a unique suffix, so it can be repeated.

    python frontend/e2e/report_flow.py --api http://localhost:8000 --web http://localhost:3000

Steps:
  1. Owner registers in the UI and creates a LOST report (place chosen from the UET Lahore list, one private detail).
  2. Finder registers in a separate browser context and creates a FOUND report with a photo.
  3. The owner sees the match on /matches with a lead label, and the private detail is not on any page the finder sees.
"""

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PRIVATE = "flow-canary-7731 notebook"  # must never show up on the finder's pages
RUN = str(int(time.time()))[-6:]
PLACE = "Lecture Theatre"


def register(page, web, name, email):
    page.goto(f"{web}/register")
    page.fill("#name", name)
    page.fill("#email", email)
    page.fill("#password", "password123")
    page.click("button:has-text('Sign up')")
    page.wait_for_url(lambda url: "/register" not in url, timeout=15000)


def fill_common(page, name, description, when, place, color, brand, features):
    page.fill("#name", name)
    page.fill("#description", description)
    page.fill("#dt", when)
    page.get_by_role("button", name=PLACE, exact=False).first.click()
    page.get_by_role("button", name="More details").click()  # colour, brand and features are behind this toggle
    page.fill("#color", color)
    page.fill("#brand", brand)
    page.fill("#features", features)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:3000")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "screenshots"))
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    photo = Path(tempfile.mkdtemp()) / "item.png"
    photo.write_bytes(PNG_1X1)

    owner_email = f"flow-owner{RUN}@example.com"
    finder_email = f"flow-finder{RUN}@example.com"
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)

        owner = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        register(owner, args.web, "Ayesha Khan", owner_email)
        owner.goto(f"{args.web}/report/lost")
        fill_common(owner, "Black JanSport backpack", "Lost my black JanSport backpack near the lecture theatre.",
                    "2026-10-01T15:00", PLACE, "Black", "JanSport", "Name tag with initials inside the front pocket")
        owner.fill("#private", PRIVATE)
        owner.get_by_role("button", name="Report lost item").click()
        owner.wait_for_url(lambda url: "/reports/" in url and "created=1" in url, timeout=20000)
        print("1. LOST report created in the UI:", owner.url.split("/reports/")[1].split("?")[0])
        owner.screenshot(path=str(out / "flow-lost-created.png"), full_page=True)

        finder_ctx = browser.new_context(viewport={"width": 390, "height": 900})
        finder = finder_ctx.new_page()
        register(finder, args.web, "Bilal Ahmed", finder_email)
        finder.goto(f"{args.web}/report/found")
        fill_common(finder, "Black backpack", "Found a black JanSport backpack near the lecture theatre.",
                    "2026-10-01T16:00", PLACE, "Black", "JanSport", "Has a name tag with initials inside the front pocket")
        finder.locator("input[type=file]").first.set_input_files(str(photo))
        finder.get_by_role("button", name="Report found item").click()
        finder.wait_for_url(lambda url: "/reports/" in url and "created=1" in url, timeout=20000)
        photo_errors = "photo_errors" in finder.url
        if photo_errors:
            failures.append("photo upload reported an error on the found report")
        print("2. FOUND report created in the UI with a photo" + ("" if not photo_errors else " (photo error)"))
        finder.screenshot(path=str(out / "flow-found-created.png"), full_page=True)

        owner.goto(f"{args.web}/matches")
        expect(owner.get_by_text("Potential matches")).to_be_visible(timeout=20000)
        card = owner.locator("a[href^='/matches/']").first
        expect(card).to_be_visible(timeout=20000)
        label = "Strong lead" if owner.get_by_text("Strong lead").count() else (
            "Possible lead" if owner.get_by_text("Possible lead").count() else None)
        if label is None:
            failures.append("owner's match shows no Strong or Possible lead")
        print("3. Owner sees the match with label:", label)
        owner.screenshot(path=str(out / "flow-owner-matches.png"), full_page=True)
        card.click()
        owner.wait_for_url(lambda url: "/matches/" in url, timeout=15000)
        expect(owner.get_by_role("button", name="Verify ownership")).to_be_visible(timeout=15000)
        print("4. Owner can start verification from the match page (Verify ownership shown)")

        finder.goto(f"{args.web}/matches")
        expect(finder.get_by_text("Potential matches")).to_be_visible(timeout=20000)
        expect(finder.locator("a[href^='/matches/']").first).to_be_visible(timeout=20000)
        finder.goto(f"{args.web}/matches/" + finder.locator("a[href^='/matches/']").first.get_attribute("href").split("/")[-1])
        expect(finder.get_by_text("Why LostLink suggested this")).to_be_visible(timeout=15000)
        for page_name, page in [("finder matches", finder), ("owner match page", owner)]:
            if PRIVATE in page.inner_text("body"):
                failures.append(f"private detail visible on the {page_name}")
        print("5. Finder sees the match; the owner's private detail is not on the finder's pages")
        finder.screenshot(path=str(out / "flow-finder-match.png"), full_page=True)

        browser.close()

    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("report flow passed; screenshots in", out)


if __name__ == "__main__":
    main()

"""Production matching and image smoke test through the public API. Creates ONLY the records it deletes at the end.

    python frontend/e2e/production_smoke.py --api https://lostlinkai-98em.onrender.com

Creates: a black backpack with a red keychain (lost), a similar one (found, same place, within 12 hours), and a
charger (found, negative control). Each report has two photos. Accounts are throwaway. Nothing else is touched.
"""

import argparse
import io
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class Api:
    def __init__(self, base):
        self.base = base

    def call(self, method, path, body=None, token=None, raw=None, ctype=None):
        headers, data = {}, None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if raw is not None:
            data, headers["Content-Type"] = raw, ctype
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                payload = r.read()
                return r.status, r.headers.get("Content-Type", ""), payload, time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read(), time.perf_counter() - t0

    def json(self, *a, **kw):
        status, ctype, payload, dur = self.call(*a, **kw)
        try:
            return status, json.loads(payload or b"null"), dur
        except ValueError:
            return status, None, dur


def photo(kind, shift=0):
    img = Image.new("RGB", (320, 240), (235, 235, 235))
    d = ImageDraw.Draw(img)
    if kind == "backpack":
        d.rounded_rectangle((90 + shift, 50, 230 + shift, 210), radius=28, fill=(30, 30, 30))
        d.rectangle((120 + shift, 150, 200 + shift, 190), fill=(55, 55, 55))
        d.ellipse((215 + shift, 120, 232 + shift, 137), fill=(200, 30, 30))  # red keychain
    else:
        d.ellipse((60, 90, 150, 180), fill=(250, 250, 250), outline=(90, 90, 90), width=3)
        d.ellipse((150, 120, 250, 200), fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def multipart(content):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"p.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://lostlinkai-98em.onrender.com")
    args = ap.parse_args()
    api = Api(args.api)
    now = datetime.now(timezone.utc)
    lost_at = (now - timedelta(hours=3)).replace(microsecond=0).isoformat()
    found_at = (now - timedelta(hours=1)).replace(microsecond=0).isoformat()
    canary = f"smoke-canary-{uuid.uuid4().hex[:6]}"

    status, _, dur = api.call("GET", "/health")[0], None, 0
    t0 = time.perf_counter()
    status, body, dur = api.json("GET", "/health")
    check("health returns 200 with database true", status == 200 and body.get("database") is True, f"{dur:.2f} s")

    def register(name):
        email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
        s, b, _ = api.json("POST", "/auth/register", {"name": name, "email": email, "password": secrets.token_urlsafe(16)})
        assert s == 201, s
        return b["access_token"]

    owner, finder = register("Smoke Owner"), register("Smoke Finder")

    lost = api.json("POST", "/reports", {"report_type": "LOST", "category": "Backpack", "name": "Black backpack",
                    "description": "Black backpack lost near gate 3", "color": "Black", "distinctive_features": "red keychain",
                    "private_details": f"Contains a notebook: {canary}", "date_time": lost_at, "location": "Gate 3",
                    "place_key": "gate-3"}, owner)[1]["id"]
    found = api.json("POST", "/reports", {"report_type": "FOUND", "category": "Backpack", "name": "Black backpack",
                     "description": "Black backpack found near gate 3", "color": "Black", "distinctive_features": "red keychain",
                     "date_time": found_at, "location": "Gate 3", "place_key": "gate-3"}, finder)[1]["id"]
    charger = api.json("POST", "/reports", {"report_type": "FOUND", "category": "Charger", "name": "Charger",
                       "description": "Charger found near gate 3", "date_time": found_at, "location": "Gate 3",
                       "place_key": "gate-3"}, finder)[1]["id"]
    created = [(lost, owner), (found, finder), (charger, finder)]
    image_urls = []
    for rid, tok in ((lost, owner), (found, finder)):
        for shift in (0, 4):
            body, ctype = multipart(photo("backpack", shift))
            s, b, _ = api.json("POST", f"/reports/{rid}/images", token=tok, raw=body, ctype=ctype)
            check(f"photo uploaded to report {rid} (Cloudinary-backed in production)", s == 201, str(s))
            if rid == lost:
                image_urls.append(b["url"])
    for _ in range(2):
        body, ctype = multipart(photo("charger"))
        api.json("POST", f"/reports/{charger}/images", token=finder, raw=body, ctype=ctype)

    # Search again: one controlled matching request, timed.
    s, body, dur = api.json("POST", f"/reports/{lost}/match", token=owner)
    check("Search again executes matching (POST /match 200)", s == 200, f"{dur:.2f} s")
    check("Search again returns the current candidates", s == 200 and isinstance(body.get("matches"), list))
    # Identify OUR pair from the finder's side: other owners' candidates may also match the lost report.
    # The pair we created is the only match that appears in BOTH the owner's list (for our lost report) and the
    # finder's list (for our found report). Other owners' candidates appear in only one of them.
    owner_side = api.json("GET", f"/reports/{lost}/matches", token=owner)[1]["matches"]
    finder_side = api.json("GET", f"/reports/{found}/matches", token=finder)[1]["matches"]
    shared_ids = {m["id"] for m in owner_side} & {m["id"] for m in finder_side}
    backpack = [m for m in owner_side if m["id"] in shared_ids and m.get("lead") in ("STRONG", "POSSIBLE", "WEAK")]
    check("backpack pair with a red keychain produces a lead (WEAK or stronger)", len(backpack) == 1,
          f"shared matches {len(shared_ids)}; leads {[m.get('lead') for m in backpack]}")
    lead = backpack[0]["lead"] if backpack else None
    check("the owner reloads the persisted match for this pair", len(backpack) == 1)
    check("no notification is sent for a WEAK lead",
          lead != "WEAK" or not any(n.get("type") in ("match_owner", "match_finder") for n in
                                    api.json("GET", "/notifications?limit=50", token=owner)[1].get("notifications", [])))
    if lead == "WEAK":
        s, _, _ = api.json("POST", f"/matches/{backpack[0]['id']}/verification", token=owner)
        check("a WEAK lead cannot start ownership verification (409)", s == 409, str(s))

    # Negative control: the backpack owner's report is not matched with the charger.
    cs, cb, _ = api.json("POST", f"/reports/{charger}/match", token=finder)
    check("negative control: the charger is not matched with the backpack", cs == 200 and cb["matches"] == [],
          f"status {cs}, matches {len((cb or {}).get('matches', []))}")

    # Private data never reaches the other party.
    fs, fbody, _ = api.json("GET", f"/reports/{lost}", token=finder)
    raw_finder_view = json.dumps(fbody) if fs == 200 else ""
    check("finder's view of the owner's report omits the private canary", canary not in raw_finder_view and fs in (200, 404))
    _, mbody, _ = api.json("GET", f"/reports/{found}/matches", token=finder)
    check("finder's match list omits the owner's private canary", canary not in json.dumps(mbody))

    # Authenticated image retrieval.
    image_url = image_urls[0]
    s, ctype, _, _ = api.call("GET", image_url)
    check("image is served to its owner with a valid token (200 image)", s == 200 and ctype.startswith("image/"), f"{s} {ctype}")
    base_path = image_url.split("?")[0]
    check("missing token is refused", api.call("GET", base_path)[0] == 422)
    check("invalid token is refused", api.call("GET", base_path + "?token=not-a-real-token")[0] == 404)

    # Cleanup: only the records this script created.
    for rid, tok in created:
        api.call("DELETE", f"/reports/{rid}", token=tok)
    gone = [api.json("GET", f"/reports/{rid}", token=tok)[0] for rid, tok in created]
    check("cleanup: all three test reports are gone (404)", all(g == 404 for g in gone), str(gone))

    print(f"\nRESULT: {sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

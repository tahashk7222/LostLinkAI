"""Create demo accounts for the hackathon demo (local use only).

    python -m scripts.seed_demo            # accounts only (report items live during the demo)
    python -m scripts.seed_demo --reports  # also create the backpack lost/found pair

Accounts are clearly demo accounts; do not run this against production.
"""

import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ai.orchestrator import process_report
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import init_db
from app.models import ItemReport, User
from app.models.enums import ReportType, Role

DEMO_PASSWORD = "demo-pass-123"
ACCOUNTS = [
    ("Admin Demo", "admin@lostlink.demo", Role.ADMIN),
    ("Ayesha Owner", "ayesha@lostlink.demo", Role.USER),
    ("Bilal Finder", "bilal@lostlink.demo", Role.USER),
]


def main() -> None:
    if get_settings().app_env == "production":
        sys.exit("Refusing to seed demo data in production.")
    init_db()
    with SessionLocal() as db:
        users = {}
        for name, email, role in ACCOUNTS:
            u = db.scalar(select(User).where(User.email == email))
            if not u:
                u = User(name=name, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role)
                db.add(u)
                db.flush()
            users[email] = u
        db.commit()

        if "--reports" in sys.argv:
            t = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
            lost = ItemReport(
                user_id=users["ayesha@lostlink.demo"].id, report_type=ReportType.LOST, category="Backpack",
                name="Black backpack", description="I lost my black backpack near the library at around 3 PM.",
                color="Black", brand="JanSport", distinctive_features="Red keychain on the front zipper",
                private_details="Blue calculus notebook, Casio calculator, green water bottle",
                date_time=t, location="Main Library", latitude=33.6425, longitude=72.993)
            found = ItemReport(
                user_id=users["bilal@lostlink.demo"].id, report_type=ReportType.FOUND, category="Backpack",
                name="Black backpack", description="I found a black backpack near the library around 3:30 PM.",
                color="Black", brand="JanSport", distinctive_features="Red keychain attached to the zipper",
                private_details="Has a blue notebook with calculus notes and a calculator inside",
                date_time=t + timedelta(minutes=30), location="Library Courtyard", latitude=33.6431, longitude=72.9941)
            db.add_all([lost, found])
            db.commit()
            process_report(lost.id)
            process_report(found.id)

    print("Demo accounts (password: %s):" % DEMO_PASSWORD)
    for name, email, role in ACCOUNTS:
        print(f"  {role.value:5}  {email}")


if __name__ == "__main__":
    main()

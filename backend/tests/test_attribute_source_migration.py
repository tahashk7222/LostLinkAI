"""Migration 0004 relabels legacy rule-inferred attributes from AI to RULE."""

import tempfile

from sqlalchemy import create_engine, text

from app.db.migrate import run_migrations


def test_legacy_ai_attributes_become_rule(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    run_migrations(eng, target="0003")
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at) "
                          "VALUES (1, 'Old', 'old@x.com', 'x', 'USER', 1, '2026-01-01', '2026-01-01')"))
        conn.execute(text(
            "INSERT INTO item_reports (id, user_id, report_type, category, name, description, date_time, location, "
            "status, ai_status, created_at, updated_at) VALUES (1, 1, 'LOST', 'Wallet', 'Brown wallet', "
            "'Old report', '2026-01-01', 'Somewhere', 'ACTIVE', 'DONE', '2026-01-01', '2026-01-01')"))
        conn.execute(text(
            "INSERT INTO item_attributes (report_id, attribute_name, attribute_value, source, confidence, created_at) "
            "VALUES (1, 'color', 'red', 'AI', 0.7, '2026-01-01'), (1, 'color', 'brown', 'USER', 1.0, '2026-01-01')"))
    run_migrations(eng)
    with eng.connect() as conn:
        rows = dict(conn.execute(text("SELECT attribute_value, source FROM item_attributes")).all())
    eng.dispose()
    assert rows == {"red": "RULE", "brown": "USER"}

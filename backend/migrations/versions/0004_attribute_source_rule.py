"""relabel rule-inferred attributes: AI -> RULE

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 00:00:00

Attributes inferred by the deterministic understanding rules were stored with source "AI".
No learned model was ever used, so they are relabelled RULE. The data change is applied on
every backend.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Native enum types need the new label added first; ADD VALUE cannot run inside a transaction.
        with op.get_context().autocommit_block():
            op.execute(sa.text("ALTER TYPE attributesource ADD VALUE IF NOT EXISTS 'RULE'"))
    op.execute(sa.text("UPDATE item_attributes SET source = 'RULE' WHERE source = 'AI'"))


def downgrade() -> None:
    # The Postgres enum keeps the RULE label (enum values cannot be removed safely); rows are relabelled back.
    op.execute(sa.text("UPDATE item_attributes SET source = 'AI' WHERE source = 'RULE'"))

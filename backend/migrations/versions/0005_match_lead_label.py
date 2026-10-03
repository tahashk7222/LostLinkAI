"""match candidate lead label (scoring v2)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL means the suggestion was created before scoring v2. It is treated as notifiable, as before.
    with op.batch_alter_table('match_candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lead_label', sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('match_candidates', schema=None) as batch_op:
        batch_op.drop_column('lead_label')

"""case possession confirmed time (finder confirms they still have the item)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: existing cases have no possession confirmation yet. Nothing is deleted.
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('possession_confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('cases', schema=None) as batch_op:
        batch_op.drop_column('possession_confirmed_at')

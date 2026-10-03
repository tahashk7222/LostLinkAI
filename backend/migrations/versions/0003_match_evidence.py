"""match candidate structured evidence

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: suggestions created before this migration keep only the display explanation.
    with op.batch_alter_table('match_candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evidence', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('match_candidates', schema=None) as batch_op:
        batch_op.drop_column('evidence')

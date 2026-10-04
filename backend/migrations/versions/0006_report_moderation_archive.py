"""report moderation reason, note, moderator and archive time

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All new columns are nullable: existing reports keep their values and nothing is deleted.
    with op.batch_alter_table('item_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('moderation_reason', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('moderation_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('moderated_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_item_reports_moderated_by_users', 'users', ['moderated_by'], ['id'],
                                    ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('item_reports', schema=None) as batch_op:
        batch_op.drop_constraint('fk_item_reports_moderated_by_users', type_='foreignkey')
        batch_op.drop_column('archived_at')
        batch_op.drop_column('moderated_at')
        batch_op.drop_column('moderated_by')
        batch_op.drop_column('moderation_note')
        batch_op.drop_column('moderation_reason')

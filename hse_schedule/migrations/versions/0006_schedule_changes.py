"""schedule_changes

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa

from hse_schedule.db import UTCDateTime


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('lesson_changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lesson_id', sa.String(length=128), nullable=False),
    sa.Column('group_oid', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('was_starts_at', UTCDateTime(), nullable=False),
    sa.Column('was_ends_at', UTCDateTime(), nullable=False),
    sa.Column('was_room', sa.String(length=64), nullable=True),
    sa.Column('new_starts_at', UTCDateTime(), nullable=True),
    sa.Column('new_ends_at', UTCDateTime(), nullable=True),
    sa.Column('new_room', sa.String(length=64), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('author_id', sa.Uuid(), nullable=True),
    sa.Column('author_name', sa.String(length=200), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('moved', 'cancelled', 'room')", name=op.f('ck_lesson_changes_kind_known')),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_lesson_changes_author_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lesson_changes')),
    sa.UniqueConstraint('lesson_id', name=op.f('uq_lesson_changes_lesson_id'))
    )


def downgrade() -> None:
    op.drop_table('lesson_changes')

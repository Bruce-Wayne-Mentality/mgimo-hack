"""booking

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hse_schedule.db import UTCDateTime

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('resources',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('building', sa.String(length=64), nullable=False),
    sa.Column('floor', sa.Integer(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('features', JSON_TYPE, nullable=False),
    sa.Column('room', sa.String(length=32), nullable=True),
    sa.Column('opens', sa.String(length=5), nullable=False),
    sa.Column('closes', sa.String(length=5), nullable=False),
    sa.Column('host', sa.String(length=200), nullable=True),
    sa.Column('is_bookable', sa.Boolean(), nullable=False),
    sa.CheckConstraint("kind IN ('classroom', 'coworking', 'consultation')", name=op.f('ck_resources_kind_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resources')),
    sa.UniqueConstraint('code', name=op.f('uq_resources_code'))
    )
    op.create_table('bookings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('starts_at', UTCDateTime(), nullable=False),
    sa.Column('ends_at', UTCDateTime(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('purpose', sa.String(length=200), nullable=True),
    sa.Column('checked_in_at', UTCDateTime(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('active', 'cancelled', 'released', 'done')", name=op.f('ck_bookings_status_known')),
    sa.CheckConstraint('ends_at > starts_at', name=op.f('ck_bookings_positive_duration')),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_bookings_resource_id_resources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_bookings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings'))
    )
    op.create_index('ix_bookings_resource_start', 'bookings', ['resource_id', 'starts_at'], unique=False)
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        # K6: two active bookings of one resource can never overlap, even under concurrent requests.
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute(
            "ALTER TABLE bookings ADD CONSTRAINT ex_bookings_no_overlap "
            "EXCLUDE USING gist (resource_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status = 'active')"
        )



def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ex_bookings_no_overlap")
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index('ix_bookings_resource_start', table_name='bookings')

    op.drop_table('bookings')
    op.drop_table('resources')

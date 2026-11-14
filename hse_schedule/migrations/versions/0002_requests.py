"""requests

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hse_schedule.db import UTCDateTime

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('request_counters',
    sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('year', name=op.f('pk_request_counters'))
    )
    op.create_table('request_types',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('result', sa.String(length=200), nullable=False),
    sa.Column('sla_days', sa.Integer(), nullable=False),
    sa.Column('auto_issue', sa.Boolean(), nullable=False),
    sa.Column('fields', JSON_TYPE, nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.CheckConstraint('sla_days >= 0', name=op.f('ck_request_types_sla_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_types')),
    sa.UniqueConstraint('code', name=op.f('uq_request_types_code'))
    )
    op.create_table('requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.String(length=24), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('type_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('payload', JSON_TYPE, nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=True),
    sa.Column('assignee_id', sa.Uuid(), nullable=True),
    sa.Column('result_note', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.Column('due_at', UTCDateTime(), nullable=False),
    sa.Column('closed_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("status IN ('submitted', 'in_review', 'needs_info', 'ready', 'rejected', 'cancelled')", name=op.f('ck_requests_status_known')),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], name=op.f('fk_requests_assignee_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_requests_student_id_students'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_id'], ['request_types.id'], name=op.f('fk_requests_type_id_request_types'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_requests')),
    sa.UniqueConstraint('number', name=op.f('uq_requests_number')),
    sa.UniqueConstraint('student_id', 'idempotency_key', name='uq_requests_student_idempotency')
    )
    op.create_index('ix_requests_status_due', 'requests', ['status', 'due_at'], unique=False)
    op.create_index('ix_requests_student_created', 'requests', ['student_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_requests_type_id'), 'requests', ['type_id'], unique=False)

    op.create_table('request_comments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('internal', sa.Boolean(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_request_comments_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name=op.f('fk_request_comments_request_id_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_comments'))
    )
    op.create_index(op.f('ix_request_comments_request_id'), 'request_comments', ['request_id'], unique=False)

    op.create_table('request_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.String(length=16), nullable=True),
    sa.Column('to_status', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_request_events_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name=op.f('fk_request_events_request_id_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_events'))
    )
    op.create_index(op.f('ix_request_events_request_id'), 'request_events', ['request_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_request_events_request_id'), table_name='request_events')

    op.drop_table('request_events')
    op.drop_index(op.f('ix_request_comments_request_id'), table_name='request_comments')

    op.drop_table('request_comments')
    op.drop_index(op.f('ix_requests_type_id'), table_name='requests')
    op.drop_index('ix_requests_student_created', table_name='requests')
    op.drop_index('ix_requests_status_due', table_name='requests')

    op.drop_table('requests')
    op.drop_table('request_types')
    op.drop_table('request_counters')

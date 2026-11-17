"""redbutton

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hse_schedule.db import UTCDateTime

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The first «Красная кнопка» (K7, 0004) is replaced by the specification version.
    op.drop_table('complaint_events')
    op.drop_table('complaints')
    op.drop_table('complaint_counters')
    op.create_table('complaint_counters',
    sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('year', name=op.f('pk_complaint_counters'))
    )
    op.create_table('moderation_buffer',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('author_ref', sa.String(length=64), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('form', JSON_TYPE, nullable=False),
    sa.Column('key_id', sa.String(length=8), nullable=False),
    sa.Column('nonce', sa.LargeBinary(), nullable=False),
    sa.Column('ct', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_buffer'))
    )
    op.create_index(op.f('ix_moderation_buffer_expires_at'), 'moderation_buffer', ['expires_at'], unique=False)
    op.create_index(op.f('ix_moderation_buffer_session_id'), 'moderation_buffer', ['session_id'], unique=False)

    op.create_table('complaints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('category_source', sa.String(length=8), nullable=False),
    sa.Column('subject_type', sa.String(length=16), nullable=True),
    sa.Column('subject_user_id', sa.Uuid(), nullable=True),
    sa.Column('link_type', sa.String(length=16), nullable=True),
    sa.Column('link_id', sa.String(length=64), nullable=True),
    sa.Column('link_label', sa.String(length=200), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('title_source', sa.String(length=8), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('privacy', sa.String(length=16), nullable=False),
    sa.Column('author_ref', sa.String(length=64), nullable=False),
    sa.Column('desired_outcome', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('department', sa.String(length=120), nullable=False),
    sa.Column('assignee_id', sa.Uuid(), nullable=True),
    sa.Column('escalated', sa.Boolean(), nullable=False),
    sa.Column('take_due_at', UTCDateTime(), nullable=False),
    sa.Column('answer_due_at', UTCDateTime(), nullable=False),
    sa.Column('paused_at', UTCDateTime(), nullable=True),
    sa.Column('taken_at', UTCDateTime(), nullable=True),
    sa.Column('answered_at', UTCDateTime(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.Column('closed_at', UTCDateTime(), nullable=True),
    sa.Column('resolved_by_student', sa.Boolean(), nullable=True),
    sa.Column('moderation_reason', sa.String(length=32), nullable=True),
    sa.Column('return_comment', sa.Text(), nullable=True),
    sa.Column('flags', JSON_TYPE, nullable=False),
    sa.Column('ai', JSON_TYPE, nullable=False),
    sa.Column('stage2_state', sa.String(length=12), nullable=False),
    sa.Column('stage2_attempts', sa.Integer(), nullable=False),
    sa.Column('stage2_next_at', UTCDateTime(), nullable=True),
    sa.Column('body_ct', sa.LargeBinary(), nullable=False),
    sa.Column('body_dek', sa.LargeBinary(), nullable=True),
    sa.CheckConstraint("privacy IN ('named', 'confidential', 'anonymous')", name=op.f('ck_complaints_privacy_known')),
    sa.CheckConstraint("status IN ('MODERATION', 'NEW', 'IN_PROGRESS', 'NEED_INFO', 'ANSWERED', 'ESCALATED', 'CLOSED', 'WITHDRAWN', 'RETURNED')", name=op.f('ck_complaints_status_known')),
    sa.CheckConstraint("type IN ('unfair', 'problem', 'suggestion', 'thanks')", name=op.f('ck_complaints_type_known')),
    sa.CheckConstraint('priority BETWEEN 1 AND 3', name=op.f('ck_complaints_priority_range')),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], name=op.f('fk_complaints_assignee_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['subject_user_id'], ['users.id'], name=op.f('fk_complaints_subject_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaints')),
    sa.UniqueConstraint('number', name=op.f('uq_complaints_number'))
    )
    op.create_index(op.f('ix_complaints_author_ref'), 'complaints', ['author_ref'], unique=False)
    op.create_index('ix_complaints_status_priority', 'complaints', ['status', 'priority', 'answer_due_at'], unique=False)

    op.create_table('complaint_authors',
    sa.Column('complaint_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_authors_complaint_id_complaints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_complaint_authors_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('complaint_id', name=op.f('pk_complaint_authors'))
    )
    op.create_index(op.f('ix_complaint_authors_user_id'), 'complaint_authors', ['user_id'], unique=False)

    op.create_table('complaint_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('complaint_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.String(length=16), nullable=True),
    sa.Column('to_status', sa.String(length=16), nullable=False),
    sa.Column('actor_role', sa.String(length=16), nullable=False),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_events_complaint_id_complaints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaint_events'))
    )
    op.create_index(op.f('ix_complaint_events_complaint_id'), 'complaint_events', ['complaint_id'], unique=False)

    op.create_table('complaint_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('complaint_id', sa.Uuid(), nullable=False),
    sa.Column('from_role', sa.String(length=16), nullable=False),
    sa.Column('author_name', sa.String(length=200), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('body_ct', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_messages_complaint_id_complaints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaint_messages'))
    )
    op.create_index(op.f('ix_complaint_messages_complaint_id'), 'complaint_messages', ['complaint_id'], unique=False)

    op.create_table('moderation_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=True),
    sa.Column('complaint_id', sa.Uuid(), nullable=True),
    sa.Column('stage', sa.Integer(), nullable=False),
    sa.Column('verdict', sa.String(length=24), nullable=False),
    sa.Column('scores', JSON_TYPE, nullable=False),
    sa.Column('flags', JSON_TYPE, nullable=False),
    sa.Column('text_hmac', sa.String(length=64), nullable=True),
    sa.Column('models', JSON_TYPE, nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_moderation_events_complaint_id_complaints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_events'))
    )
    op.create_index(op.f('ix_moderation_events_session_id'), 'moderation_events', ['session_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_moderation_events_session_id'), table_name='moderation_events')

    op.drop_table('moderation_events')
    op.drop_index(op.f('ix_complaint_messages_complaint_id'), table_name='complaint_messages')

    op.drop_table('complaint_messages')
    op.drop_index(op.f('ix_complaint_events_complaint_id'), table_name='complaint_events')

    op.drop_table('complaint_events')
    op.drop_index(op.f('ix_complaint_authors_user_id'), table_name='complaint_authors')

    op.drop_table('complaint_authors')
    op.drop_index('ix_complaints_status_priority', table_name='complaints')
    op.drop_index(op.f('ix_complaints_author_ref'), table_name='complaints')

    op.drop_table('complaints')
    op.drop_index(op.f('ix_moderation_buffer_session_id'), table_name='moderation_buffer')
    op.drop_index(op.f('ix_moderation_buffer_expires_at'), table_name='moderation_buffer')

    op.drop_table('moderation_buffer')
    op.drop_table('complaint_counters')
    # Restore the 0004 tables.
    op.create_table('complaint_counters',
    sa.Column('year', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('year', name=op.f('pk_complaint_counters'))
    )
    op.create_table('complaints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('happened_on', sa.Date(), nullable=True),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=True),
    sa.Column('track_hash', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('response', sa.Text(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('first_response_due', UTCDateTime(), nullable=False),
    sa.Column('resolve_due', UTCDateTime(), nullable=False),
    sa.Column('responded_at', UTCDateTime(), nullable=True),
    sa.Column('closed_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("mode <> 'anonymous' OR author_id IS NULL", name=op.f('ck_complaints_anonymous_has_no_author')),
    sa.CheckConstraint("mode IN ('open', 'confidential', 'anonymous')", name=op.f('ck_complaints_mode_known')),
    sa.CheckConstraint("status IN ('new', 'accepted', 'investigating', 'resolved', 'rejected', 'escalated')", name=op.f('ck_complaints_status_known')),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_complaints_author_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaints')),
    sa.UniqueConstraint('number', name=op.f('uq_complaints_number')),
    sa.UniqueConstraint('track_hash', name=op.f('uq_complaints_track_hash'))
    )
    op.create_index(op.f('ix_complaints_author_id'), 'complaints', ['author_id'], unique=False)
    op.create_table('complaint_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('complaint_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.String(length=16), nullable=True),
    sa.Column('to_status', sa.String(length=16), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_events_complaint_id_complaints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaint_events'))
    )
    op.create_index(op.f('ix_complaint_events_complaint_id'), 'complaint_events', ['complaint_id'], unique=False)

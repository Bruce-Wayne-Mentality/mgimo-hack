"""campus_services

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa

from hse_schedule.db import UTCDateTime


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    op.create_table('ics_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ics_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_ics_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_ics_tokens_token_hash'))
    )
    op.create_table('announcements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=True),
    sa.Column('author_name', sa.String(length=200), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('audience', sa.String(length=16), nullable=False),
    sa.Column('faculty_id', sa.Uuid(), nullable=True),
    sa.Column('course', sa.Integer(), nullable=True),
    sa.Column('group_id', sa.Uuid(), nullable=True),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('important', sa.Boolean(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.CheckConstraint("audience IN ('all', 'faculty', 'course', 'group')", name=op.f('ck_announcements_audience_known')),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_announcements_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['faculty_id'], ['faculties.id'], name=op.f('fk_announcements_faculty_id_faculties'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_announcements_group_id_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_announcements'))
    )
    op.create_index(op.f('ix_announcements_created_at'), 'announcements', ['created_at'], unique=False)

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

    op.create_table('documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('public_id', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('holder_initials', sa.String(length=16), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('signature', sa.String(length=64), nullable=False),
    sa.Column('issued_at', UTCDateTime(), nullable=False),
    sa.Column('revoked_at', UTCDateTime(), nullable=True),
    sa.Column('revoke_reason', sa.Text(), nullable=True),
    sa.Column('pdf', sa.LargeBinary(), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name=op.f('fk_documents_request_id_requests'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_documents_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('public_id', name=op.f('uq_documents_public_id')),
    sa.UniqueConstraint('request_id', name=op.f('uq_documents_request_id'))
    )
    op.create_index(op.f('ix_documents_student_id'), 'documents', ['student_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_documents_student_id'), table_name='documents')

    op.drop_table('documents')
    op.drop_index(op.f('ix_complaint_events_complaint_id'), table_name='complaint_events')

    op.drop_table('complaint_events')
    op.drop_index(op.f('ix_announcements_created_at'), table_name='announcements')

    op.drop_table('announcements')
    op.drop_table('ics_tokens')
    op.drop_index(op.f('ix_complaints_author_id'), table_name='complaints')

    op.drop_table('complaints')
    op.drop_table('complaint_counters')

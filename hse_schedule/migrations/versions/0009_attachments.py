"""attachments

Attachments in request chats and in the red button (files on disk, names and
metadata here; red button names encrypted).

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa

from hse_schedule.db import UTCDateTime


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('complaint_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('complaint_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('owner_ref', sa.String(length=64), nullable=False),
    sa.Column('from_role', sa.String(length=16), nullable=False),
    sa.Column('name_ct', sa.LargeBinary(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('mime', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=36), nullable=False),
    sa.Column('key_id', sa.String(length=8), nullable=True),
    sa.Column('check_status', sa.String(length=16), nullable=False),
    sa.Column('check_reason', sa.String(length=32), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=True),
    sa.Column('attached_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("check_status IN ('ok', 'blocked', 'unverified', 'skipped')", name=op.f('ck_complaint_attachments_check_known')),
    sa.CheckConstraint("kind IN ('pdf', 'docx', 'jpeg', 'png')", name=op.f('ck_complaint_attachments_kind_known')),
    sa.ForeignKeyConstraint(['complaint_id'], ['complaints.id'], name=op.f('fk_complaint_attachments_complaint_id_complaints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['complaint_messages.id'], name=op.f('fk_complaint_attachments_message_id_complaint_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaint_attachments')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_complaint_attachments_storage_key'))
    )
    op.create_index(op.f('ix_complaint_attachments_complaint_id'), 'complaint_attachments', ['complaint_id'], unique=False)
    op.create_index(op.f('ix_complaint_attachments_expires_at'), 'complaint_attachments', ['expires_at'], unique=False)
    op.create_index(op.f('ix_complaint_attachments_message_id'), 'complaint_attachments', ['message_id'], unique=False)
    op.create_index(op.f('ix_complaint_attachments_owner_ref'), 'complaint_attachments', ['owner_ref'], unique=False)

    op.create_table('request_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('comment_id', sa.Uuid(), nullable=True),
    sa.Column('uploader_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('mime', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=36), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('attached_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("kind IN ('pdf', 'docx', 'jpeg', 'png')", name=op.f('ck_request_attachments_kind_known')),
    sa.ForeignKeyConstraint(['comment_id'], ['request_comments.id'], name=op.f('fk_request_attachments_comment_id_request_comments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name=op.f('fk_request_attachments_request_id_requests'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploader_id'], ['users.id'], name=op.f('fk_request_attachments_uploader_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_attachments')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_request_attachments_storage_key'))
    )
    op.create_index(op.f('ix_request_attachments_comment_id'), 'request_attachments', ['comment_id'], unique=False)
    op.create_index(op.f('ix_request_attachments_request_id'), 'request_attachments', ['request_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_request_attachments_request_id'), table_name='request_attachments')
    op.drop_index(op.f('ix_request_attachments_comment_id'), table_name='request_attachments')

    op.drop_table('request_attachments')
    op.drop_index(op.f('ix_complaint_attachments_owner_ref'), table_name='complaint_attachments')
    op.drop_index(op.f('ix_complaint_attachments_message_id'), table_name='complaint_attachments')
    op.drop_index(op.f('ix_complaint_attachments_expires_at'), table_name='complaint_attachments')
    op.drop_index(op.f('ix_complaint_attachments_complaint_id'), table_name='complaint_attachments')

    op.drop_table('complaint_attachments')

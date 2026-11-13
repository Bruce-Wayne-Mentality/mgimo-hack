"""accounts, sessions and audit log

Revision ID: 0001
Revises: 
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hse_schedule.db import UTCDateTime

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('faculties',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_faculties')),
    sa.UniqueConstraint('code', name=op.f('uq_faculties_code'))
    )
    op.create_table('login_throttle',
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('window_started_at', UTCDateTime(), nullable=False),
    sa.Column('locked_until', UTCDateTime(), nullable=True),
    sa.PrimaryKeyConstraint('key_hash', name=op.f('pk_login_throttle'))
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('login', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('password_changed_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("role IN ('student', 'staff', 'admin')", name=op.f('ck_users_role_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('uq_users_login_lower', 'users', [sa.text('lower(login)')], unique=True)
    op.create_table('audit_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('object_type', sa.String(length=64), nullable=True),
    sa.Column('object_id', sa.String(length=64), nullable=True),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.Column('meta', JSON_TYPE, nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_log_actor_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_actor_id'), 'audit_log', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_log_at'), 'audit_log', ['at'], unique=False)

    op.create_table('groups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('faculty_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('course', sa.Integer(), nullable=False),
    sa.Column('program_code', sa.String(length=16), nullable=False),
    sa.Column('program_title', sa.String(length=200), nullable=False),
    sa.CheckConstraint('course BETWEEN 1 AND 6', name=op.f('ck_groups_course_range')),
    sa.ForeignKeyConstraint(['faculty_id'], ['faculties.id'], name=op.f('fk_groups_faculty_id_faculties'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_groups')),
    sa.UniqueConstraint('code', name=op.f('uq_groups_code'))
    )
    op.create_index(op.f('ix_groups_faculty_id'), 'groups', ['faculty_id'], unique=False)

    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('remember', sa.Boolean(), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('last_seen_at', UTCDateTime(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)

    op.create_table('staff',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('position', sa.String(length=200), nullable=False),
    sa.Column('faculty_id', sa.Uuid(), nullable=True),
    sa.Column('scopes', JSON_TYPE, nullable=False),
    sa.ForeignKeyConstraint(['faculty_id'], ['faculties.id'], name=op.f('fk_staff_faculty_id_faculties'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_staff_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_staff')),
    sa.UniqueConstraint('user_id', name=op.f('uq_staff_user_id'))
    )
    op.create_index(op.f('ix_staff_faculty_id'), 'staff', ['faculty_id'], unique=False)

    op.create_table('students',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('record_book_no', sa.String(length=32), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('study_form', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.CheckConstraint("status IN ('active', 'academic_leave', 'expelled', 'graduated')", name=op.f('ck_students_status_known')),
    sa.CheckConstraint("study_form IN ('full_time', 'part_time', 'distance')", name=op.f('ck_students_study_form_known')),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_students_group_id_groups'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_students_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_students')),
    sa.UniqueConstraint('email', name=op.f('uq_students_email')),
    sa.UniqueConstraint('record_book_no', name=op.f('uq_students_record_book_no')),
    sa.UniqueConstraint('user_id', name=op.f('uq_students_user_id'))
    )
    op.create_index(op.f('ix_students_group_id'), 'students', ['group_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_students_group_id'), table_name='students')

    op.drop_table('students')
    op.drop_index(op.f('ix_staff_faculty_id'), table_name='staff')

    op.drop_table('staff')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')

    op.drop_table('sessions')
    op.drop_index(op.f('ix_groups_faculty_id'), table_name='groups')

    op.drop_table('groups')
    op.drop_index(op.f('ix_audit_log_at'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_actor_id'), table_name='audit_log')

    op.drop_table('audit_log')
    op.drop_index('uq_users_login_lower', table_name='users')
    op.drop_table('users')
    op.drop_table('login_throttle')
    op.drop_table('faculties')

"""academics

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hse_schedule.db import UTCDateTime

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('disciplines',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('group_id', sa.Uuid(), nullable=False),
    sa.Column('semester', sa.String(length=32), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('teacher_name', sa.String(length=200), nullable=False),
    sa.Column('control_form', sa.String(length=16), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('admission_threshold', sa.Integer(), nullable=False),
    sa.Column('final_at', UTCDateTime(), nullable=True),
    sa.Column('final_room', sa.String(length=64), nullable=True),
    sa.CheckConstraint("control_form IN ('exam', 'credit', 'diff_credit', 'coursework')", name=op.f('ck_disciplines_control_form_known')),
    sa.CheckConstraint('admission_threshold BETWEEN 0 AND 100', name=op.f('ck_disciplines_threshold_range')),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_disciplines_group_id_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_disciplines')),
    sa.UniqueConstraint('group_id', 'semester', 'code', name='uq_disciplines_group_semester_code')
    )
    op.create_index(op.f('ix_disciplines_group_id'), 'disciplines', ['group_id'], unique=False)

    op.create_table('attendance',
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('discipline_id', sa.Uuid(), nullable=False),
    sa.Column('attended', sa.Integer(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.CheckConstraint('attended >= 0 AND attended <= total', name=op.f('ck_attendance_attended_range')),
    sa.ForeignKeyConstraint(['discipline_id'], ['disciplines.id'], name=op.f('fk_attendance_discipline_id_disciplines'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_attendance_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('student_id', 'discipline_id', name=op.f('pk_attendance'))
    )
    op.create_table('checkpoints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('discipline_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('weight', sa.Integer(), nullable=False),
    sa.Column('max_score', sa.Integer(), nullable=False),
    sa.Column('due_on', sa.Date(), nullable=True),
    sa.Column('critical', sa.Boolean(), nullable=False),
    sa.Column('is_final', sa.Boolean(), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.CheckConstraint('max_score > 0', name=op.f('ck_checkpoints_max_positive')),
    sa.CheckConstraint('weight BETWEEN 0 AND 100', name=op.f('ck_checkpoints_weight_range')),
    sa.ForeignKeyConstraint(['discipline_id'], ['disciplines.id'], name=op.f('fk_checkpoints_discipline_id_disciplines'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_checkpoints'))
    )
    op.create_index(op.f('ix_checkpoints_discipline_id'), 'checkpoints', ['discipline_id'], unique=False)

    op.create_table('nudge_mutes',
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('rule_code', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_nudge_mutes_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('student_id', 'rule_code', name=op.f('pk_nudge_mutes'))
    )
    op.create_table('nudges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('rule_code', sa.String(length=32), nullable=False),
    sa.Column('dedup_key', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('action', JSON_TYPE, nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("state IN ('new', 'seen', 'done', 'dismissed')", name=op.f('ck_nudges_state_known')),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_nudges_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_nudges')),
    sa.UniqueConstraint('student_id', 'dedup_key', name='uq_nudges_student_dedup')
    )
    op.create_index(op.f('ix_nudges_student_id'), 'nudges', ['student_id'], unique=False)

    op.create_table('past_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('semester_no', sa.Integer(), nullable=False),
    sa.Column('semester', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('control_form', sa.String(length=16), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('mark', sa.Integer(), nullable=True),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.CheckConstraint('mark IS NULL OR mark BETWEEN 2 AND 5', name=op.f('ck_past_results_mark_range')),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_past_results_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_past_results'))
    )
    op.create_index(op.f('ix_past_results_student_id'), 'past_results', ['student_id'], unique=False)

    op.create_table('risk_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('discipline_id', sa.Uuid(), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('p', sa.Float(), nullable=False),
    sa.Column('w', sa.Float(), nullable=False),
    sa.Column('pace', sa.Float(), nullable=True),
    sa.Column('r', sa.Float(), nullable=False),
    sa.Column('reasons', JSON_TYPE, nullable=False),
    sa.Column('computed_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("level IN ('green', 'yellow', 'red', 'grey')", name=op.f('ck_risk_snapshots_level_known')),
    sa.ForeignKeyConstraint(['discipline_id'], ['disciplines.id'], name=op.f('fk_risk_snapshots_discipline_id_disciplines'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_risk_snapshots_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_snapshots'))
    )
    op.create_index('ix_risk_snapshots_student_discipline', 'risk_snapshots', ['student_id', 'discipline_id', 'computed_at'], unique=False)

    op.create_table('grade_changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('checkpoint_id', sa.Uuid(), nullable=False),
    sa.Column('old_score', sa.Float(), nullable=True),
    sa.Column('new_score', sa.Float(), nullable=True),
    sa.Column('changed_by', sa.Uuid(), nullable=True),
    sa.Column('changed_by_name', sa.String(length=200), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_grade_changes_changed_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['checkpoint_id'], ['checkpoints.id'], name=op.f('fk_grade_changes_checkpoint_id_checkpoints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_grade_changes_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grade_changes'))
    )
    op.create_index('ix_grade_changes_student_checkpoint', 'grade_changes', ['student_id', 'checkpoint_id'], unique=False)

    op.create_table('grades',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('checkpoint_id', sa.Uuid(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('graded_at', UTCDateTime(), nullable=False),
    sa.Column('graded_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint('score >= 0', name=op.f('ck_grades_score_non_negative')),
    sa.ForeignKeyConstraint(['checkpoint_id'], ['checkpoints.id'], name=op.f('fk_grades_checkpoint_id_checkpoints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['graded_by'], ['users.id'], name=op.f('fk_grades_graded_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_grades_student_id_students'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_grades')),
    sa.UniqueConstraint('student_id', 'checkpoint_id', name='uq_grades_student_checkpoint')
    )
    op.create_index(op.f('ix_grades_checkpoint_id'), 'grades', ['checkpoint_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_grades_checkpoint_id'), table_name='grades')

    op.drop_table('grades')
    op.drop_index('ix_grade_changes_student_checkpoint', table_name='grade_changes')

    op.drop_table('grade_changes')
    op.drop_index('ix_risk_snapshots_student_discipline', table_name='risk_snapshots')

    op.drop_table('risk_snapshots')
    op.drop_index(op.f('ix_past_results_student_id'), table_name='past_results')

    op.drop_table('past_results')
    op.drop_index(op.f('ix_nudges_student_id'), table_name='nudges')

    op.drop_table('nudges')
    op.drop_table('nudge_mutes')
    op.drop_index(op.f('ix_checkpoints_discipline_id'), table_name='checkpoints')

    op.drop_table('checkpoints')
    op.drop_table('attendance')
    op.drop_index(op.f('ix_disciplines_group_id'), table_name='disciplines')

    op.drop_table('disciplines')

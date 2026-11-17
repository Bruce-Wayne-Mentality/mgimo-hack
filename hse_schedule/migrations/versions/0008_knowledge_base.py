"""knowledge_base

Revision ID: 0008
Revises: 0007

RAG for the assistant (K4): documents, fragments with float32 vectors as bytes
(no pgvector — works on PostgreSQL and SQLite) and the queue of unanswered
questions, which keeps only the masked text.
"""

from alembic import op
import sqlalchemy as sa

from hse_schedule.db import UTCDateTime


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('kb_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('doc_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('audience', sa.String(length=16), nullable=False),
    sa.Column('source_path', sa.String(length=300), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("kind IN ('regulation', 'portal')", name=op.f('ck_kb_documents_kind_known')),
    sa.CheckConstraint("status IN ('active', 'superseded', 'draft')", name=op.f('ck_kb_documents_status_known')),
    sa.CheckConstraint("audience IN ('all', 'foreign', 'bachelor', 'master')", name=op.f('ck_kb_documents_audience_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_documents')),
    sa.UniqueConstraint('doc_id', name=op.f('uq_kb_documents_doc_id'))
    )
    op.create_index(op.f('ix_kb_documents_status'), 'kb_documents', ['status'], unique=False)
    op.create_table('kb_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('ord', sa.Integer(), nullable=False),
    sa.Column('section_path', sa.String(length=300), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=True),
    sa.Column('embedding_model', sa.String(length=64), nullable=True),
    sa.CheckConstraint("kind IN ('clause', 'table', 'faq', 'paragraph')", name=op.f('ck_kb_chunks_kind_known')),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], name=op.f('fk_kb_chunks_document_id_kb_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_chunks')),
    sa.UniqueConstraint('document_id', 'ord', name=op.f('uq_kb_chunks_document_id'))
    )
    op.create_index(op.f('ix_kb_chunks_document_id'), 'kb_chunks', ['document_id'], unique=False)
    op.create_table('kb_gaps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('question_masked', sa.Text(), nullable=False),
    sa.Column('top_score', sa.Float(), nullable=False),
    sa.Column('top_chunk_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('answer_text', sa.Text(), nullable=True),
    sa.Column('answered_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('answered_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("status IN ('open', 'answered', 'rejected')", name=op.f('ck_kb_gaps_status_known')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_gaps'))
    )
    op.create_index(op.f('ix_kb_gaps_status'), 'kb_gaps', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_kb_gaps_status'), table_name='kb_gaps')
    op.drop_table('kb_gaps')
    op.drop_index(op.f('ix_kb_chunks_document_id'), table_name='kb_chunks')
    op.drop_table('kb_chunks')
    op.drop_index(op.f('ix_kb_documents_status'), table_name='kb_documents')
    op.drop_table('kb_documents')

"""Versioned DeepTutor indexes and pinned AI execution backend."""
from alembic import op
import sqlalchemy as sa

revision = '2d669cb4149a'
down_revision = '75d08ac3af22'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('v2_materials', sa.Column('original_sha256', sa.String(64), nullable=True))
    op.add_column('v2_ai_runs', sa.Column('backend', sa.String(30), server_default='bounded_chat', nullable=False))
    op.add_column('v2_ai_runs', sa.Column('metrics', sa.JSON(), server_default='{}', nullable=False))
    op.create_table('v2_tutor_indexes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('material_id', sa.String(36), sa.ForeignKey('v2_materials.id'), nullable=False),
        sa.Column('membership_id', sa.String(36), sa.ForeignKey('memberships.id'), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('principal', sa.String(200), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('next_at', sa.String(40), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.UniqueConstraint('material_id', 'sha256'))
    op.create_index('ix_v2_tutor_index_queue', 'v2_tutor_indexes', ['state', 'next_at'])
    op.create_table('v2_tutor_teaching_indexes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('membership_id', sa.String(36), sa.ForeignKey('memberships.id'), nullable=False),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('source_versions.id'), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('principal', sa.String(200), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('next_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('membership_id', 'version_id', 'sha256'))
    op.create_index('ix_tutor_teaching_index_queue', 'v2_tutor_teaching_indexes', ['state', 'next_at'])


def downgrade():
    op.drop_index('ix_tutor_teaching_index_queue', table_name='v2_tutor_teaching_indexes')
    op.drop_table('v2_tutor_teaching_indexes')
    op.drop_index('ix_v2_tutor_index_queue', table_name='v2_tutor_indexes')
    op.drop_table('v2_tutor_indexes')
    with op.batch_alter_table('v2_ai_runs') as batch:
        batch.drop_column('metrics')
        batch.drop_column('backend')
    with op.batch_alter_table('v2_materials') as batch:
        batch.drop_column('original_sha256')

"""Add private annual exam resources.

Revision ID: 75d08ac3af22
Revises: 61e064beac51
"""
from alembic import op
import sqlalchemy as sa

revision = '75d08ac3af22'
down_revision = '61e064beac51'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('v2_exam_resources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('v2_projects.id'), nullable=False),
        sa.Column('material_id', sa.String(36), sa.ForeignKey('v2_materials.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('edition', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('source', sa.JSON(), nullable=False),
        sa.Column('contents', sa.JSON(), nullable=False),
        sa.UniqueConstraint('project_id', 'kind', 'year', 'edition', name='uq_v2_exam_resource_edition'))
    op.create_index('ix_v2_exam_resources_project_id', 'v2_exam_resources', ['project_id'])
    op.create_index('ix_v2_assessment_deadline', 'v2_assessments', ['state', 'deadline_at'])
    op.create_index('ix_v2_ai_run_queue', 'v2_ai_runs', ['state', 'created_at'])
    op.create_index('ix_v2_ai_run_lease', 'v2_ai_runs', ['state', 'lease_until'])


def downgrade():
    op.drop_index('ix_v2_ai_run_lease', table_name='v2_ai_runs')
    op.drop_index('ix_v2_ai_run_queue', table_name='v2_ai_runs')
    op.drop_index('ix_v2_assessment_deadline', table_name='v2_assessments')
    op.drop_table('v2_exam_resources')

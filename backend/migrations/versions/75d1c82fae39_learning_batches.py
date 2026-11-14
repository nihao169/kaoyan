"""Persist daily plans and bounded tutor stages."""
from alembic import op
import sqlalchemy as sa

revision = '75d1c82fae39'
down_revision = '4a71dd1b1822'


def upgrade():
    op.create_table(
        'v2_learning_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('v2_projects.id'), nullable=False),
        sa.Column('scope_revision', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(80), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.UniqueConstraint('project_id', 'scope_revision', 'key'),
    )
    op.create_index('ix_v2_learning_batches_project_id', 'v2_learning_batches', ['project_id'])


def downgrade():
    op.drop_table('v2_learning_batches')

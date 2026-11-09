"""Scene-aware project bindings; original records remain intact."""
from alembic import op
import sqlalchemy as sa

revision = 'a418f6d28c09'
down_revision = '942b368ab73c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('v2_projects', sa.Column('course_name', sa.String(200), nullable=False, server_default=''))
    op.add_column('v2_projects', sa.Column('learning_goal', sa.Text(), nullable=False, server_default=''))
    op.add_column('v2_projects', sa.Column('scene_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('v2_project_learning',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('v2_projects.id'), nullable=False),
        sa.Column('scope_revision', sa.Integer(), nullable=False),
        sa.Column('plan_revision', sa.Integer(), nullable=False),
        sa.Column('path_id', sa.String(150), nullable=False),
        sa.Column('session_id', sa.String(150), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.UniqueConstraint('project_id', 'scope_revision', 'plan_revision'))
    op.create_index('ix_v2_project_learning_project_id', 'v2_project_learning', ['project_id'])


def downgrade():
    op.drop_table('v2_project_learning')
    for name in ('scene_confirmed', 'learning_goal', 'course_name'):
        op.drop_column('v2_projects', name)

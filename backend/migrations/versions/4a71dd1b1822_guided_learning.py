"""Save the confirmed scope for guided project learning."""
from alembic import op
import sqlalchemy as sa

revision = '4a71dd1b1822'
down_revision = 'a418f6d28c09'


def upgrade():
    op.add_column('v2_projects', sa.Column('study_scope', sa.JSON(), server_default='{}', nullable=False))


def downgrade():
    op.drop_column('v2_projects', 'study_scope')

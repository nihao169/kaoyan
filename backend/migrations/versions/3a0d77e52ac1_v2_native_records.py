"""Keep the project record backend durable across restarts and flag changes."""
from alembic import op
import sqlalchemy as sa


revision = '3a0d77e52ac1'
down_revision = '2d669cb4149a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('v2_projects', sa.Column('native_records', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('v2_projects') as batch:
        batch.drop_column('native_records')

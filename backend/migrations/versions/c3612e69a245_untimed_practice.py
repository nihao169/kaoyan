"""Allow untimed personal practice assessments."""
from alembic import op
import sqlalchemy as sa

revision = 'c3612e69a245'
down_revision = '75d1c82fae39'


def upgrade():
    with op.batch_alter_table('v2_assessments') as batch:
        batch.alter_column('deadline_at', existing_type=sa.String(40), nullable=True)


def downgrade():
    op.execute("UPDATE v2_assessments SET deadline_at = created_at WHERE deadline_at IS NULL")
    with op.batch_alter_table('v2_assessments') as batch:
        batch.alter_column('deadline_at', existing_type=sa.String(40), nullable=False)

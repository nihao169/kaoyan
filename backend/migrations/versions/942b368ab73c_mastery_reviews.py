"""Durable mappings and delivery for native Mastery Path reviews."""
from alembic import op
import sqlalchemy as sa

revision = '942b368ab73c'
down_revision = '3a0d77e52ac1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('v2_mastery_review_scopes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('membership_id', sa.String(36), sa.ForeignKey('memberships.id'), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=False),
        sa.Column('path_id', sa.String(80)),
        sa.UniqueConstraint('owner_id', 'kind', 'resource_id'))
    op.create_index('ix_v2_mastery_review_scopes_owner_id', 'v2_mastery_review_scopes', ['owner_id'])
    op.create_table('v2_mastery_review_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('scope_id', sa.String(36), sa.ForeignKey('v2_mastery_review_scopes.id'), nullable=False),
        sa.Column('attempt_id', sa.String(36), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('next_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('scope_id', 'attempt_id'))
    op.create_index('ix_mastery_review_pending', 'v2_mastery_review_events', ['state', 'next_at'])


def downgrade():
    op.drop_table('v2_mastery_review_events')
    op.drop_table('v2_mastery_review_scopes')

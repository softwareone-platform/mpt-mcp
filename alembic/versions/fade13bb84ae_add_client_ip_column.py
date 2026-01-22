"""add_client_ip_column

Revision ID: fade13bb84ae
Revises: 8ec0bd357032
Create Date: 2026-01-22 13:26:02.011840

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fade13bb84ae'
down_revision = '8ec0bd357032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add client_ip column and index to mcp_events table."""
    # Add client_ip column (supports IPv4 and IPv6, max 45 chars for IPv6)
    op.add_column('mcp_events', sa.Column('client_ip', sa.String(length=45), nullable=True))

    # Add index for IP address queries
    op.create_index('idx_events_client_ip', 'mcp_events', ['client_ip'])


def downgrade() -> None:
    """Remove client_ip column and index from mcp_events table."""
    op.drop_index('idx_events_client_ip', table_name='mcp_events')
    op.drop_column('mcp_events', 'client_ip')

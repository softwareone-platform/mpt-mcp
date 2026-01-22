"""initial analytics schema - simplified

Revision ID: 8ec0bd357032
Revises: 
Create Date: 2026-01-21 23:44:40.208331
Updated: 2026-01-22 - Simplified to only create mcp_events table

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '8ec0bd357032'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create simplified analytics schema with only mcp_events table."""
    # Create mcp_events table
    op.create_table('mcp_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('token_id', sa.String(length=20), nullable=True),
        sa.Column('api_endpoint', sa.String(length=100), nullable=True),
        sa.Column('session_id', sa.String(length=100), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('server_type', sa.String(length=20), nullable=True),
        sa.Column('tool_name', sa.String(length=100), nullable=True),
        sa.Column('resource_uri', sa.Text(), nullable=True),
        sa.Column('api_resource', sa.String(length=200), nullable=True),
        sa.Column('api_path', sa.Text(), nullable=True),
        sa.Column('api_method', sa.String(length=10), nullable=True),
        sa.Column('api_status_code', sa.Integer(), nullable=True),
        sa.Column('api_response_time_ms', sa.Integer(), nullable=True),
        sa.Column('result_count', sa.Integer(), nullable=True),
        sa.Column('rql_filter', sa.Text(), nullable=True),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('offset_value', sa.Integer(), nullable=True),
        sa.Column('order_by', sa.String(length=200), nullable=True),
        sa.Column('select_fields', sa.Text(), nullable=True),
        sa.Column('cache_hit', sa.Boolean(), nullable=True),
        sa.Column('cache_type', sa.String(length=50), nullable=True),
        sa.Column('error_type', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('server_version', sa.String(length=20), nullable=True),
        sa.Column('client_info', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for mcp_events
    op.create_index('idx_events_timestamp', 'mcp_events', [sa.literal_column('timestamp DESC')], unique=False)
    op.create_index('idx_events_token_id', 'mcp_events', ['token_id'], unique=False)
    op.create_index('idx_events_tool_name', 'mcp_events', ['tool_name'], unique=False)
    op.create_index('idx_events_api_resource', 'mcp_events', ['api_resource'], unique=False)
    op.create_index('idx_events_event_type', 'mcp_events', ['event_type'], unique=False)
    op.create_index('idx_events_error_type', 'mcp_events', ['error_type'], unique=False, postgresql_where=sa.text('error_type IS NOT NULL'))
    op.create_index('idx_events_date_token', 'mcp_events', [sa.literal_column('date(timestamp)'), 'token_id'], unique=False)
    op.create_index('idx_events_date_tool', 'mcp_events', [sa.literal_column('date(timestamp)'), 'tool_name'], unique=False)


def downgrade() -> None:
    """Drop mcp_events table and all its indexes."""
    op.drop_index('idx_events_date_tool', table_name='mcp_events')
    op.drop_index('idx_events_date_token', table_name='mcp_events')
    op.drop_index('idx_events_error_type', table_name='mcp_events', postgresql_where=sa.text('error_type IS NOT NULL'))
    op.drop_index('idx_events_event_type', table_name='mcp_events')
    op.drop_index('idx_events_api_resource', table_name='mcp_events')
    op.drop_index('idx_events_tool_name', table_name='mcp_events')
    op.drop_index('idx_events_token_id', table_name='mcp_events')
    op.drop_index('idx_events_timestamp', table_name='mcp_events')
    op.drop_table('mcp_events')

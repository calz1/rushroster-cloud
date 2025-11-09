"""add_registration_codes_table

Revision ID: b8382dc79fd9
Revises: a8354bf2e7c1
Create Date: 2025-10-22 18:14:52.017702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'b8382dc79fd9'
down_revision: Union[str, None] = 'a8354bf2e7c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'registration_codes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', UUID(as_uuid=True), nullable=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    )
    op.create_index('ix_registration_codes_code', 'registration_codes', ['code'])
    op.create_index('ix_registration_codes_active', 'registration_codes', ['is_active', 'code'])


def downgrade() -> None:
    op.drop_index('ix_registration_codes_active', table_name='registration_codes')
    op.drop_index('ix_registration_codes_code', table_name='registration_codes')
    op.drop_table('registration_codes')

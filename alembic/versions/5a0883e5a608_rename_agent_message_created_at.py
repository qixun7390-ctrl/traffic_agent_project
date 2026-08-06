"""rename agent message created at

Revision ID: 5a0883e5a608
Revises: 69f86ba5f2e4
Create Date: 2026-08-06 22:27:36.751304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a0883e5a608'
down_revision: Union[str, Sequence[str], None] = '69f86ba5f2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "agent_messages",
        "create_at",
        new_column_name="created_at",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "agent_messages",
        "created_at",
        new_column_name="create_at",
    )

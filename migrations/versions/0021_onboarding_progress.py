"""onboarding_progress — practice tasks an operator has finished

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-11 12:00:00

The playground on /onboarding ticks a task off when its validator accepts the
journey. Ticks live here, per operator, so they follow the person instead of the
browser. One row per (username, task_key); the key is a slug the server owns.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "onboarding_progress",
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("task_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("username", "task_key"),
        sa.ForeignKeyConstraint(["username"], ["users.username"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_onboarding_progress_username", "onboarding_progress", ["username"]
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_progress_username", table_name="onboarding_progress")
    op.drop_table("onboarding_progress")

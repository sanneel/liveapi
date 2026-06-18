"""cube_blocked_slot — operator-reserved empty cube slots

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-16 00:00:00

A blocked slot tells the cube resolver to leave a slot BLANK instead of
auto-filling it, so an operator can clear a slot and then place a specific
match. One row per (cube_slug, position). Independent of cube_override.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cube_blocked_slot",
        sa.Column("cube_slug", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("cube_slug", "position", name="pk_cube_blocked_slot"),
    )


def downgrade() -> None:
    op.drop_table("cube_blocked_slot")

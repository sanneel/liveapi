"""cube_override table — per-cube manual pins and suppressions

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-26 14:00:00

Introduces the `cube_override` table, the cube-side analogue of
`hot_override`. Each row pins or suppresses one match within one cube
theme; composite primary key (cube_slug, event_id) keeps cubes
independent of each other.

Forward-only and additive — no existing rows touched, no other tables
modified. Safe to apply on a running production DB.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cube_override",
        sa.Column("cube_slug", sa.String(), nullable=False),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("matches.event_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column(
            "suppress",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("cube_slug", "event_id", name="pk_cube_override"),
    )
    op.create_index("ix_cube_override_cube", "cube_override", ["cube_slug"])
    op.create_index("ix_cube_override_position", "cube_override", ["position"])
    op.create_index("ix_cube_override_suppress", "cube_override", ["suppress"])


def downgrade() -> None:
    op.drop_index("ix_cube_override_suppress", table_name="cube_override")
    op.drop_index("ix_cube_override_position", table_name="cube_override")
    op.drop_index("ix_cube_override_cube", table_name="cube_override")
    op.drop_table("cube_override")

"""hot_weight table — admin-editable per-sport scoring weights

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-28 12:00:00

Introduces the `hot_weight` table. Each row is one scoring rule
(league/team/word pattern → points) for one sport, with an optional active
window (starts_at/ends_at) so temporary boosts expire on their own.

Forward-only and additive — no existing rows touched, no other tables
modified. Safe to apply on a running production DB. The table starts empty;
the app seeds it from the static weights_<sport>.py modules on first use.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hot_weight",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("pattern", sa.String(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hot_weight"),
        sa.UniqueConstraint("sport", "kind", "pattern", name="uq_hot_weight_skp"),
    )
    op.create_index("ix_hot_weight_sport", "hot_weight", ["sport"])
    op.create_index(
        "ix_hot_weight_sport_enabled", "hot_weight", ["sport", "enabled"]
    )


def downgrade() -> None:
    op.drop_index("ix_hot_weight_sport_enabled", table_name="hot_weight")
    op.drop_index("ix_hot_weight_sport", table_name="hot_weight")
    op.drop_table("hot_weight")

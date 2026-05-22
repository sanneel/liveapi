"""positional pin + suppress on hot_override

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20 00:00:02

Replaces the legacy boolean-pin + boost-only override model with explicit
positional pinning and per-event suppression:

  position  Lock this event to slot N of the hot list for its sport
            (1-indexed). NULL = no positional lock.
  suppress  Hide this event from hot entirely, regardless of score.

The pre-existing columns (`boost`, `pin`) stay in place so old API clients
don't error; the new HotEngine simply ignores them in favor of position +
suppress.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("hot_override") as batch:
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("suppress", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_index("ix_hot_override_position", "hot_override", ["position"])
    op.create_index("ix_hot_override_suppress", "hot_override", ["suppress"])


def downgrade() -> None:
    op.drop_index("ix_hot_override_suppress", table_name="hot_override")
    op.drop_index("ix_hot_override_position", table_name="hot_override")
    with op.batch_alter_table("hot_override") as batch:
        batch.drop_column("suppress")
        batch.drop_column("position")

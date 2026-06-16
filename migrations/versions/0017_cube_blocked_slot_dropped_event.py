"""cube_blocked_slot — remember the match removed from a slot

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-16 00:00:00

When an operator empties a slot we suppress the match that was there so it
can't auto-fill another slot. Storing that event on the slot lets "restore
auto" un-suppress it again, so emptying a slot is reversible in one click.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cube_blocked_slot",
        sa.Column("dropped_event_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cube_blocked_slot", "dropped_event_id")

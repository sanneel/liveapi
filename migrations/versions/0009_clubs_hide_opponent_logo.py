"""clubs: hide_opponent_logo flag

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21 00:00:00

When a club page is used as fan-base creative for a single club, the admin
may not want the rival team's logo on the rendered PNG. This flag, off by
default, tells the club render path to drop the opponent's logo from the
event dict before invoking the shared campaign renderer.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.add_column(
            sa.Column(
                "hide_opponent_logo",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.drop_column("hide_opponent_logo")

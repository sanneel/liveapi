"""campaign hot_mode column

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19 00:00:01

Adds `campaigns.hot_mode`: which override scope this campaign uses
when `campaigns.mode == 'hot'`. Valid values: 'all' | 'prematch' | 'live'.

Default 'all' preserves today's behaviour — campaigns created before this
migration pool both prematch and live matches the same way the legacy
`_run_scoring` did.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(
            sa.Column(
                "hot_mode",
                sa.String(),
                nullable=False,
                server_default="all",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("hot_mode")

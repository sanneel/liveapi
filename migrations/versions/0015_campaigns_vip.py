"""campaigns: vip theme toggle

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-15 00:00:00

Adds a per-campaign `vip` boolean. When set, the public /r/{slug}.png render
uses the "vip" color theme (purple/violet) instead of the original "default"
navy theme. Defaults to False so every existing campaign keeps the old look.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(
            sa.Column(
                "vip",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("vip")

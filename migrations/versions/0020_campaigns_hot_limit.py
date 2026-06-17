"""campaigns.hot_limit — persisted default render count for auto campaigns

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-17 02:00:00

Re-introduces a stored per-campaign limit. For auto campaigns this is the
default number of matches the PNG renders when the URL carries no explicit
`?limit=`, and it drives the Copy-URL helper on the edit page. Manual
campaigns ignore it (they render their selected list).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("hot_limit", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "hot_limit")

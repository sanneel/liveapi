"""team campaign columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-19 00:00:02

Phase 5: team-based campaigns.

Adds to `campaigns`:
  - team_slug          : canonical team identifier (e.g. 'colo-colo'); null
                         except for campaigns with mode='team'.
  - team_limit         : max upcoming matches to surface (default 1).
  - fallback_image_url : optional URL redirected to when no upcoming matches
                         exist. Validated against an allow-list at write time.

Indexes team_slug for the team-page resolver query.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("team_slug", sa.String(), nullable=True))
        batch.add_column(
            sa.Column(
                "team_limit",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(sa.Column("fallback_image_url", sa.String(), nullable=True))
    op.create_index("ix_campaigns_team_slug", "campaigns", ["team_slug"])


def downgrade() -> None:
    op.drop_index("ix_campaigns_team_slug", table_name="campaigns")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("fallback_image_url")
        batch.drop_column("team_limit")
        batch.drop_column("team_slug")

"""simplify campaigns to manual|auto with league filter

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-20 00:00:00

Collapses the campaign surface to exactly two shapes:

  manual  Editor-picked CampaignMatch list (unchanged).
  auto    Top-N hottest matches for a sport, optionally filtered to one
          league (tournament_name). Count comes from `?limit=` at request
          time, no longer stored on the row.

Removes the team-mode campaign columns and the hot-mode tuning knobs:
  - hot_limit
  - hot_mode
  - team_slug
  - team_limit
  - fallback_image_url

Pre-existing data is migrated:
  - mode = 'hot'  -> mode = 'auto'  (league left NULL; admin sets later)
  - mode = 'team' -> mode = 'manual' (manual match list is empty until
    admin re-picks; team_slug data is dropped with the column).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("league", sa.String(), nullable=True))

    op.execute("UPDATE campaigns SET mode = 'auto' WHERE mode = 'hot'")
    op.execute("UPDATE campaigns SET mode = 'manual' WHERE mode = 'team'")

    op.drop_index("ix_campaigns_team_slug", table_name="campaigns")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("fallback_image_url")
        batch.drop_column("team_limit")
        batch.drop_column("team_slug")
        batch.drop_column("hot_mode")
        batch.drop_column("hot_limit")


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("hot_limit", sa.Integer(), nullable=False, server_default="5"))
        batch.add_column(sa.Column("hot_mode", sa.String(), nullable=False, server_default="all"))
        batch.add_column(sa.Column("team_slug", sa.String(), nullable=True))
        batch.add_column(sa.Column("team_limit", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("fallback_image_url", sa.String(), nullable=True))
    op.create_index("ix_campaigns_team_slug", "campaigns", ["team_slug"])

    op.execute("UPDATE campaigns SET mode = 'hot' WHERE mode = 'auto'")

    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("league")

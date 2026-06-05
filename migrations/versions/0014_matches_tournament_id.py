"""matches.tournament_id — jugabet tournament UUID for the priority odds lane

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-05 00:00:00

Adds `matches.tournament_id`, jugabet's tournament UUID (e.g.
c19cb5ffb4404c31b869b53dd90161de). It is already present in the SSR events
JSON the parser now reads; storing it lets the priority odds parser map any
featured match (campaign / hot / World Cup) to its league overlay URL
(/football/all/1?tournaments=<uuid>) for fast, browserless live-odds refresh.

No backfill — the parser populates it as rows re-upsert.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("tournament_id", sa.String(), nullable=True))
    op.create_index("ix_matches_tournament_id", "matches", ["tournament_id"])


def downgrade() -> None:
    op.drop_index("ix_matches_tournament_id", table_name="matches")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("tournament_id")

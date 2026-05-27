"""matches: is_synthetic flag

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-25 11:00:00

Sportsbook feeds carry a lot of synthetic / replay / esports inventory
(Virtual football, FIFA Replays, ESportsBattle, etc.) mixed in with real
fixtures. Without a way to tell them apart, the campaign picker and the
public hot list end up promoting fake matches. Adding a boolean we can
populate at parser-write time using `app.utils.quality` and filter on
in every read path.

Backfill: every existing row is set by re-checking its `tournament_name`
against the keyword classifier so the first request after deploy doesn't
see "all synthetic" or "all real" — values match what a fresh parser
cycle would have set.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.add_column(
            sa.Column(
                "is_synthetic",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.create_index(
            "ix_matches_is_synthetic", ["is_synthetic"]
        )

    # Backfill from existing tournament names. Done inline in SQL so we
    # don't have to import the Python classifier into the migration.
    # Keywords mirror app/utils/quality.py::SYNTHETIC_KEYWORDS — keep in sync.
    keywords = [
        "virtual", "replay", "ereplay", "esportsbattle", "esports-battle",
        "ehighlight", "epenalt", "ebattle", "simulat", "fifa 2", "fc 2",
        "efootball", "vff",
    ]
    conn = op.get_bind()
    for kw in keywords:
        conn.execute(
            sa.text(
                "UPDATE matches SET is_synthetic = 1 "
                "WHERE LOWER(COALESCE(tournament_name, '')) LIKE :pat"
            ),
            {"pat": f"%{kw}%"},
        )


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.drop_index("ix_matches_is_synthetic")
        batch.drop_column("is_synthetic")

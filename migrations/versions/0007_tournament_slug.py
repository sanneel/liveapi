"""tournament slug for resilient league filtering

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20 00:00:01

Adds `matches.tournament_slug` so auto campaigns can filter on a normalized
identifier instead of the raw feed string. Without this, a single casing or
accent change in the upstream feed silently breaks every campaign pinned to
that league.

Backfill: computes the slug for every existing row from `tournament_name`,
using the same `slugify_league` function the parser will use going forward.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.utils.slugify import slugify_league

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("tournament_slug", sa.String(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT event_id, tournament_name FROM matches WHERE tournament_name IS NOT NULL")
    ).fetchall()
    for row in rows:
        slug = slugify_league(row.tournament_name)
        if slug:
            conn.execute(
                sa.text("UPDATE matches SET tournament_slug = :s WHERE event_id = :e"),
                {"s": slug, "e": row.event_id},
            )

    op.create_index("ix_matches_tournament_slug", "matches", ["tournament_slug"])


def downgrade() -> None:
    op.drop_index("ix_matches_tournament_slug", table_name="matches")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("tournament_slug")

"""hot overrides + team slugs

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19 00:00:00

Phase 1 of the campaign/hot-match enhancement work.

Adds:
  - hot_override_config: per (sport, mode) override mode (auto|manual|hybrid)
  - hot_override_match : ordered list of pinned/manual matches per (sport, mode)
  - matches.home_slug, matches.away_slug: canonical team identifiers,
    populated by the parser in Phase 2 (nullable until then).

No application code reads or writes the new structures yet — this migration is
schema-only and fully reversible.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── matches: additive team-slug columns ──────────────────────────
    # Nullable so existing rows remain valid; parser will backfill on
    # next refresh cycle once Phase 2 ships.
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("home_slug", sa.String(), nullable=True))
        batch.add_column(sa.Column("away_slug", sa.String(), nullable=True))
    op.create_index("ix_matches_home_slug", "matches", ["home_slug"])
    op.create_index("ix_matches_away_slug", "matches", ["away_slug"])

    # ── hot_override_config ──────────────────────────────────────────
    # One row per (sport, mode). override_mode defaults to 'auto' so any
    # row that gets inserted is behaviour-equivalent to today's system.
    op.create_table(
        "hot_override_config",
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column(
            "override_mode",
            sa.String(),
            nullable=False,
            server_default="auto",
        ),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("sport", "mode"),
    )

    # ── hot_override_match ───────────────────────────────────────────
    # Ordered list of pinned event_ids per (sport, mode). Position is the
    # render order (0-based). pinned=1 forces inclusion in hybrid mode.
    # FK ondelete=NO ACTION: preserve historical overrides even if the
    # underlying match is ever hard-deleted from `matches`.
    op.create_table(
        "hot_override_match",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["matches.event_id"], ondelete="NO ACTION"
        ),
        sa.UniqueConstraint(
            "sport", "mode", "event_id", name="uq_hot_override_match_smv"
        ),
    )
    op.create_index(
        "ix_hot_override_match_sport_mode_position",
        "hot_override_match",
        ["sport", "mode", "position"],
    )
    op.create_index(
        "ix_hot_override_match_event_id",
        "hot_override_match",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_hot_override_match_event_id", table_name="hot_override_match")
    op.drop_index(
        "ix_hot_override_match_sport_mode_position",
        table_name="hot_override_match",
    )
    op.drop_table("hot_override_match")
    op.drop_table("hot_override_config")

    op.drop_index("ix_matches_away_slug", table_name="matches")
    op.drop_index("ix_matches_home_slug", table_name="matches")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("away_slug")
        batch.drop_column("home_slug")

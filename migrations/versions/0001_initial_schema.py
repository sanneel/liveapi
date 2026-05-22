"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-18 00:00:00

Creates all six tables of the v2 architecture:
  matches, campaigns, campaign_matches, users, admin_logs, campaign_hits
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── matches ──────────────────────────────────────────────────────
    op.create_table(
        "matches",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("home_name", sa.String(), nullable=False),
        sa.Column("away_name", sa.String(), nullable=False),
        sa.Column("home_logo", sa.String(), nullable=True),
        sa.Column("away_logo", sa.String(), nullable=True),
        sa.Column("tournament_name", sa.String(), nullable=True),
        sa.Column("href", sa.String(), nullable=True),
        sa.Column("start_time_utc", sa.DateTime(), nullable=True),
        sa.Column("time_raw", sa.String(), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("market_type", sa.String(), nullable=True),
        sa.Column("market_name", sa.String(), nullable=True),
        sa.Column("odds_json", sa.Text(), nullable=True),
        sa.Column("hot_score", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_matches_sport", "matches", ["sport"])
    op.create_index("ix_matches_mode", "matches", ["mode"])
    op.create_index("ix_matches_status", "matches", ["status"])
    op.create_index("ix_matches_tournament_name", "matches", ["tournament_name"])
    op.create_index("ix_matches_start_time_utc", "matches", ["start_time_utc"])
    op.create_index("ix_matches_hot_score", "matches", ["hot_score"])
    op.create_index("ix_matches_is_active", "matches", ["is_active"])
    op.create_index("ix_matches_sport_status_active", "matches", ["sport", "status", "is_active"])
    op.create_index("ix_matches_active_hot", "matches", ["is_active", "hot_score"])
    op.create_index("ix_matches_sport_active", "matches", ["sport", "is_active"])

    # ── campaigns ────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("slug", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="manual"),
        sa.Column("hot_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_campaigns_sport", "campaigns", ["sport"])
    op.create_index("ix_campaigns_enabled", "campaigns", ["enabled"])
    op.create_index("ix_campaigns_expires_at", "campaigns", ["expires_at"])

    # ── campaign_matches ─────────────────────────────────────────────
    op.create_table(
        "campaign_matches",
        sa.Column("campaign_slug", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("campaign_slug", "event_id"),
        sa.ForeignKeyConstraint(["campaign_slug"], ["campaigns.slug"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["matches.event_id"]),
    )
    op.create_index("ix_campaign_matches_campaign_slug", "campaign_matches", ["campaign_slug"])
    op.create_index("ix_campaign_matches_event_id", "campaign_matches", ["event_id"])

    # ── users ────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("username", sa.String(), primary_key=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("totp_secret", sa.String(), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ── admin_logs ───────────────────────────────────────────────────
    op.create_table(
        "admin_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
    )
    op.create_index("ix_admin_logs_ts", "admin_logs", ["ts"])
    op.create_index("ix_admin_logs_username", "admin_logs", ["username"])
    op.create_index("ix_admin_logs_action", "admin_logs", ["action"])

    # ── campaign_hits ────────────────────────────────────────────────
    op.create_table(
        "campaign_hits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_slug", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("ip_hash", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
    )
    op.create_index("ix_campaign_hits_campaign_slug", "campaign_hits", ["campaign_slug"])
    op.create_index("ix_campaign_hits_ts", "campaign_hits", ["ts"])


def downgrade() -> None:
    op.drop_table("campaign_hits")
    op.drop_table("admin_logs")
    op.drop_table("users")
    op.drop_table("campaign_matches")
    op.drop_table("campaigns")
    op.drop_table("matches")

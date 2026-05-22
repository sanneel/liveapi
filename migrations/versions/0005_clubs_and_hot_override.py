"""clubs and hot_override (Phase A — additive)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19 00:00:03

Introduces the new HOT engine + CLUB system without removing the legacy
campaigns surface (deprecation happens in Phase C).

New tables:
  clubs        Immutable team-entity rows, parser-driven (slug PK).
  hot_override Per-event boost/pin overrides for the new HOT engine.

Naming note: this table is named `hot_override` (per spec). Phase 3 left
`hot_override_config` + `hot_override_match` — those remain in place for
the 90-day deprecation window; both schemas coexist.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── clubs ────────────────────────────────────────────────────────
    op.create_table(
        "clubs",
        sa.Column("slug", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("logo", sa.String(), nullable=True),
        sa.Column("fallback_text", sa.String(), nullable=True),
        sa.Column("cta_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # No secondary indexes — slug is PK and the only lookup key.

    # ── hot_override ─────────────────────────────────────────────────
    # event_id is PK + FK; one override per match.
    op.create_table(
        "hot_override",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("boost", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "pin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["matches.event_id"], ondelete="NO ACTION"
        ),
    )
    op.create_index("ix_hot_override_pin", "hot_override", ["pin"])


def downgrade() -> None:
    op.drop_index("ix_hot_override_pin", table_name="hot_override")
    op.drop_table("hot_override")
    op.drop_table("clubs")

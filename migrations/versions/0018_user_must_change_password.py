"""users.must_change_password — force one-time-password rotation

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-17 00:00:00

Adds a flag so an operator can hand out a one-time password and the user is
forced to set a new one on first login before reaching any other admin page.
Existing users default to 0 (no forced change) so current sessions are
unaffected.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")

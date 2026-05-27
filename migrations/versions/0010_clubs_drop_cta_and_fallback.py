"""clubs: drop cta_url and fallback_text

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-24 00:00:00

Clubs are pure PNG renderers per the current spec: no CTA button, no
fallback text overlay. The renderer never read either column. Dropping
them removes the only stored field that contradicted the "no CTA" rule
(cta_url had a hardcoded default URL) and trims the admin form.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table is required for SQLite, which can't drop a column
    # in place on older versions; alembic recreates the table cleanly.
    with op.batch_alter_table("clubs") as batch:
        batch.drop_column("cta_url")
        batch.drop_column("fallback_text")


def downgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.add_column(sa.Column("fallback_text", sa.String(), nullable=True))
        batch.add_column(sa.Column("cta_url", sa.String(), nullable=True))

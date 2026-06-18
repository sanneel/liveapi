"""tutorials — help-center video library

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-17 01:00:00

A small library of tutorial videos uploaded by an admin and shown by title in
the Help modal. The video file lives on disk under app/static/tutorials/;
only metadata is stored here.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tutorials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tutorials_created_at", "tutorials", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_tutorials_created_at", table_name="tutorials")
    op.drop_table("tutorials")

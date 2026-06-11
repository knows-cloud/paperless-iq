"""Content-drift tracking — document_tracking.last_embedded_at.

A persistent per-document "vector last refreshed at" timestamp, stamped on every
successful embed. Drives the weekly content-drift reindex and embed-freshness
visibility (the embed audit events).

Revision ID: 003
Revises: 002
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_tracking",
        sa.Column("last_embedded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_tracking", "last_embedded_at")

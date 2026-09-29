"""Tag-drift tracking — document_tracking.last_tag_ids_json.

A persistent snapshot of the tag IDs a document carried at its last successful
embed. Drives the tag-drift reindex: tag removals (including bulk-edit
``remove_tag``/``modify_tags`` and whole-tag deletions) neither fire the
Paperless NGX ``document_updated`` webhook trigger nor bump the document's
``modified`` timestamp, so the existing content-drift reindex (D-22 note)
never notices them. Comparing the document's *current* tag IDs against this
snapshot catches that gap independently of both signals.

Revision ID: 004
Revises: 003
Create Date: 2026-09-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_tracking",
        sa.Column("last_tag_ids_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_tracking", "last_tag_ids_json")

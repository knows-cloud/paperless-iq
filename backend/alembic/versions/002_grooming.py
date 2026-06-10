"""Grooming feature — Steps 0 and 1.

Step 0: deferred re-embedding
  - document_tracking.reembed_dirty_since

Step 1: grooming ORM + permissions
  - suggestions.evidence_json
  - user_permissions.can_groom
  - NEW TABLE entity_descriptions
  - NEW TABLE grooming_dismissals

Revision ID: 002
Revises: 001
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 0 ── deferred re-embedding
    op.add_column(
        "document_tracking",
        sa.Column("reembed_dirty_since", sa.DateTime(timezone=True), nullable=True),
    )

    # Step 1 ── grooming evidence on suggestions
    op.add_column(
        "suggestions",
        sa.Column("evidence_json", sa.Text(), nullable=True),
    )

    # Step 1 ── grooming permission
    op.add_column(
        "user_permissions",
        sa.Column("can_groom", sa.Boolean(), nullable=False, server_default="0"),
    )

    # Step 1 ── entity descriptions + embeddings
    op.create_table(
        "entity_descriptions",
        sa.Column("entity_type", sa.String(50), primary_key=True),
        sa.Column("entity_id", sa.Integer(), primary_key=True),
        sa.Column("name_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_source", sa.String(20), nullable=False, server_default="user"),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("embedding_stored", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("embed_model", sa.String(200), nullable=True),
        sa.Column("embed_dim", sa.Integer(), nullable=True),
        sa.Column("description_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Step 1 ── grooming dismissals (user rejections, permanent by default)
    op.create_table(
        "grooming_dismissals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_id", sa.Integer(), nullable=False, index=True),
        sa.Column("document_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("other_entity_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("grooming_dismissals")
    op.drop_table("entity_descriptions")
    op.drop_column("user_permissions", "can_groom")
    op.drop_column("suggestions", "evidence_json")
    op.drop_column("document_tracking", "reembed_dirty_since")

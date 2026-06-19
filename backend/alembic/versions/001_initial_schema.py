"""Initial schema — all tables present before the Alembic migration system was introduced.

Revision ID: 001
Revises: (none)
Create Date: 2026-06-10

New databases run this migration to create the full baseline schema.
Pre-existing databases are stamped to this revision automatically at startup
(because they already have these tables) before upgrading to head.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("correspondent", sa.Text(), nullable=True),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=False),
        sa.Column("llm_provider", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("analysis_mode", sa.String(20), nullable=False),
        sa.Column("prompt_used", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_llm_response", sa.Text(), nullable=False, server_default=""),
        sa.Column("extracted_content", sa.Text(), nullable=True),
        sa.Column("original_ocr_content", sa.Text(), nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False, index=True),
        sa.Column("document_title", sa.Text(), nullable=True),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("previous_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("change_source", sa.String(200), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False, server_default="field_change"),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suggestion_id", sa.String(36), nullable=True),
    )

    op.create_table(
        "document_tracking",
        sa.Column("document_id", sa.Integer(), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_stored", sa.Boolean(), nullable=False, server_default="0"),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
    )

    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_session_id", sa.String(36), nullable=True),
        sa.Column("embedding_stored", sa.Boolean(), nullable=False, server_default="0"),
    )

    op.create_table(
        "user_permissions",
        sa.Column("username", sa.String(150), primary_key=True),
        sa.Column("ng_admin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_access", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_view_queue", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_approve", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_analyze", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_discover", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_settings", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_permissions")
    op.drop_table("user_memories")
    op.drop_table("conversation_sessions")
    op.drop_table("settings")
    op.drop_table("document_tracking")
    op.drop_table("audit_log")
    op.drop_table("suggestions")

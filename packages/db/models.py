import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    auth_provider_subject: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str]
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')", name="ck_workspace_members_role"
        )
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str]
    content_hash_current: Mapped[str]
    status: Mapped[str]
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", use_alter=True, name="fk_documents_current_version"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        Index("ix_document_versions_document_id_version_number", "document_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_number: Mapped[int]
    content_hash: Mapped[str]
    object_storage_key: Mapped[str]
    page_count: Mapped[int]
    is_current: Mapped[bool] = mapped_column(default=False)
    superseded_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ingestion_jobs_status", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str]
    failure_stage: Mapped[str | None] = mapped_column(nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str]
    is_shared: Mapped[bool] = mapped_column(default=False)
    share_token: Mapped[str | None] = mapped_column(nullable=True, unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role")
    )
    content: Mapped[str]
    sources_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    used_images_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_name: Mapped[str | None] = mapped_column(nullable=True)
    usage_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rating: Mapped[str] = mapped_column(
        CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating")
    )
    comment: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    key_hash: Mapped[str] = mapped_column(unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class DocumentTable(Base):
    """One row per table extracted from a document version (specs/051-table-intelligence).
    document_id is a direct FK (not the ephemeral IngestionJob's document_version_id alone)
    so the RLS policy (migration 0003) is a one-hop join to documents, matching
    document_versions/ingestion_jobs's existing shape rather than a two-hop join."""

    __tablename__ = "document_tables"
    __table_args__ = (
        Index("ix_document_tables_document_id", "document_id"),
        Index("ix_document_tables_document_version_id", "document_version_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    table_index: Mapped[int]
    page_number: Mapped[int]
    object_storage_key: Mapped[str]  # raw CSV, mirrors document_versions/image storage keys
    summary: Mapped[str | None] = mapped_column(nullable=True)  # LLM summary; primary embedded text
    schema_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{"name","type"}, ...]
    row_count: Mapped[int]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class TableCell(Base):
    """Normalized table rows, keyed (document_id, table_id, row_index, column_name) per
    specs/architecture/05-multimodal-strategy.md §2. document_id is denormalized from
    document_tables for the same one-hop-RLS-join reason noted there — not queried by
    anything yet (specs/051-table-intelligence's explicit non-goal); stored for a future
    text-to-SQL-style tool."""

    __tablename__ = "table_cells"
    __table_args__ = (
        UniqueConstraint(
            "table_id", "row_index", "column_name", name="uq_table_cells_table_row_column"
        ),
        Index("ix_table_cells_document_id", "document_id"),
        Index("ix_table_cells_table_id", "table_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_tables.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    row_index: Mapped[int]
    column_name: Mapped[str]
    value: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Nullable: a few audited actions (e.g. workspace creation itself) aren't scoped to an
    # already-existing workspace row.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str]
    resource_type: Mapped[str]
    resource_id: Mapped[uuid.UUID]
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

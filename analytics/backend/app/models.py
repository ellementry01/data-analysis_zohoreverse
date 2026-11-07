"""Application metadata (kept in the ellementry_meta schema, separate from analytical data)."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    schema_name: Mapped[str] = mapped_column(String(63), unique=True)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    members: Mapped[list["WorkspaceMember"]] = relationship(cascade="all, delete-orphan", back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_email: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # admin | editor | viewer
    workspace: Mapped[Workspace] = relationship(back_populates="members")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63))  # view name inside the workspace schema
    kind: Mapped[str] = mapped_column(String(20))  # file | connector | query_table
    description: Mapped[str] = mapped_column(Text, default="")
    source_info: Mapped[dict] = mapped_column(JSON, default=dict)
    query_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    default_date_column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    columns: Mapped[list["DatasetColumn"]] = relationship(
        cascade="all, delete-orphan", order_by="DatasetColumn.position", back_populates="dataset"
    )
    transforms: Mapped[list["Transform"]] = relationship(
        cascade="all, delete-orphan", order_by="Transform.position", back_populates="dataset"
    )


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (UniqueConstraint("dataset_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(63))  # physical column name
    display_name: Mapped[str] = mapped_column(String(200))
    data_type: Mapped[str] = mapped_column(String(20))  # text | integer | decimal | date | datetime | boolean
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    source_name: Mapped[str | None] = mapped_column(String(300), nullable=True)  # original header
    dataset: Mapped[Dataset] = relationship(back_populates="columns")


class Transform(Base):
    """Recorded data-prep step. Replayed in order whenever the dataset is refreshed or replaced."""

    __tablename__ = "transforms"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_result: Mapped[str] = mapped_column(Text, default="")
    dataset: Mapped[Dataset] = relationship(back_populates="transforms")


class Relationship(Base):
    __tablename__ = "relationships"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    from_dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    from_column: Mapped[str] = mapped_column(String(63))
    to_dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    to_column: Mapped[str] = mapped_column(String(63))
    # many_to_one: "from" is the fact/child side, "to" is the lookup/parent side
    cardinality: Mapped[str] = mapped_column(String(20), default="many_to_one")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))  # postgresql | sqlalchemy
    # Never stores a plaintext password: config holds host/db/user and optionally password_env.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(Text, default="")


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(63))  # identifier, e.g. net_sales
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="simple")  # simple | composite
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True)
    expression: Mapped[str] = mapped_column(Text, default="")  # aggregate SQL for simple, {metric} formula for composite
    filters: Mapped[list] = mapped_column(JSON, default=list)  # business rules: [{column, op, value}]
    time_column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    semi_additive: Mapped[bool] = mapped_column(Boolean, default=False)  # e.g. stock on hand -> latest snapshot
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    format: Mapped[str] = mapped_column(String(20), default="number")  # number | currency | percent
    higher_is_better: Mapped[bool] = mapped_column(Boolean, default=True)


class GlossaryTerm(Base):
    """Business vocabulary: maps words to columns, values or metrics."""

    __tablename__ = "glossary_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    term: Mapped[str] = mapped_column(String(200))
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    target_type: Mapped[str] = mapped_column(String(20))  # column | value | metric
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True)
    column: Mapped[str | None] = mapped_column(String(63), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")


class BusinessRule(Base):
    """Row-level rule applied to every semantic (chart / AI) query on a dataset."""

    __tablename__ = "business_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[list] = mapped_column(JSON, default=list)  # [{column, op, value}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    chart_type: Mapped[str] = mapped_column(String(30))
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Dashboard(Base):
    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_dashboards_workspace_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    # Stable identity: survives renames and rebuilds (ids change when a dashboard is recreated), so assistant
    # threads and memories are keyed by it, never by id.
    key: Mapped[str] = mapped_column(String(80))
    domain: Mapped[str] = mapped_column(String(30), default="")  # sales | stock | operations | executive | data | ...
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[list] = mapped_column(JSON, default=list)  # global filter definitions
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    widgets: Mapped[list["DashboardWidget"]] = relationship(cascade="all, delete-orphan", order_by="DashboardWidget.id")


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    chart_type: Mapped[str] = mapped_column(String(30))
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)  # {x, y, w, h}
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"), nullable=True)


class SavedQuery(Base):
    __tablename__ = "saved_queries"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sql: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QueryLog(Base):
    __tablename__ = "query_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_email: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20))  # chart | sql | ai | dashboard
    sql: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    user_email: Mapped[str] = mapped_column(String(200))
    # Where the thread lives: the Ask page (workspace), one dashboard's chat (dashboard + dashboard_key), or the
    # global assistant (global).
    scope_type: Mapped[str] = mapped_column(String(20), default="workspace")
    dashboard_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")  # compacted older turns
    summary_upto_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_scanned_upto_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Phase 4 extraction
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    messages: Mapped[list["Message"]] = relationship(cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    screen_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # filters / drill state the user was looking at
    tool_trace: Mapped[list | None] = mapped_column(JSON, nullable=True)  # agent steps behind an answer
    model: Mapped[str] = mapped_column(String(60), default="")
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)  # up | down
    feedback_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIUsage(Base):
    """One row per Claude call: who, what for, which model, tokens and estimated cost (spend caps read this)."""
    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    user_email: Mapped[str] = mapped_column(String(200), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(20))  # chat | explain | memory | briefing | eval
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_inr: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class RefreshSchedule(Base):
    __tablename__ = "refresh_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), unique=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(Text, default="")


# ----------------------------------------------------------------------------------------------- identity and access
# Phase 3 of docs/AI_ASSISTANTS_PLAN.md: real sign-in (Google Workspace), sessions, API tokens, access rules, audit.

class User(Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(200), primary_key=True)  # lower case
    name: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # inactive users lose access at once
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # manages users, tokens, the audit log
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 is stored."""
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class LoginState(Base):
    """One pending sign-in: OIDC state, nonce and PKCE verifier, valid for a few minutes."""
    __tablename__ = "login_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(500), default="/")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApiToken(Base):
    """For scripts (dashboard builds, evals): sent as 'Authorization: Bearer <token>', acting as its user."""
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AccessRule(Base):
    """Who may see a dashboard, a domain of dashboards, or a dataset. A target with no rules is visible to every member
    of the workspace; once it has rules, only members they match (and workspace admins) see it."""
    __tablename__ = "access_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "target_type", "target", "principal_type", "principal",
                                       name="uq_access_rules"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(20))   # dashboard | domain | dataset
    target: Mapped[str] = mapped_column(String(200))       # dashboard key, domain name, or dataset slug
    principal_type: Mapped[str] = mapped_column(String(20))  # role | user
    principal: Mapped[str] = mapped_column(String(200))    # minimum role (viewer|editor|admin), or a user's email
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_email: Mapped[str] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)  # sign_in, sign_in_failed, sign_out, assistant_ask, ...
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target: Mapped[str] = mapped_column(String(300), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")


class Memory(Base):
    """What an assistant remembers (Phase 4). Three layers:
      * personal: one person's preferences and facts; only they see it (owner_email);
      * shared:   a business fact for everyone in the workspace, approved by a workspace admin;
      * decision: a decision with its reason and date; private to its owner unless they mark it shared.
    Learned memories are proposals until the person accepts them; an explicit "remember ..." is saved at once."""
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    layer: Mapped[str] = mapped_column(String(20))          # personal | shared | decision
    kind: Mapped[str] = mapped_column(String(20))           # preference | fact | decision | caveat | open_question
    scope: Mapped[str] = mapped_column(String(120), default="global")  # global | dashboard:<key> | domain:<name>
    owner_email: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)  # who it belongs to
    visibility: Mapped[str] = mapped_column(String(10), default="private")  # decisions: private | shared
    text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    # proposed | active | rejected | retired | needs_review
    review_reason: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # explicit | inferred | manual
    share_status: Mapped[str] = mapped_column(String(20), default="none")  # none | pending | approved | rejected
    source_conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text, default="")   # the words it came from (kept if the chat is deleted)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)  # [{type: metric|issue, name, fingerprint}]
    supersedes_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class UserProfile(Base):
    """A short "how this person works" note per user and workspace, rewritten from their memories; they can edit it."""
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("workspace_id", "user_email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_email: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)   # memory ids it was written from
    version: Mapped[int] = mapped_column(Integer, default=0)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    approvals_since: Mapped[int] = mapped_column(Integer, default=0)  # memories approved since the last rewrite
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    """Background work kept in the database (memory extraction, profile rewrites, conversation summaries): it survives
    restarts, is retried with back-off, and several workers can share the queue (rows are claimed with SKIP LOCKED)."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

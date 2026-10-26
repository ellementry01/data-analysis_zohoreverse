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
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RefreshSchedule(Base):
    __tablename__ = "refresh_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), unique=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(Text, default="")

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import (
    AIStatus,
    AttributeSource,
    CaseStatus,
    FlagStatus,
    MatchStatus,
    ReportStatus,
    ReportType,
    Role,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemReport(TimestampMixin, Base):
    __tablename__ = "item_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(50))
    brand: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    distinctive_features: Mapped[str | None] = mapped_column(Text)
    # Never shown to other users; used only to build/evaluate ownership verification.
    private_details: Mapped[str | None] = mapped_column(Text)
    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    location: Mapped[str] = mapped_column(String(200))  # human-readable label (location_text)
    # Precise point: used internally for geofence validation and matching, never shown to other users.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Structured location (NULL for reports created before the UET geofence existed)
    zone: Mapped[str | None] = mapped_column(String(20))  # campus / nearby
    location_type: Mapped[str | None] = mapped_column(String(20))  # predefined / gps / map
    place_key: Mapped[str | None] = mapped_column(String(50))  # key of a predefined place
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), default=ReportStatus.ACTIVE, index=True)
    ai_status: Mapped[AIStatus] = mapped_column(Enum(AIStatus), default=AIStatus.PENDING)
    ai_error: Mapped[str | None] = mapped_column(String(255))
    text_embedding: Mapped[list | None] = mapped_column(JSON)

    owner: Mapped[User] = relationship()
    images: Mapped[list["ItemImage"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    attributes: Mapped[list["ItemAttribute"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class ItemImage(Base):
    __tablename__ = "item_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("item_reports.id", ondelete="CASCADE"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    meta: Mapped[dict | None] = mapped_column(JSON)  # width/height
    embedding: Mapped[dict | None] = mapped_column(JSON)  # visual features (hash, histogram)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[ItemReport] = relationship(back_populates="images")


class ItemAttribute(Base):
    __tablename__ = "item_attributes"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("item_reports.id", ondelete="CASCADE"), index=True)
    attribute_name: Mapped[str] = mapped_column(String(50))
    attribute_value: Mapped[str] = mapped_column(String(200))
    source: Mapped[AttributeSource] = mapped_column(Enum(AttributeSource))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[ItemReport] = relationship(back_populates="attributes")


class MatchCandidate(TimestampMixin, Base):
    __tablename__ = "match_candidates"
    __table_args__ = (UniqueConstraint("lost_report_id", "found_report_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lost_report_id: Mapped[int] = mapped_column(ForeignKey("item_reports.id", ondelete="CASCADE"), index=True)
    found_report_id: Mapped[int] = mapped_column(ForeignKey("item_reports.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    signals: Mapped[dict] = mapped_column(JSON)  # per-signal scores
    explanation: Mapped[list] = mapped_column(JSON)  # list of reason strings
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.POTENTIAL_MATCH)

    lost_report: Mapped[ItemReport] = relationship(foreign_keys=[lost_report_id])
    found_report: Mapped[ItemReport] = relationship(foreign_keys=[found_report_id])


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_candidates.id", ondelete="CASCADE"), index=True)
    questions: Mapped[list] = mapped_column(JSON)  # [{"id", "question", "evidence_type"}]
    answers: Mapped[dict | None] = mapped_column(JSON)  # {question_id: answer}
    advisory_score: Mapped[float | None] = mapped_column(Float)
    advisory_notes: Mapped[list | None] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/SUBMITTED/ACCEPTED/REJECTED
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Case(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_candidates.id", ondelete="CASCADE"), unique=True)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.CONNECTED)

    match: Mapped[MatchCandidate] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(20))  # report / user
    entity_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[FlagStatus] = mapped_column(Enum(FlagStatus), default=FlagStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(180), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AnswerVersion(Base):
    __tablename__ = "answer_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(20), default="assistant")
    __table_args__ = (UniqueConstraint("conversation_id", "version_number"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    answer_version_id: Mapped[str | None] = mapped_column(ForeignKey("answer_versions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Passage(Base):
    __tablename__ = "passages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    source_passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="RESTRICT"))
    source_answer_version_id: Mapped[str] = mapped_column(ForeignKey("answer_versions.id", ondelete="RESTRICT"))
    parent_branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(24))
    user_instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="ready_for_review")
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    reviewer_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BranchMessage(Base):
    __tablename__ = "branch_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BranchSelection(Base):
    __tablename__ = "branch_selections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    source_passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="RESTRICT"))
    source_passage_ids: Mapped[str] = mapped_column(Text)
    selected_text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("branch_id", "ordinal"),)


class MessageContextSource(Base):
    __tablename__ = "message_context_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    source_branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    source_branch_message_ids: Mapped[str] = mapped_column(Text)
    source_status: Mapped[str] = mapped_column(String(24))
    source_accepted: Mapped[bool | None] = mapped_column(nullable=True)
    __table_args__ = (UniqueConstraint("target_message_id", "source_branch_id"),)


class AnswerVersionSource(Base):
    __tablename__ = "answer_version_sources"
    answer_version_id: Mapped[str] = mapped_column(ForeignKey("answer_versions.id", ondelete="CASCADE"), primary_key=True)
    source_branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id", ondelete="RESTRICT"), primary_key=True)
    source_passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="RESTRICT"), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(String(24), default="merged_from")


class MergeDraft(Base):
    __tablename__ = "merge_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    base_answer_version_id: Mapped[str] = mapped_column(ForeignKey("answer_versions.id", ondelete="RESTRICT"))
    branch_ids: Mapped[str] = mapped_column(Text)
    proposed_content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

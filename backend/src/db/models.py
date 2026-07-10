from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, func, Boolean, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feishu_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    questions: Mapped[list["Question"]] = relationship(back_populates="user")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False, server_default="normal")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    clarified_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords_draft_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    research_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # created/awaiting_clarify/awaiting_keyword/running/done/failed/cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="created")
    # Soft-delete flag: a `done` question is hidden from the chat list (so its
    # report stays viewable) instead of being hard-deleted.
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="questions")
    task: Mapped["ResearchTask | None"] = relationship(back_populates="question", uselist=False)


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="step3_local_search")
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    keywords_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_counters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_trace: Mapped[str | None] = mapped_column(Text, nullable=True)

    question: Mapped["Question"] = relationship(back_populates="task")
    gate_results: Mapped[list["GateResult"]] = relationship(back_populates="task")
    report: Mapped["Report | None"] = relationship(back_populates="task", uselist=False)
    pending_docs: Mapped[list["PendingDocument"]] = relationship(back_populates="task")


class GateResult(Base):
    __tablename__ = "gate_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("research_tasks.id"), nullable=False)
    gate_name: Mapped[str] = mapped_column(String(32), nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["ResearchTask"] = relationship(back_populates="gate_results")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("research_tasks.id"), nullable=False)
    vault_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    research_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    me_data_stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    qc_warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    eval_scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["ResearchTask"] = relationship(back_populates="report")


class ReportChatMessage(Base):
    __tablename__ = "report_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingDocument(Base):
    __tablename__ = "pending_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("research_tasks.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # ieee | patent | web
    title: Mapped[str] = mapped_column(Text, nullable=False)
    staging_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    # pending/approved/rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["ResearchTask"] = relationship(back_populates="pending_docs")
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])


class MRAMEQueryLog(Base):
    __tablename__ = "mra_me_query_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("research_tasks.id"), nullable=True)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

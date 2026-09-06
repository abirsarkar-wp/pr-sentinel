from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    BigInteger,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database import Base


EMBEDDING_DIM = 1024


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(255))
    access_token_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    repos: Mapped[list["Repo"]] = relationship(
        back_populates="user",
    )


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    github_repo_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(
        String(500),
        index=True,
    )
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped["User | None"] = relationship(
        back_populates="repos",
    )
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repo",
    )
    code_chunks: Mapped[list["CodeChunk"]] = relationship(
        back_populates="repo",
    )


class CodeChunk(Base):
    __tablename__ = "code_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repos.id"),
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1000))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM),
        nullable=True,
    )

    repo: Mapped["Repo"] = relationship(
        back_populates="code_chunks",
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repos.id"),
        index=True,
    )
    github_pr_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1000))
    author: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(50),
        default="open",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    repo: Mapped["Repo"] = relationship(
        back_populates="pull_requests",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pull_request",
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    pr_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    tokens_used: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    turns_taken: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="reviews",
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="review",
    )
    traces: Mapped[list["AgentTrace"]] = relationship(
        back_populates="review",
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id"),
        index=True,
    )
    file: Mapped[str] = mapped_column(String(1000))
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(
        String(50)
    )
    severity: Mapped[str] = mapped_column(
        String(20)
    )
    explanation: Mapped[str] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=0.5,
    )

    review: Mapped["Review"] = relationship(
        back_populates="findings",
    )


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id"),
        index=True,
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(50))
    content_json: Mapped[dict] = mapped_column(JSON)
    tool_calls_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    review: Mapped["Review"] = relationship(
        back_populates="traces",
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    dataset_name: Mapped[str] = mapped_column(
        String(255)
    )
    precision: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    recall: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    false_positive_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class EvalLabel(Base):
    __tablename__ = "eval_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    pr_reference: Mapped[str] = mapped_column(
        String(500)
    )
    ground_truth_findings_json: Mapped[dict] = mapped_column(
        JSON
    )
    source: Mapped[str] = mapped_column(
        String(255)
    )
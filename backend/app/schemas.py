from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    file: str
    line_start: int
    line_end: int
    category: Literal[
        "bug",
        "security",
        "performance",
        "style",
        "test_coverage",
    ]
    severity: Literal[
        "low",
        "medium",
        "high",
        "critical",
    ]
    explanation: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0, le=1)


class FindingsSubmission(BaseModel):
    findings: list[Finding]
    summary: str
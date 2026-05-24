from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PullRequestRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str
    repo: str
    number: int
    api_base_url: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class PullRequestFileMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str | None = None
    status: str | None = None
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch_available: bool
    blob_url: str | None = None
    raw_url: str | None = None
    previous_filename: str | None = None


class PullRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pr_url: str
    repository: str
    owner: str
    repo: str
    pull_number: int
    title: str | None = None
    author: str | None = None
    state: str | None = None
    draft: bool
    html_url: str | None = None
    api_url: str | None = None
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    merge_commit_sha: str | None = None
    commits: int | None = None
    files_changed: int
    changed_files: int
    additions: int
    deletions: int
    files_without_patch: int
    files: list[PullRequestFileMetadata]
    fetched_at: datetime


class PullRequestDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    diff: str
    metadata: PullRequestMetadata


FindingSeverity = Literal["critical", "high", "medium", "low", "info"]
FindingCategory = Literal[
    "bug",
    "security",
    "performance",
    "maintainability",
    "testing",
    "style",
    "documentation",
    "other",
]
FindingConfidence = Literal["high", "medium", "low"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: FindingSeverity = Field(
        description="Impact level of the finding. Use critical only for urgent production or security risk."
    )
    category: FindingCategory = Field(
        description="Primary review category for the finding."
    )
    line_ref: str = Field(
        description="Precise changed-code reference, preferably file path plus new-line number or hunk range."
    )
    message: str = Field(
        description="Clear explanation of the issue and why it matters."
    )
    suggestion: str = Field(description="Concrete, actionable fix or mitigation.")
    confidence: FindingConfidence = Field(
        description="Reviewer confidence based only on evidence in the diff."
    )


class ReviewAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Finding] = Field(
        description="Code review findings supported by the diff. Return an empty list when there are no actionable issues."
    )

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """Structured problem record for extraction or validation failures."""

    issue_code: str
    severity: str = "warning"
    field: str | None = None
    cad_value: Any = None
    pdf_value: Any = None
    message: str
    need_manual_review: bool = False


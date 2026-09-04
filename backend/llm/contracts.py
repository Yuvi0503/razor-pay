from pydantic import BaseModel, ConfigDict, Field

from backend.domain.enums import ActionType, FailureCategory, ReasonCode


class LLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionType
    delay_minutes: int = Field(default=0, ge=0, le=10080)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=4)
    rationale: str = Field(default="", max_length=400)


class LLMClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FailureCategory
    confidence: float = Field(default=0.0, ge=0, le=1)
    rationale: str = Field(default="", max_length=400)


__all__ = ["LLMClassification", "LLMDecision"]

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ShortText = Annotated[str, Field(min_length=1, max_length=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationCreate(StrictModel):
    title: str = Field(default="新的相处", min_length=1, max_length=80)


class ChatRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    content: str = Field(min_length=1, max_length=5000)


class SettingsUpdate(StrictModel):
    memory_enabled: bool | None = None
    auto_memory: bool | None = None
    personality: str | None = Field(default=None, min_length=1, max_length=800)


class MemoryCreate(StrictModel):
    outline: str = Field(min_length=1, max_length=240)
    detail: str = Field(default="", max_length=3000)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1, ge=0, le=1)
    reason: str = Field(default="用户主动记录", max_length=300)
    tags: list[ShortText] = Field(default_factory=list, max_length=8)
    occurred_on: str | None = Field(default=None, max_length=30)
    missing_details: list[ShortText] = Field(default_factory=list, max_length=8)
    pinned: bool = False


class ExtractedMemory(MemoryCreate):
    source_ids: list[str] = Field(min_length=1, max_length=8)


class FeedbackRequest(StrictModel):
    direction: Literal["more", "less"]
    reason: str = Field(default="", max_length=300)


class ExtractedFeedback(FeedbackRequest):
    memory_id: str
    source_id: str


class Extraction(StrictModel):
    memories: list[ExtractedMemory] = Field(default_factory=list, max_length=6)
    feedback: list[ExtractedFeedback] = Field(default_factory=list, max_length=4)


class PinRequest(StrictModel):
    pinned: bool

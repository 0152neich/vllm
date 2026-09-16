"""Schema Chat Completions dạng text-only cho MVP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatMessage(BaseModel):
    """Message text tương thích ba role không-tool."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    """Allowlist tham số Chat Completions được Gateway hỗ trợ."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False
    stop: str | list[str] | None = None
    seed: int | None = None
    response_format: dict[str, Any] | None = None
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    n: int = Field(default=1, ge=1, le=1)
    user: str | None = Field(default=None, max_length=256)
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None

    @model_validator(mode="after")
    def reject_tool_calling(self) -> ChatCompletionRequest:
        """Từ chối tool fields để ranh giới trách nhiệm không mập mờ."""

        if self.tools is not None or self.tool_choice is not None:
            from app.core.errors import GatewayError

            raise GatewayError(
                400,
                "LLM Gateway không hỗ trợ tool calling; ứng dụng phải tự điều phối tool.",
                "invalid_request_error",
                "unsupported_parameter",
                param="tools" if self.tools is not None else "tool_choice",
            )
        return self

    def input_character_count(self) -> int:
        """Đếm kích thước text trước khi gọi upstream."""

        return sum(len(message.content) for message in self.messages)

    def upstream_body(self, safety_prompt: str, upstream_model: str) -> dict[str, Any]:
        """Ghép safety prompt và loại các field chỉ dành Gateway."""

        body = self.model_dump(exclude_none=True, exclude={"tools", "tool_choice"})
        body["model"] = upstream_model
        body["messages"] = [
            {"role": "system", "content": safety_prompt},
            *[message.model_dump(exclude_none=True) for message in self.messages],
        ]
        return body

"""Persisted read-only assistant conversations and streamed turns."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.assistant.provider import AssistantProvider, OpenAIResponsesProvider
from radar.assistant.service import (
    AssistantTurnError,
    ConversationNotFoundError,
    conversation_detail,
    create_conversation,
    list_conversations,
    run_assistant_turn,
)

router = APIRouter(prefix="/conversations", tags=["assistant"])


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID
    role: str
    content: str
    status: str
    error_code: str | None
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation: ConversationSummary
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=10_000)


@router.get("", response_model=list[ConversationSummary])
def conversations(services: Services) -> list[ConversationSummary]:
    return [
        ConversationSummary.model_validate(item) for item in list_conversations(services.sessions)
    ]


@router.post("", response_model=ConversationSummary, status_code=201)
def new_conversation(body: CreateConversationRequest, services: Services) -> ConversationSummary:
    value = create_conversation(services.sessions, services.clock, title=body.title)
    return ConversationSummary(
        conversation_id=value.id,
        title=value.title,
        created_at=value.created_at,
        updated_at=value.updated_at,
        message_count=0,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: UUID, services: Services) -> ConversationResponse:
    try:
        conversation, messages = conversation_detail(services.sessions, conversation_id)
    except ConversationNotFoundError as error:
        raise ApiError(404, "conversation_not_found", "The conversation does not exist.") from error
    return ConversationResponse(
        conversation=ConversationSummary(
            conversation_id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=len(messages),
        ),
        messages=[
            MessageResponse(
                message_id=message.id,
                role=message.role,
                content=message.content,
                status=message.status,
                error_code=message.error_code,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    body: SendMessageRequest,
    request: Request,
    services: Services,
) -> StreamingResponse:
    if services.config is None:
        raise ApiError(503, "config_unavailable", "An active valid configuration is required.")
    config = services.config
    provider: AssistantProvider | None = getattr(request.app.state, "assistant_provider", None)
    if provider is None:
        if not services.environment.openai_api_key:
            raise ApiError(503, "assistant_unavailable", "OpenAI credentials are not configured.")
        provider = OpenAIResponsesProvider(
            api_key=services.environment.openai_api_key,
            model=config.llm.model,
        )
    try:
        conversation_detail(services.sessions, conversation_id)
    except ConversationNotFoundError as error:
        raise ApiError(404, "conversation_not_found", "The conversation does not exist.") from error

    async def events() -> AsyncIterator[str]:
        assert provider is not None
        try:
            async for delta in run_assistant_turn(
                sessions=services.sessions,
                clock=services.clock,
                conversation_id=conversation_id,
                user_text=body.content,
                provider=provider,
                model=config.llm.model,
            ):
                yield f"event: {delta.event}\ndata: {json.dumps(delta.data)}\n\n"
        except AssistantTurnError:
            payload: dict[str, Any] = {
                "code": "assistant_turn_failed",
                "message": "The assistant could not complete this turn.",
            }
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")

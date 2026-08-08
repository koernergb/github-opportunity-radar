"""Conversation persistence, budgets, tool mediation, and streaming orchestration."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from radar.assistant.proposals import (
    ProposalError,
    create_config_proposal,
    create_pipeline_proposal,
)
from radar.assistant.provider import (
    AssistantProvider,
    ProviderCompleted,
    ProviderTextDelta,
    ProviderToolCall,
)
from radar.assistant.tools import (
    TOOL_SCHEMA_VERSION,
    TOOL_SCHEMAS,
    ToolInputError,
    execute_read_tool,
)
from radar.clock import Clock
from radar.db.models import AssistantToolCall, Conversation, ConversationMessage
from radar.db.session import transaction

ASSISTANT_PROMPT_VERSION = "assistant_system_v2"
MAX_MESSAGES = 20
MAX_TOOLS = 4
MAX_OUTPUT_TOKENS = 800
TURN_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class AssistantDelta:
    event: str
    data: dict[str, Any]


class ConversationNotFoundError(LookupError):
    pass


class AssistantTurnError(RuntimeError):
    pass


def create_conversation(
    sessions: sessionmaker[Session], clock: Clock, *, title: str = "New conversation"
) -> Conversation:
    conversation = Conversation(title=title[:255], created_at=clock.now(), updated_at=clock.now())
    with sessions.begin() as session:
        session.add(conversation)
    return conversation


def list_conversations(sessions: sessionmaker[Session]) -> list[dict[str, Any]]:
    with sessions() as session:
        values = list(
            session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))
        )
        return [
            {
                "conversation_id": str(item.id),
                "title": item.title,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "message_count": session.scalar(
                    select(func.count())
                    .select_from(ConversationMessage)
                    .where(ConversationMessage.conversation_id == item.id)
                )
                or 0,
            }
            for item in values
        ]


def conversation_detail(
    sessions: sessionmaker[Session], conversation_id: UUID
) -> tuple[Conversation, list[ConversationMessage]]:
    with sessions() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))
        messages = list(
            session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at, ConversationMessage.id)
            )
        )
        session.expunge(conversation)
        for message in messages:
            session.expunge(message)
        return conversation, messages


async def run_assistant_turn(
    *,
    sessions: sessionmaker[Session],
    clock: Clock,
    conversation_id: UUID,
    user_text: str,
    provider: AssistantProvider,
    model: str,
) -> AsyncIterator[AssistantDelta]:
    """Stream one bounded turn; tools disappear after untrusted data enters context."""
    if not user_text.strip() or len(user_text) > 10_000:
        raise AssistantTurnError("message must contain 1 to 10000 characters")
    _, history = conversation_detail(sessions, conversation_id)
    with transaction(sessions) as session:
        user_message = ConversationMessage(
            conversation_id=conversation_id,
            role="user",
            content=user_text.strip(),
            status="complete",
            prompt_version=None,
            provider=None,
            model_version=None,
            usage_json={},
            error_code=None,
            created_at=clock.now(),
        )
        session.add(user_message)
        assistant_message = ConversationMessage(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            status="streaming",
            prompt_version=ASSISTANT_PROMPT_VERSION,
            provider="openai",
            model_version=model,
            usage_json={},
            error_code=None,
            created_at=clock.now(),
        )
        session.add(assistant_message)
    messages = _provider_messages(history[-MAX_MESSAGES:], user_text)
    text = ""
    usage: dict[str, Any] = {}
    tool_calls: list[ProviderToolCall] = []
    try:
        async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
            async for event in provider.stream(
                messages=messages,
                tools=TOOL_SCHEMAS,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ):
                if isinstance(event, ProviderTextDelta):
                    text += event.text
                    yield AssistantDelta("text_delta", {"text": event.text})
                elif isinstance(event, ProviderToolCall):
                    tool_calls.append(event)
                elif isinstance(event, ProviderCompleted):
                    usage = event.usage
            if len(tool_calls) > MAX_TOOLS:
                raise AssistantTurnError("assistant tool budget exceeded")
            if tool_calls:
                results = _execute_tools(
                    sessions, clock, conversation_id, assistant_message.id, tool_calls
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "UNTRUSTED_DATA tool results:\n" + json.dumps(results),
                    }
                )
                text = ""
                async for event in provider.stream(
                    messages=messages,
                    tools=[],
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                ):
                    if isinstance(event, ProviderToolCall):
                        raise AssistantTurnError("tool calls are forbidden after tool data")
                    if isinstance(event, ProviderTextDelta):
                        text += event.text
                        yield AssistantDelta("text_delta", {"text": event.text})
                    elif isinstance(event, ProviderCompleted):
                        usage = event.usage
        if not text.strip():
            raise AssistantTurnError("provider returned no grounded answer")
    except TimeoutError as error:
        _fail_message(sessions, assistant_message.id, "assistant_timeout")
        raise AssistantTurnError("assistant turn timed out") from error
    except (json.JSONDecodeError, ProposalError, ToolInputError, ValidationError) as error:
        _fail_message(sessions, assistant_message.id, "assistant_tool_invalid")
        raise AssistantTurnError("assistant emitted an invalid tool call") from error
    except AssistantTurnError:
        _fail_message(sessions, assistant_message.id, "assistant_policy_error")
        raise
    with transaction(sessions) as session:
        stored = session.get(ConversationMessage, assistant_message.id)
        assert stored is not None
        stored.content = text
        stored.status = "complete"
        stored.usage_json = usage
        active = session.get(Conversation, conversation_id)
        assert active is not None
        active.updated_at = clock.now()
        if active.title == "New conversation":
            active.title = user_text.strip()[:80]
    yield AssistantDelta("completed", {"message_id": str(assistant_message.id), "usage": usage})


def _provider_messages(history: list[ConversationMessage], user_text: str) -> list[dict[str, Any]]:
    prompt = (Path(__file__).parent / "prompts" / "system_v2.txt").read_text(encoding="utf-8")
    messages = [{"role": "developer", "content": prompt}]
    messages.extend(
        {"role": item.role, "content": item.content}
        for item in history
        if item.role in {"user", "assistant"} and item.status == "complete"
    )
    messages.append({"role": "user", "content": user_text})
    return messages


def _execute_tools(
    sessions: sessionmaker[Session],
    clock: Clock,
    conversation_id: UUID,
    message_id: UUID,
    calls: list[ProviderToolCall],
) -> list[dict[str, Any]]:
    outputs = []
    for call in calls:
        arguments = json.loads(call.arguments)
        if not isinstance(arguments, dict):
            raise ToolInputError("tool arguments must be an object")
        if call.name == "propose_preference_change":
            proposal = create_config_proposal(
                sessions, clock, conversation_id, "preferences", arguments
            )
            result = {
                "proposal_id": str(proposal.id),
                "status": proposal.status,
                "requires_user_confirmation": True,
            }
        elif call.name == "propose_repository_change":
            proposal = create_config_proposal(
                sessions, clock, conversation_id, "repository", arguments
            )
            result = {
                "proposal_id": str(proposal.id),
                "status": proposal.status,
                "requires_user_confirmation": True,
            }
        elif call.name == "propose_pipeline_run":
            proposal = create_pipeline_proposal(sessions, clock, conversation_id, arguments)
            result = {
                "proposal_id": str(proposal.id),
                "status": proposal.status,
                "requires_separate_scope_budget_confirmation": True,
            }
        else:
            with sessions() as read_session:
                result = execute_read_tool(read_session, call.name, arguments)
        with transaction(sessions) as session:
            session.add(
                AssistantToolCall(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    call_id=call.call_id,
                    tool_name=call.name,
                    arguments_json=arguments,
                    result_json=result,
                    schema_version=TOOL_SCHEMA_VERSION,
                    created_at=clock.now(),
                )
            )
        outputs.append({"call_id": call.call_id, "name": call.name, "result": result})
    return outputs


def _fail_message(sessions: sessionmaker[Session], message_id: UUID, code: str) -> None:
    with transaction(sessions) as session:
        stored = session.get(ConversationMessage, message_id)
        if stored is not None:
            stored.status = "failed"
            stored.error_code = code

"""Bounded provider protocol and OpenAI Responses API streaming adapter."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import AsyncOpenAI, AsyncStream


@dataclass(frozen=True)
class ProviderTextDelta:
    text: str


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ProviderCompleted:
    usage: dict[str, Any]


ProviderEvent = ProviderTextDelta | ProviderToolCall | ProviderCompleted


class AssistantProvider(Protocol):
    def stream(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        max_output_tokens: int,
    ) -> AsyncIterator[ProviderEvent]: ...


class OpenAIResponsesProvider:
    """Translate typed Responses API stream events into provider-neutral events."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def stream(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        max_output_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        stream = cast(
            AsyncStream[Any],
            await self._client.responses.create(
                model=self._model,
                input=cast(Any, list(messages)),
                tools=cast(Any, list(tools)),
                max_output_tokens=max_output_tokens,
                stream=True,
                store=False,
            ),
        )
        async for event in stream:
            event_type = event.type
            if event_type == "response.output_text.delta":
                yield ProviderTextDelta(text=event.delta)
            elif event_type == "response.function_call_arguments.done":
                yield ProviderToolCall(
                    call_id=event.item_id,
                    name=event.name,
                    arguments=event.arguments,
                )
            elif event_type == "response.completed":
                response = event.response
                usage = response.usage.model_dump(mode="json") if response.usage else {}
                yield ProviderCompleted(usage=usage)

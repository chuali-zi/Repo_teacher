from __future__ import annotations

import json
from collections.abc import AsyncIterator

from backend.contracts.domain import ContractModel
from backend.contracts.dto import SseEventDto


def encode_sse_event(event: SseEventDto) -> str:
    payload = event.model_dump(mode="json", exclude_none=True)
    event_name = payload["event_type"]
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def encode_sse_stream(events: AsyncIterator[SseEventDto]) -> AsyncIterator[str]:
    async for event in events:
        if not isinstance(event, ContractModel):
            raise TypeError("SSE events must be Pydantic contract models")
        yield encode_sse_event(event)


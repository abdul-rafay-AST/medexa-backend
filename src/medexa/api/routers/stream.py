from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from medexa.adapters.realtime.in_process_broker import sse_encode_stream
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import require_state

router = APIRouter(prefix="/sessions", tags=["stream"])


@router.get("/{session_id}/live/stream")
async def live_event_stream(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> StreamingResponse:
    require_state(session_id, container)
    return StreamingResponse(
        sse_encode_stream(session_id, container.live_broker),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/{session_id}/live/ws")
async def live_event_websocket(
    websocket: WebSocket,
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> None:
    if container.session_repo.get(session_id) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = container.live_broker.subscribe(session_id)
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        container.live_broker.unsubscribe(session_id, queue)

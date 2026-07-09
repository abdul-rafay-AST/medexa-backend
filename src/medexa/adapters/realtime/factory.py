from __future__ import annotations

from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.adapters.realtime.sse_adapter import SseRealtimeAdapter
from medexa.adapters.realtime.websocket_adapter import WebSocketRealtimeAdapter
from medexa.config import MedexaConfig
from medexa.ports.realtime import RealtimePort


def build_realtime_adapter(settings: MedexaConfig, broker: InProcessBroker) -> RealtimePort:
    if settings.realtime_transport == "websocket":
        return WebSocketRealtimeAdapter(broker)
    return SseRealtimeAdapter(broker)

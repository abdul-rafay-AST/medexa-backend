"""Benchmark Path A chunk processing latency."""

from __future__ import annotations

import statistics
import time
import uuid

from medexa.api.dependencies import ServiceContainer
from medexa.schemas import SessionState
from medexa.utils.time import now_utc


def main() -> None:
    container = ServiceContainer()
    state = SessionState(session_id=str(uuid.uuid4()), patient_name="Bench")
    container.session_repo.save(state)
    text = "therapeutic exercise and gait training for lumbar spine range of motion"
    latencies: list[float] = []

    for i in range(50):
        start = time.perf_counter()
        chunk = container.chunk_ingest.ingest(state, text, start_ts=i * 15.0, end_ts=(i + 1) * 15.0)
        container.path_a_processor.process(state, chunk, now_utc())
        latencies.append((time.perf_counter() - start) * 1000)

    print(f"Path A iterations: {len(latencies)}")
    print(f"p50: {statistics.median(latencies):.1f} ms")
    print(f"p95: {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.1f} ms")
    print(f"max: {max(latencies):.1f} ms")


if __name__ == "__main__":
    main()

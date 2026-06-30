"""CLI demo of the full live pipeline, end-to-end, with NO server and NO AWS.

    python scripts/run_local_session.py

Feeds scripted transcript lines through the real engine and prints the insights
panel after each step, then a final billing summary.
"""
from __future__ import annotations

import datetime
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


import uuid  # noqa: E402

from medexa.api.dependencies import ServiceContainer  # noqa: E402
from medexa.schemas import SessionState, TranscriptChunk  # noqa: E402
from medexa.utils.time import now_utc  # noqa: E402

TRANSCRIPT = [
    "Let's start with some soft tissue work on the left shoulder",
    "Now we'll move into functional activities on the left shoulder",
    "Let's finish with a hot pack",
]


def main() -> None:
    container = ServiceContainer()
    state = SessionState(session_id=str(uuid.uuid4()), status="active")

    current_time = now_utc()

    print("Welcome to the Medexa interactive CLI.")
    print("Type what the therapist says (or 'quit' to exit).")

    seq = 0
    while True:
        try:
            text = input("\n>>> Therapist: ")
        except (EOFError, KeyboardInterrupt):
            break
            
        if text.strip().lower() in ["quit", "exit", "q"]:
            break
            
        if not text.strip():
            continue

        chunk = TranscriptChunk(
            session_id=state.session_id,
            chunk_id=str(uuid.uuid4()),
            text=text,
            start_ts=float(seq),
            end_ts=float(seq + 1),
            sequence=seq,
        )
        seq += 1

        _entities, suggestions = container.transcript_processor.process(state, chunk, current_time)
        
        for s in suggestions:
            print(f"    [suggestion] {s.title}")
            # Auto-apply for the demo: start billing the suggested CPT.
            container.timer_engine.switch_segment(state, s.cpt_code or "", s.body_region, current_time)

        # Ask how much time passes
        time_input = input("    How many minutes passed since last action? (default 15): ")
        try:
            minutes = int(time_input.strip())
        except ValueError:
            minutes = 15
            
        current_time = current_time + datetime.timedelta(minutes=minutes)

        panel = container.insights_builder.build(state, current_time)
        if panel.current_cpt:
            print(f"    current CPT: {panel.current_cpt.code} ({panel.current_cpt.label})")
        for alert in panel.alerts:
            print(f"    [ALERT] {alert.message}")

    summary = container.billing_summary_builder.build(state, current_time)
    print("\n=== Billing Summary ===")
    print(f"Total: {summary.total_units} units / {summary.total_minutes} min")
    for li in summary.line_items:
        kind = "timed" if li.timed else "untimed"
        print(f"  {li.cpt_code} {li.display_name}: {li.units} unit(s) [{kind}]")


if __name__ == "__main__":
    main()



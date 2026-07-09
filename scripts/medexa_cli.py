#!/usr/bin/env python3
"""Medexa local CLI — test Path A / B / C without a frontend or microphone.

Uses in-memory session store and local config files (no DynamoDB, no S3).

Examples:
  python scripts/medexa_cli.py --demo
  python scripts/medexa_cli.py --interactive
  python scripts/medexa_cli.py --file scripts/fixtures/pt_session_37min_full_transcript.txt --max-chunks 12
  python scripts/medexa_cli.py --interactive --region US

Or use the frontend live session page:
  Typed chunks (no mic) → Path A live · Path B when enabled · Path C on Stop
  GET /sessions/{id}/live-pipeline for a single status snapshot

Bedrock (optional): set in .env before running:
  MEDEXA_PATH_B_ENABLED=true
  MEDEXA_SOAP_GENERATOR=bedrock
  MEDEXA_SUMMARY_GENERATOR=bedrock
  MEDEXA_AWS_REGION=us-east-2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_TIMESTAMP = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*$")
_US_DEMO_CHUNKS = [
    ("00:00", "Patient reports lower back pain for two weeks, pain 6 out of 10."),
    ("04:00", "Starting therapeutic exercise for lumbar stretching and core strengthening."),
    ("08:00", "Continuing therapeutic exercise with resistance band for ten minutes."),
    ("14:00", "Neuromuscular re-education for balance and gait training."),
    ("20:00", "Manual therapy soft tissue mobilization on the lumbar spine."),
    ("26:00", "Applying hot pack to the lower back for fifteen minutes."),
]


def _configure_local_env() -> None:
    os.environ["MEDEXA_USE_DYNAMODB"] = "false"
    os.environ["MEDEXA_CONFIG_SOURCE"] = "local"
    os.environ["MEDEXA_S3_BUCKET"] = ""
    os.environ["MEDEXA_TRANSCRIBE_S3_BUCKET"] = ""


def _banner(live_settings) -> None:
    print("=" * 72)
    print(" Medexa CLI — local Path A / B / C tester")
    print("=" * 72)
    print(f"  Region:          {live_settings.aws_region} (config files: local)")
    print(f"  DynamoDB:        {live_settings.use_dynamodb}")
    print(f"  S3:              {live_settings.s3_bucket or 'off'}")
    print(f"  Path B Bedrock:  {live_settings.path_b_enabled} ({live_settings.path_b_model_id})")
    print(f"  Path C Bedrock:  soap={live_settings.soap_generator} summary={live_settings.summary_generator}")
    print("=" * 72)


def _parse_transcript_file(path: Path) -> list[tuple[str, str]]:
    """Return (timestamp_label, text) chunks from fixture file."""
    chunks: list[tuple[str, str]] = []
    current_ts = "00:00"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = " ".join(line.strip() for line in buffer if line.strip())
        if text and not text.startswith("#"):
            chunks.append((current_ts, text))
        buffer = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TIMESTAMP.match(line)
        if match:
            flush()
            current_ts = f"{int(match.group(1))}:{match.group(2)}"
            continue
        buffer.append(line)
    flush()
    return chunks


def _ts_to_seconds(label: str) -> float:
    if ":" not in label:
        return 0.0
    mins, secs = label.split(":", 1)
    return float(int(mins) * 60 + int(secs))


def _print_path_a(result, state) -> None:
    if result.entities:
        print("  [Path A] Detected:")
        for entity in result.entities[:6]:
            cpt = entity.possible_cpt or "-"
            print(f"    - {entity.matched_phrase!r} -> {cpt} ({entity.body_region or 'no region'})")
    if result.new_alerts:
        print("  [Path A] Alerts:")
        for alert in result.new_alerts:
            print(f"    - [{alert.severity}] {alert.alert_type}: {alert.message}")
    if state.suggestions:
        open_suggestions = [s for s in state.suggestions if s.status == "suggested"]
        if open_suggestions:
            print("  [Path A] Billing suggestions:")
            for sug in open_suggestions[-3:]:
                print(f"    - {sug.title}: {sug.message}")


def _print_path_b(state) -> None:
    if state.path_b_triggers:
        last = state.path_b_triggers[-1]
        print(f"  [Path B] Trigger: {last.reason} ({last.status})")
    if state.assistant_suggestions:
        print("  [Path B] Assistant suggestions:")
        for item in state.assistant_suggestions[-3:]:
            print(f"    - [{item.kind}] {item.title}: {item.body[:120]}")


async def _process_chunk(
    container,
    state,
    text: str,
    *,
    start_label: str,
    seq: int,
    auto_apply: bool = False,
    wall_time: datetime | None = None,
) -> object:
    from medexa.utils.time import now_utc

    runtime = container.runtime_for_state(state.billing_region)
    started = wall_time or now_utc()
    start_ts = _ts_to_seconds(start_label)
    end_ts = start_ts + 15.0
    state.client_elapsed_seconds = int(end_ts)

    print(f"\n--- Chunk {seq + 1} @ {start_label} ---")
    print(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")

    chunk = container.chunk_ingest.ingest(state, text, start_ts=start_ts, end_ts=end_ts)
    result = runtime.path_a_processor.process(state, chunk, started)
    await container.path_a_dispatcher.dispatch(state, result, now=started)

    refreshed = container.session_repo.get(state.session_id)
    if refreshed is not None:
        state = refreshed

    state.last_updated = started
    container.session_repo.save(state)

    if auto_apply and state.suggestions:
        for suggestion in state.suggestions:
            if suggestion.status == "suggested" and suggestion.cpt_code:
                suggestion.status = "applied"
                container.timer_engine.switch_segment(
                    state,
                    suggestion.cpt_code,
                    suggestion.body_region,
                    started,
                )
        container.session_repo.save(state)

    analysis = runtime.path_a_snapshot.build_analysis(state, text)
    state.latest_analysis = analysis
    container.session_repo.save(state)

    _print_path_a(result, state)
    _print_path_b(state)

    panel = result.panel
    if panel.current_cpt:
        print(
            f"  [Timer] Active CPT: {panel.current_cpt.code} "
            f"({panel.current_cpt.duration_sec}s)"
        )
    print(
        f"  [Timer] Session total: {panel.session_timer_sec}s | "
        f"Units: {panel.eight_minute_rule.total_units if panel.eight_minute_rule else 'n/a'}"
    )
    return state


def _finalize(container, state) -> None:
    from medexa.api import contracts as c
    from medexa.utils.time import now_utc

    runtime = container.runtime_for_state(state.billing_region)
    now = now_utc()
    transcript = state.transcript_text or " ".join(c.text for c in state.transcript_chunks)
    body = c.FinalizeSessionRequest(
        transcript=transcript,
        total_seconds=state.client_elapsed_seconds or 0,
    )
    result = container.finalize_orchestrator.finalize(
        state,
        runtime,
        body,
        now=now,
        object_storage=container.export_object_storage(),
    )
    container.session_repo.save(result.state)
    state = result.state

    print("\n" + "=" * 72)
    print(" PATH C — Finalize")
    print("=" * 72)
    print(f"  SOAP chief complaint: {state.soap.subjective.chief_complaint[:120]}")
    print(f"  Assessment: {state.soap.assessment.diagnosis_summary[:120]}")
    print(f"  Patient summary: {state.patient_summary.summary[:200]}")
    print(f"  Billing units: {result.billing_summary.total_units}")
    for item in result.billing_summary.line_items:
        print(f"    - {item.cpt_code} {item.display_name}: {item.units} unit(s), {item.total_seconds}s")
    if result.documentation_review:
        print(f"  Documentation review: {result.documentation_review.open_count} open item(s)")
        for row in result.documentation_review.items[:5]:
            print(f"    - [{row.severity}] {row.title}")
    if result.fhir_export:
        print(f"  FHIR export: {result.fhir_export.storage_uri or 'in-memory'}")
    print("=" * 72)


async def _run_chunks(container, state, chunks: list[tuple[str, str]], *, auto_apply: bool) -> object:
    from medexa.utils.time import now_utc

    base_time = now_utc()
    for seq, (ts, text) in enumerate(chunks):
        wall_time = base_time + timedelta(seconds=_ts_to_seconds(ts))
        state = await _process_chunk(
            container,
            state,
            text,
            start_label=ts,
            seq=seq,
            auto_apply=auto_apply,
            wall_time=wall_time,
        )
        await asyncio.sleep(0.05)
    _finalize(container, state)
    return state


async def _interactive(container, state, *, auto_apply: bool = False) -> object:
    from medexa.utils.time import now_utc

    print("\nInteractive mode. Type transcript lines (empty line to finalize, 'quit' to exit).")
    print("After each chunk, enter minutes until the next one (default 15) so billing timers advance.")
    base_time = now_utc()
    elapsed_sec = 0
    seq = 0
    while True:
        try:
            text = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in {"quit", "exit", "q"}:
            break
        if not text:
            break
        label = f"{elapsed_sec // 60:02d}:{elapsed_sec % 60:02d}"
        wall_time = base_time + timedelta(seconds=elapsed_sec)
        state = await _process_chunk(
            container,
            state,
            text,
            start_label=label,
            seq=seq,
            auto_apply=auto_apply,
            wall_time=wall_time,
        )
        seq += 1
        try:
            mins = input("  Minutes until next chunk? [15]: ").strip()
            elapsed_sec += int(mins) * 60 if mins else 15 * 60
        except ValueError:
            elapsed_sec += 15 * 60
    if seq > 0:
        _finalize(container, state)
    return state


async def main_async(args: argparse.Namespace) -> int:
    _configure_local_env()

    from medexa.api.dependencies import ServiceContainer
    from medexa.config import MedexaConfig
    from medexa.schemas import SessionState

    live_settings = MedexaConfig()
    _banner(live_settings)
    container = ServiceContainer()
    state = SessionState(
        session_id=str(uuid.uuid4()),
        billing_region=args.region,
        patient_name=args.patient,
        status="active",
    )
    container.session_repo.save(state)
    print(f"\nSession started: {state.session_id} (region={state.billing_region})")

    if args.demo:
        state = await _run_chunks(container, state, _US_DEMO_CHUNKS, auto_apply=args.auto_apply)
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        chunks = _parse_transcript_file(path)
        if args.max_chunks:
            chunks = chunks[: args.max_chunks]
        print(f"Loaded {len(chunks)} chunk(s) from {path}")
        state = await _run_chunks(container, state, chunks, auto_apply=args.auto_apply)
    else:
        state = await _interactive(container, state, auto_apply=args.auto_apply)

    if args.json_dump:
        final = container.session_repo.get(state.session_id)
        if final:
            print(json.dumps(final.model_dump(mode="json"), indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Medexa local CLI for Path A/B/C testing")
    parser.add_argument("--region", default="US", choices=["US", "SA", "AE"], help="Billing region")
    parser.add_argument("--patient", default="CLI Test Patient", help="Patient display name")
    parser.add_argument("--demo", action="store_true", help="Run built-in US PT demo chunks")
    parser.add_argument("--interactive", action="store_true", help="Type chunks manually (default)")
    parser.add_argument("--file", type=str, help="Transcript file ([MM:SS] blocks or plain lines)")
    parser.add_argument("--max-chunks", type=int, default=0, help="Limit chunks from file (0=all)")
    parser.add_argument("--auto-apply", action="store_true", help="Auto-apply CPT suggestions (demo/file mode)")
    parser.add_argument("--local", action="store_true", default=True, help="Force in-memory, no AWS storage")
    parser.add_argument("--json-dump", action="store_true", help="Print final session JSON")
    args = parser.parse_args()
    if not args.demo and not args.file:
        args.interactive = True
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

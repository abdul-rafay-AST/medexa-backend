from __future__ import annotations

import uuid
from datetime import datetime

from medexa.schemas import SessionState, TimerSegment


class BillingTimerEngine:
    """Pure session-timer logic. Mutates SessionState but has zero dependency on
    FastAPI, AWS, or the clock (the caller passes ``now``), so it is fully testable.
    """

    def accumulated_seconds(self, segment: TimerSegment, now: datetime) -> int:
        """Total seconds a segment has run, including live time if still running."""
        total = segment.accumulated_seconds
        if segment.stop_time is None:
            total += max(0, int((now - segment.start_time).total_seconds()))
        return total

    def start_segment(
        self,
        state: SessionState,
        cpt_code: str,
        body_region: str | None,
        now: datetime,
        is_billable: bool = True,
    ) -> TimerSegment:
        """Begin timing a CPT. Does not stop other running segments (use
        ``switch_segment`` for a mutually exclusive switch)."""
        segment = TimerSegment(
            segment_id=str(uuid.uuid4()),
            cpt_code=cpt_code,
            body_region=body_region,
            start_time=now,
            is_billable=is_billable,
        )
        state.timer_segments.append(segment)
        state.active_cpt = cpt_code
        state.active_body_region = body_region
        state.is_currently_billable = is_billable
        return segment

    def stop_segment(self, state: SessionState, segment_id: str, now: datetime) -> bool:
        """Stop one running segment by id. Returns True if a running segment matched."""
        for seg in state.timer_segments:
            if seg.segment_id == segment_id and seg.stop_time is None:
                self._finalize(seg, now)
                if state.active_cpt == seg.cpt_code:
                    state.active_cpt = None
                    state.active_body_region = None
                    state.is_currently_billable = False
                return True
        return False

    def stop_all_running(self, state: SessionState, now: datetime) -> None:
        """Stop every running segment (used on pause/end)."""
        for seg in state.timer_segments:
            if seg.stop_time is None:
                self._finalize(seg, now)
        state.is_currently_billable = False

    def switch_segment(
        self,
        state: SessionState,
        cpt_code: str,
        body_region: str | None,
        now: datetime,
    ) -> TimerSegment:
        """Stop whatever is running and start a new segment (mutually exclusive)."""
        self.stop_all_running(state, now)
        return self.start_segment(state, cpt_code, body_region, now)

    def _finalize(self, segment: TimerSegment, now: datetime) -> None:
        segment.accumulated_seconds = self.accumulated_seconds(segment, now)
        segment.stop_time = now

    def seconds_by_cpt(self, state: SessionState, now: datetime) -> dict[str, int]:
        """Aggregate total seconds per CPT across all segments in the session."""
        totals: dict[str, int] = {}
        for seg in state.timer_segments:
            totals[seg.cpt_code] = totals.get(seg.cpt_code, 0) + self.accumulated_seconds(seg, now)
        return totals

    def running_segment_seconds(self, state: SessionState, now: datetime) -> int:
        """Seconds on the currently running segment only (0 if none)."""
        for seg in reversed(state.timer_segments):
            if seg.stop_time is None:
                return self.accumulated_seconds(seg, now)
        return 0

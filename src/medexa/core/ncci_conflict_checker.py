from typing import List
import uuid

from medexa.schemas import Alert
from medexa.loaders.ncci_rules_loader import NcciRule, NcciRulesLoader

class NcciConflictChecker:
    """
    Checks active session CPT codes against the NCCI rules engine to flag billing conflicts.
    Generates Alerts that are completely decoupled from network boundaries.
    """
    
    def __init__(self, rules_loader: NcciRulesLoader):
        self._rules_loader = rules_loader

    def check_conflict(self, cpt_a: str, cpt_b: str) -> NcciRule | None:
        return self._rules_loader.check_conflict(cpt_a, cpt_b)

    def check_conflicts(
        self,
        session_id: str,
        active_segments: List[tuple[str, str | None]],
    ) -> List[Alert]:
        """
        Cross-references active timed segments to find NCCI conflicts.

        Each item in ``active_segments`` is a ``(cpt_code, body_region)`` pair.
        Body-region-sensitive rules only fire when BOTH services share the same,
        non-null body region (Modifier 59 separates distinct regions). Non-sensitive
        rules fire whenever the conflicting pair is active together.
        """
        alerts: List[Alert] = []

        # Need at least two segments to have a conflict.
        if len(active_segments) < 2:
            return alerts

        # Dedupe so we raise at most one alert per (cpt pair, body region).
        seen: set[tuple[str, str, str | None]] = set()

        for i in range(len(active_segments)):
            for j in range(i + 1, len(active_segments)):
                cpt_a, region_a = active_segments[i]
                cpt_b, region_b = active_segments[j]

                if cpt_a == cpt_b:
                    continue

                rule = self._rules_loader.check_conflict(cpt_a, cpt_b)
                if not rule:
                    continue

                if rule["body_region_sensitive"]:
                    # Only a conflict when performed on the exact same body region.
                    if region_a is None or region_a != region_b:
                        continue
                    conflict_region = region_a
                else:
                    conflict_region = None

                dedupe_key = (min(cpt_a, cpt_b), max(cpt_a, cpt_b), conflict_region)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                message = f"Potential conflict between {cpt_a} and {cpt_b}. " + rule["explanation"]
                if rule["modifier_59_possible"]:
                    message += " Modifier 59 may apply if services were distinct."

                alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        session_id=session_id,
                        alert_type="ncci_conflict",
                        severity="high",
                        message=message,
                        cpt_codes=[cpt_a, cpt_b],
                        body_region=conflict_region,
                    )
                )

        return alerts

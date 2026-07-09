from medexa.schemas import EightMinuteRuleResult

class EightMinuteRuleCalculator:
    """
    Calculates billable units based on the CMS 8-Minute Rule.
    Includes the 'Largest Remainder' rule for assigning partial units across multiple timed CPTs.
    """
    
    # CMS 8-Minute Rule thresholds (Total Minutes -> Total Units) for 8-127 minutes.
    _THRESHOLDS = [
        (8, 22, 1),
        (23, 37, 2),
        (38, 52, 3),
        (53, 67, 4),
        (68, 82, 5),
        (83, 97, 6),
        (98, 112, 7),
        (113, 127, 8),
    ]

    @staticmethod
    def _units_from_minutes(total_minutes: int) -> int:
        """CMS pooled timed minutes -> billable units (extends beyond 127 min)."""
        if total_minutes < 8:
            return 0
        return (total_minutes - 8) // 15 + 1

    @staticmethod
    def _seconds_to_next_unit(total_minutes: int, total_units: int) -> int:
        """Seconds until the next pooled unit threshold."""
        if total_minutes < 8:
            return (8 - total_minutes) * 60
        next_threshold = 8 + total_units * 15
        return max(0, (next_threshold - total_minutes) * 60)

    def calculate(self, minutes_by_cpt: dict[str, int]) -> EightMinuteRuleResult:
        """
        Calculates the total units and allocates them to specific CPT codes based on minutes.
        """
        total_minutes = sum(minutes_by_cpt.values())

        total_units = self._units_from_minutes(total_minutes)
        seconds_to_next_unit = self._seconds_to_next_unit(total_minutes, total_units)
        units_by_cpt = {cpt: 0 for cpt in minutes_by_cpt}
        remainders = {}
        
        allocated_units = 0
        for cpt, minutes in minutes_by_cpt.items():
            base_units = minutes // 15
            units_by_cpt[cpt] = base_units
            allocated_units += base_units
            remainders[cpt] = minutes % 15
            
        # 4. Largest remainder allocation
        # The CMS table already accounts for the aggregate remainder when deriving
        # total_units. Any unit not covered by full 15-min blocks must still be billed,
        # and CMS assigns it to the service(s) with the most leftover minutes -- NOT
        # gated at >= 8 (that gate only qualifies a *standalone* service). Gating here
        # would silently drop a billable unit (e.g. 7 + 7 min => 1 unit, dropped).
        units_remaining_to_allocate = total_units - allocated_units
        remainder_assigned_to = None

        if units_remaining_to_allocate > 0 and remainders:
            # Sort by leftover minutes (desc), then CPT code for deterministic ties.
            sorted_remainders = sorted(
                remainders.items(), key=lambda item: (item[1], item[0]), reverse=True
            )
            index = 0
            count = len(sorted_remainders)
            while units_remaining_to_allocate > 0:
                cpt, _ = sorted_remainders[index % count]
                units_by_cpt[cpt] += 1
                if remainder_assigned_to is None:
                    remainder_assigned_to = cpt
                units_remaining_to_allocate -= 1
                index += 1

        return EightMinuteRuleResult(
            total_minutes=total_minutes,
            total_units=total_units,
            units_by_cpt=units_by_cpt,
            minutes_by_cpt=minutes_by_cpt,
            remainder_minutes=sum(remainders.values()),
            remainder_assigned_to=remainder_assigned_to,
            seconds_to_next_unit=seconds_to_next_unit
        )

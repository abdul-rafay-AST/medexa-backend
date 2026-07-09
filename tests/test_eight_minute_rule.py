from medexa.core.eight_minute_rule import EightMinuteRuleCalculator


calc = EightMinuteRuleCalculator()


def test_no_time_is_zero_units():
    result = calc.calculate({})
    assert result.total_units == 0
    assert result.seconds_to_next_unit == 8 * 60


def test_single_cpt_one_unit():
    result = calc.calculate({"97110": 14})
    assert result.total_units == 1
    assert result.units_by_cpt == {"97110": 1}
    assert result.remainder_assigned_to == "97110"


def test_leftover_unit_not_dropped_bug_a():
    # 7 + 7 = 14 min -> table says 1 unit. The leftover unit must NOT vanish.
    result = calc.calculate({"97110": 7, "97140": 7})
    assert result.total_units == 1
    assert sum(result.units_by_cpt.values()) == 1


def test_two_leftover_units_distributed():
    # 14 + 14 = 28 min -> 2 units, base allocation is 0+0, both leftovers assigned.
    result = calc.calculate({"97110": 14, "97140": 14})
    assert result.total_units == 2
    assert result.units_by_cpt == {"97110": 1, "97140": 1}


def test_largest_remainder_wins():
    # 20 + 7 = 27 min -> 2 units. 97110 gets base 1, leftover goes to 97140 (rem 7 > 5).
    result = calc.calculate({"97110": 20, "97140": 7})
    assert result.total_units == 2
    assert result.units_by_cpt == {"97110": 1, "97140": 1}
    assert result.remainder_assigned_to == "97140"

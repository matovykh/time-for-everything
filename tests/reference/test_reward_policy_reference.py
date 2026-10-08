"""Self-tests of the QA reference oracle against the literal examples in SPECIFICATION §5/§6/§14.

Run (stdlib only):  python3 -m unittest discover -s tests/reference -v
These do NOT test the backend. Backend parity tests live in tests/backend/ once it exists.
"""

import os
import sys
import unittest
from datetime import date
from fractions import Fraction

sys.path.insert(0, os.path.dirname(__file__))

from reward_policy_v1 import (  # noqa: E402
    WalkDay,
    ai_allowed_range,
    chores_award,
    clamp_ai_amount,
    evaluation_windows,
    final_period_ends,
    lesson_progress,
    lesson_subject_award,
    lessons_total,
    voluntary_award,
    walk_award,
)


class LessonsSpecExamples(unittest.TestCase):
    def test_35_to_30_is_20(self):
        r = lesson_subject_award([35, 35, 35], [30, 30, 30])
        self.assertEqual((r.status, r.amount), ("final", 20))

    def test_35_to_35_is_0(self):
        self.assertEqual(lesson_subject_award([35] * 3, [35] * 3).amount, 0)

    def test_no_current_records_is_insufficient_not_100pct(self):
        r = lesson_subject_award([35] * 5, [])
        self.assertEqual((r.status, r.amount), ("insufficient_data", 0))

    def test_slower_is_zero_never_negative(self):
        self.assertEqual(lesson_subject_award([30] * 3, [40] * 3).amount, 0)

    def test_base_zero_is_insufficient(self):
        self.assertEqual(lesson_subject_award([0] * 3, [0] * 3).status, "insufficient_data")

    def test_two_days_is_insufficient(self):
        self.assertEqual(lesson_subject_award([35, 35], [10, 10, 10]).status, "insufficient_data")

    def test_five_subjects_capped_at_100(self):
        self.assertEqual(lessons_total([30] * 5), 100)

    def test_exact_boundaries_inclusive_no_float_drift(self):
        # p exactly 5%, 10%, 15% must hit the tier ("от 5%")
        self.assertEqual(lesson_subject_award([20] * 3, [19] * 3).amount, 10)
        self.assertEqual(lesson_subject_award([100] * 3, [90] * 3).amount, 20)
        self.assertEqual(lesson_subject_award([60] * 3, [51] * 3).amount, 30)
        # float trap: 0.1*3 style values in seconds
        self.assertEqual(lesson_subject_award([2100] * 3, [1785] * 3).amount, 30)  # 15% exactly
        self.assertEqual(lesson_subject_award([2100] * 3, [1786] * 3).amount, 20)

    def test_median_not_mean_and_not_fastest_pick(self):
        # one very fast outlier must not create a reward on its own
        self.assertEqual(lesson_progress([35, 35, 35], [5, 35, 35]), Fraction(0))

    def test_even_median(self):
        self.assertEqual(lesson_progress([30, 40, 30, 40], [35, 35, 35]), Fraction(0))


class WalkSpecExamples(unittest.TestCase):
    def d(self, *mins):
        return [WalkDay("recorded", m) for m in mins]

    def test_five_of_seven_target_gives_40(self):
        self.assertEqual(walk_award(self.d(120, 120, 130, 125, 240, 0, 60)).amount, 40)

    def test_240_minutes_not_double(self):
        self.assertEqual(walk_award(self.d(*[240] * 7)).amount, 40)

    def test_missing_blocks_final(self):
        days = self.d(120, 120, 120, 120, 120, 120) + [WalkDay("missing")]
        self.assertEqual(walk_award(days).status, "preliminary")

    def test_excluded_days_shrink_e_and_threshold(self):
        # E=6 -> ceil(30/7)=5
        days = self.d(120, 120, 120, 120, 60, 60) + [WalkDay("excluded")]
        self.assertEqual(walk_award(days).amount, 0)
        days = self.d(120, 120, 120, 120, 120, 60) + [WalkDay("excluded")]
        self.assertEqual(walk_award(days).amount, 40)
        # E=5 -> ceil(25/7)=4
        days = self.d(120, 120, 120, 120, 0) + [WalkDay("excluded")] * 2
        self.assertEqual(walk_award(days).amount, 40)

    def test_e_below_5_is_insufficient(self):
        days = self.d(120, 120, 120, 120) + [WalkDay("excluded")] * 3
        self.assertEqual(walk_award(days).status, "insufficient_data")

    def test_no_walk_counts_as_zero_included(self):
        days = self.d(120, 120, 120, 120) + [WalkDay("no_walk")] * 3  # K=4 < 5
        self.assertEqual(walk_award(days).amount, 0)

    def test_improvement_branch_20(self):
        cur = self.d(100, 100, 100, 100, 100, 0, 0)  # R=500/840≈0.595 -> below 0.60
        self.assertEqual(walk_award(cur, base_r=Fraction(1, 10)).amount, 0)
        cur = self.d(100, 100, 100, 100, 100, 100, 0)  # R=600/840≈0.714, K=0
        self.assertEqual(walk_award(cur, base_r=Fraction(6, 10)).amount, 20)
        self.assertEqual(walk_award(cur, base_r=None).amount, 0)  # unknown base: no improvement reward

    def test_branches_not_summed(self):
        self.assertEqual(walk_award(self.d(*[120] * 7), base_r=Fraction(0)).amount, 40)


class ChoresSpecExamples(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(chores_award(10, 10, 5, 5).amount, 28)
        self.assertEqual(chores_award(10, 6, 5, 5).amount, 14)
        self.assertEqual(chores_award(10, 5, 5, 5).amount, 0)

    def test_n_zero_no_award_not_100pct(self):
        r = chores_award(0, 0, 0, 0)
        self.assertEqual((r.status, r.amount), ("insufficient_data", 0))

    def test_single_weekly_friday_chore_qualifies(self):
        self.assertEqual(chores_award(1, 1, 1, 1).amount, 20 + 0 + 5)

    def test_cap_40(self):
        self.assertEqual(chores_award(60, 60, 7, 7).amount, 40)

    def test_regularity_distinct_days(self):
        self.assertEqual(chores_award(10, 10, 2, 7).amount, 0)


class VoluntaryAndAI(unittest.TestCase):
    def test_voluntary_caps_and_toggle_dupes(self):
        self.assertEqual(voluntary_award([["a", "a", "a"]]), 2)  # re-check same day = 1 fact
        self.assertEqual(voluntary_award([["a", "b", "c", "d"]]), 6)
        self.assertEqual(voluntary_award([["a", "b", "c"]] * 7), 20)

    def test_ai_range_and_lessons_zero(self):
        self.assertEqual(ai_allowed_range("lessons", 0, 100, lesson_progress_positive=False), (0, 0))
        self.assertEqual(ai_allowed_range("chores", 28, 40), (28, 30))
        self.assertEqual(ai_allowed_range("walk", 40, 40), (40, 40))

    def test_ai_proposal_validation(self):
        for bad in (31, -1, 27, "30", 29.5, True, None):
            self.assertEqual(clamp_ai_amount(bad, 28, 30, 28), 28)
        self.assertEqual(clamp_ai_amount(30, 28, 30, 28), 30)


class Windows(unittest.TestCase):
    def test_window_bounds_exclude_today(self):
        cur, base = evaluation_windows(date(2026, 10, 15))
        self.assertEqual(cur, (date(2026, 10, 8), date(2026, 10, 14)))
        self.assertEqual(base, (date(2026, 10, 1), date(2026, 10, 7)))

    def test_final_periods_non_overlapping_every_7(self):
        ends = final_period_ends(date(2026, 10, 1), date(2026, 11, 1))
        self.assertEqual(ends, [date(2026, 10, 14), date(2026, 10, 21), date(2026, 10, 28)])


if __name__ == "__main__":
    unittest.main()

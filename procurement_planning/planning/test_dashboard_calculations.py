# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Deterministic tests for the dashboard calculations (no database needed)."""

import unittest
from datetime import date

from procurement_planning.planning.dashboard_calculations import (
	FUNNEL_STAGES,
	agreement_drawdown,
	agreement_flags,
	first_of_next_month,
	funnel,
	furthest_stage,
	group_totals,
	is_at_risk,
	margin_percent,
	quarter_range,
	risk_by_class,
	slow_suppliers,
	spread_plan_by_month,
	top_items_to_buy,
	win_rate,
)


class TestDates(unittest.TestCase):
	def test_quarter_range(self):
		self.assertEqual(quarter_range(date(2026, 11, 2)), (date(2026, 10, 1), date(2026, 12, 31)))
		self.assertEqual(quarter_range(date(2026, 2, 28)), (date(2026, 1, 1), date(2026, 3, 31)))

	def test_first_of_next_month(self):
		self.assertEqual(first_of_next_month(date(2026, 12, 15)), date(2027, 1, 1))
		self.assertEqual(first_of_next_month(date(2026, 11, 2)), date(2026, 12, 1))


class TestBlanketOrders(unittest.TestCase):
	def test_spread_full_year(self):
		plan = spread_plan_by_month([{"from_date": date(2026, 1, 1), "to_date": date(2026, 12, 31), "value": 1200}], 2026)
		self.assertEqual(set(plan.values()), {100})

	def test_spread_across_years(self):
		# Jul 2026 - Jun 2027: 12 months, 6 in 2026
		plan = spread_plan_by_month([{"from_date": date(2026, 7, 1), "to_date": date(2027, 6, 30), "value": 1200}], 2026)
		self.assertEqual(plan[6], 0)
		self.assertEqual(plan[7], 100)
		self.assertEqual(sum(plan.values()), 600)

	def test_drawdown_and_flags(self):
		planned, ordered, percent = agreement_drawdown([(100, 90, 525), (10, 0, 100)])
		self.assertEqual(planned, 53500)
		self.assertEqual(ordered, 47250)
		self.assertAlmostEqual(percent, 47250 / 53500 * 100)
		self.assertEqual(agreement_flags(date(2026, 11, 20), 90, date(2026, 11, 2)), ["ending", "nearly_used"])
		self.assertEqual(agreement_flags(date(2027, 3, 1), 10, date(2026, 11, 2)), [])
		self.assertEqual(agreement_drawdown([]), (0, 0, 0))


class TestPlanning(unittest.TestCase):
	def test_slow_suppliers(self):
		samples = [("A", None, 50), ("A", "X", 70), ("A", None, 60), ("B", None, 20), ("C", None, 99)]
		profiles = {("A", None): 40, ("B", None): 30, ("C", "Y"): 50, ("C", "Z"): 70}
		result = slow_suppliers(samples, profiles)
		self.assertEqual([row["supplier"] for row in result], ["C", "A"])
		self.assertEqual((result[1]["median_days"], result[1]["profile_days"]), (60, 40))
		self.assertEqual(result[0]["profile_days"], 60)

	def test_top_items(self):
		rows = [
			{"item_code": "low", "suggested_purchase": 5, "stockout_risk": "Low", "suggested_value": 9999},
			{"item_code": "high-small", "suggested_purchase": 1, "stockout_risk": "High", "suggested_value": 10},
			{"item_code": "high-big", "suggested_purchase": 1, "stockout_risk": "High", "suggested_value": 100},
			{"item_code": "none", "suggested_purchase": 0, "stockout_risk": "High", "suggested_value": 0},
		]
		self.assertEqual([r["item_code"] for r in top_items_to_buy(rows)], ["high-big", "high-small", "low"])

	def test_group_and_risk(self):
		rows = [
			{"supplier": "A", "suggested_value": 10, "stockout_risk": "High", "abc_class": "A"},
			{"supplier": "B", "suggested_value": 30, "stockout_risk": "Low", "abc_class": "A"},
			{"supplier": "A", "suggested_value": 25, "stockout_risk": "High", "abc_class": "C"},
			{"supplier": None, "suggested_value": 99},
		]
		self.assertEqual(group_totals(rows, "supplier", "suggested_value"), [("A", 35), ("B", 30)])
		self.assertEqual(group_totals(rows, "supplier", "suggested_value", limit=1), [("A", 35)])
		self.assertEqual(risk_by_class(rows, ["A", "B", "C"])["High"], [1, 0, 1])


class TestBackToBack(unittest.TestCase):
	def test_funnel(self):
		stages = [
			furthest_stage([True, True, True, True, True, False, False, False, False]),
			furthest_stage([True, True, False, False, False, False, False, False, False]),
			furthest_stage([True] + [False] * 8),
			furthest_stage([True] * 9),
		]
		rows = funnel(stages)
		self.assertEqual([r["count"] for r in rows], [4, 3, 2, 2, 2, 1, 1, 1, 1])
		self.assertEqual(rows[0]["label"], FUNNEL_STAGES[0])
		self.assertAlmostEqual(rows[1]["drop_off"], 25)
		self.assertAlmostEqual(rows[2]["percent"], 50)
		self.assertEqual([r["count"] for r in funnel([])], [0] * 9)

	def test_rates(self):
		self.assertEqual(win_rate(4, 3), 75)
		self.assertIsNone(win_rate(0, 0))
		self.assertAlmostEqual(margin_percent(2750, 2200), 20)
		self.assertIsNone(margin_percent(0, 10))

	def test_at_risk(self):
		self.assertTrue(is_at_risk(-7))
		self.assertTrue(is_at_risk(0))
		self.assertFalse(is_at_risk(1))
		self.assertFalse(is_at_risk(-8))
		self.assertFalse(is_at_risk(None))

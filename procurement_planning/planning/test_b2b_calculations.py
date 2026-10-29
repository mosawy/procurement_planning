# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Deterministic tests for the back-to-back calculations (no database needed)."""

import unittest
from datetime import date

from procurement_planning.planning.b2b_calculations import (
	EXCESS_CUSTOMER_BEARS,
	EXCESS_TO_STOCK,
	back_to_back_stage,
	customer_unit_cost,
	estimated_landed_cost,
	margin_percent,
	offer_lead_time,
	promised_date,
	purchase_quantity,
	rank_offers,
	selling_rate,
	weighted_average_cost,
)


class TestCost(unittest.TestCase):
	def test_landed_cost(self):
		self.assertAlmostEqual(estimated_landed_cost(100, 10), 110)
		self.assertAlmostEqual(estimated_landed_cost(100, 10, 2, foreign_currency=True), 112)
		self.assertAlmostEqual(estimated_landed_cost(100, 10, 2, foreign_currency=False), 110)

	def test_moq(self):
		self.assertEqual(purchase_quantity(10, 20), (20, 10))
		self.assertEqual(purchase_quantity(30, 20), (30, 0))
		self.assertEqual(purchase_quantity(10, 0), (10, 0))

	def test_excess_pricing(self):
		# need 10, bought 20 at 100: customer bears -> 200 per unit
		self.assertAlmostEqual(customer_unit_cost(100, 10, 20, EXCESS_CUSTOMER_BEARS), 200)
		self.assertAlmostEqual(customer_unit_cost(100, 10, 20, EXCESS_TO_STOCK), 100)

	def test_margin(self):
		self.assertAlmostEqual(selling_rate(80, 20), 100)
		self.assertAlmostEqual(margin_percent(100, 80), 20)
		self.assertEqual(margin_percent(0, 80), 0)
		with self.assertRaises(ValueError):
			selling_rate(80, 100)

	def test_weighted_average(self):
		self.assertEqual(weighted_average_cost([(25, 100), (15, 110)]), (40, 103.75))
		self.assertEqual(weighted_average_cost([]), (0, None))


class TestDates(unittest.TestCase):
	def test_lead_time(self):
		self.assertEqual(offer_lead_time(date(2026, 10, 1), 45), 45)
		self.assertEqual(offer_lead_time(date(2026, 10, 1), 0, date(2026, 10, 31)), 30)
		self.assertIsNone(offer_lead_time(date(2026, 10, 1)))

	def test_promised_date(self):
		self.assertEqual(promised_date(date(2026, 10, 1), 45, 7), date(2026, 11, 22))
		self.assertIsNone(promised_date(date(2026, 10, 1), None, 7))

	def test_ranking(self):
		cheap_slow = {"name": "A", "customer_unit_cost": 100, "promised_date": date(2026, 12, 1)}
		dear_fast = {"name": "B", "customer_unit_cost": 120, "promised_date": date(2026, 11, 1)}
		expired = {"name": "C", "customer_unit_cost": 50, "promised_date": date(2026, 10, 15), "expired": True}
		undated = {"name": "D", "customer_unit_cost": 90, "promised_date": None}
		offers = [cheap_slow, dear_fast, expired, undated]
		self.assertEqual([o["name"] for o in rank_offers(offers, "Normal")], ["D", "A", "B", "C"])
		self.assertEqual([o["name"] for o in rank_offers(offers, "Urgent")], ["B", "A", "D", "C"])


class TestStage(unittest.TestCase):
	def test_stages(self):
		self.assertEqual(back_to_back_stage(0, 0, 0, 0, 10), "Not Ordered")
		self.assertEqual(back_to_back_stage(0, 0, 0, 0, 10, has_draft_po=True), "PO Draft")
		self.assertEqual(back_to_back_stage(10, 0, 0, 0, 10), "Ordered")
		self.assertEqual(back_to_back_stage(10, 10, 0, 0, 10), "Shipped")
		self.assertEqual(back_to_back_stage(10, 10, 4, 0, 10), "Partly Received")
		self.assertEqual(back_to_back_stage(10, 10, 10, 0, 10), "Received")
		self.assertEqual(back_to_back_stage(10, 10, 10, 10, 10), "Delivered")


if __name__ == "__main__":
	unittest.main()

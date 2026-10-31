# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Deterministic tests for the back-to-back calculations (no database needed)."""

import unittest
from datetime import date

from procurement_planning.planning.b2b_calculations import (
	QTY_CHANGE_BLOCK,
	QTY_CHANGE_WARN,
	EXCESS_CUSTOMER_BEARS,
	EXCESS_TO_STOCK,
	back_to_back_stage,
	customer_unit_cost,
	days_late,
	estimated_landed_cost,
	evaluate_offer,
	line_gross_profit,
	margin_percent,
	offer_lead_time,
	promised_date,
	purchase_line_cost,
	purchase_order_split,
	purchase_quantity,
	quotation_rate,
	rank_offers,
	selling_rate,
	sourced_qty_change,
	sourcing_rates,
	sourcing_request_status,
	sourcing_status,
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


class TestOfferEvaluation(unittest.TestCase):
	def offer(self, **kw):
		values = {
			"unit_cost": 100,
			"min_order_qty": 0,
			"foreign_currency": True,
			"quotation_date": date(2026, 10, 1),
			"lead_time_days": 30,
			"expected_delivery_date": None,
			"valid_till": date(2026, 11, 30),
		}
		values.update(kw)
		return values

	def test_foreign_offer_with_moq_customer_bears(self):
		result = evaluate_offer(
			self.offer(min_order_qty=20),
			10,
			date(2026, 10, 29),
			landed_cost_percent=10,
			fx_buffer_percent=2,
			buffer_days=7,
			excess_pricing=EXCESS_CUSTOMER_BEARS,
		)
		self.assertAlmostEqual(result["landed_cost"], 112)
		self.assertEqual((result["purchase_qty"], result["excess_qty"]), (20, 10))
		self.assertAlmostEqual(result["customer_unit_cost"], 224)
		self.assertEqual(result["promised_date"], date(2026, 12, 5))
		self.assertFalse(result["expired"])

	def test_local_offer_excess_to_stock_expired(self):
		result = evaluate_offer(
			self.offer(foreign_currency=False, min_order_qty=20, valid_till=date(2026, 10, 1)),
			10,
			date(2026, 10, 29),
			landed_cost_percent=10,
			fx_buffer_percent=2,
		)
		self.assertAlmostEqual(result["customer_unit_cost"], 110)
		self.assertTrue(result["expired"])

	def test_no_lead_time(self):
		result = evaluate_offer(self.offer(lead_time_days=0), 5, date(2026, 10, 29))
		self.assertIsNone(result["lead_time_days"])
		self.assertIsNone(result["promised_date"])

	def test_quotation_rate(self):
		# cost 80 per piece, 20% margin, box of 10, quotation in USD at 3.75 SAR
		self.assertAlmostEqual(quotation_rate(80, 20, 10, 3.75), 1000 / 3.75)
		self.assertAlmostEqual(quotation_rate(80, 20), 100)

	def test_sourcing_status(self):
		self.assertEqual(sourcing_status([{"needs_sourcing": 0}]), "")
		self.assertEqual(
			sourcing_status([{"needs_sourcing": 1, "supplier_quotation_item": "x"}, {"needs_sourcing": 0}]),
			"Ready for Pricing",
		)
		self.assertEqual(
			sourcing_status([{"needs_sourcing": 1, "supplier_quotation_item": "x"}, {"needs_sourcing": 1}]),
			"Pending Sourcing",
		)

	def test_purchase_order_split(self):
		self.assertEqual(purchase_order_split(10, 25), (10, 15))
		self.assertEqual(purchase_order_split(30, 25), (30, 0))


class TestTracking(unittest.TestCase):
	def test_days_late(self):
		self.assertEqual(days_late(date(2026, 11, 10), date(2026, 11, 5)), 5)
		self.assertEqual(days_late(date(2026, 11, 1), date(2026, 11, 5)), -4)
		self.assertIsNone(days_late(None, date(2026, 11, 5)))

	def test_purchase_line_cost(self):
		self.assertEqual(purchase_line_cost(0, 0, 10, 110), (110, "Estimated"))
		self.assertEqual(purchase_line_cost(10, 1150, 0, 110), (115, "Actual"))
		cost, basis = purchase_line_cost(5, 600, 5, 110)
		self.assertAlmostEqual(cost, 115)
		self.assertEqual(basis, "Mixed")
		self.assertEqual(purchase_line_cost(0, 0, 0, 110), (None, "Estimated"))


class TestGrossProfit(unittest.TestCase):
	def test_line_gross_profit(self):
		# VM case: 10 pieces at 275, landed cost 220 -> 550, not 2,750
		self.assertAlmostEqual(line_gross_profit(275, 1, 220, 10), 550)
		# box of 10 sold at 2,750 per box, 2 boxes
		self.assertAlmostEqual(line_gross_profit(2750, 10, 220, 20), 1100)


class TestSourcingRequest(unittest.TestCase):
	def test_sourcing_rates(self):
		# landed cost 220, margin 20% -> 275; minimum margin 10% -> 244.44
		suggested, minimum = sourcing_rates(220, 20, 10)
		self.assertAlmostEqual(suggested, 275)
		self.assertAlmostEqual(minimum, 220 / 0.9)
		self.assertEqual(sourcing_rates(100, 0, 0), (100, 100))

	def test_sourced_qty_change_excess_to_stock(self):
		self.assertIsNone(sourced_qty_change(10, 10))
		self.assertEqual(sourced_qty_change(10, 12), QTY_CHANGE_BLOCK)
		self.assertEqual(sourced_qty_change(10, 8), QTY_CHANGE_WARN)
		self.assertIsNone(sourced_qty_change(0, 8))

	def test_sourced_qty_change_customer_bears_excess(self):
		self.assertEqual(sourced_qty_change(10, 12, customer_bears_excess=True), QTY_CHANGE_BLOCK)
		self.assertEqual(sourced_qty_change(10, 8, customer_bears_excess=True), QTY_CHANGE_BLOCK)
		self.assertIsNone(sourced_qty_change(10, 10, customer_bears_excess=True))

	def test_sourcing_request_status(self):
		self.assertEqual(sourcing_request_status(0, 0, 2), "Draft")
		self.assertEqual(sourcing_request_status(0, 0, 2, has_rfq=True), "Waiting for Offers")
		self.assertEqual(sourcing_request_status(0, 1, 2), "Waiting for Offers")
		self.assertEqual(sourcing_request_status(0, 2, 2), "Ready")
		self.assertEqual(sourcing_request_status(1, 2, 2), "Submitted")
		self.assertEqual(sourcing_request_status(2, 2, 2), "Cancelled")

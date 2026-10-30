# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Deterministic tests for the pure calculation modules (no database needed)."""

import unittest
from datetime import date

from procurement_planning.planning.demand_history import (
	count_stockout_days,
	opening_balance,
	select_demand_months,
	stockout_months,
)
from procurement_planning.planning.lead_time import (
	SOURCE_DEFAULT,
	SOURCE_ITEM,
	SOURCE_PROFILE,
	SUPPLIER_BLANKET_ORDER,
	SUPPLIER_ITEM_DEFAULT,
	SUPPLIER_LAST_PO,
	effective_entry,
	pick_history_supplier,
	resolve_lead_time,
	pick_blanket_order,
	resolve_supplier,
	summarise_lead_times,
)
from procurement_planning.planning.proposed_calculations import (
	PO_BUCKETS,
	calculate_proposed,
	round_to_multiple,
	split_purchase_orders,
)
from procurement_planning.planning.sap_calculations import (
	NON_MOVING_CLASS,
	calculate_sap,
	ceil_qty,
	classify_abc,
	count_months_with_sales,
)

NO_PO = {"late": 0, "due": 0, "beyond": 0, "undated": 0}


def proposed(**overrides):
	args = dict(
		net_sales=730,
		eligible_months=12,
		analysis_months=12,
		is_non_moving=False,
		lead_time_days=60,
		safety_stock_days=45,
		review_period_days=30,
		stock=0,
		open_so=0,
		po_buckets=NO_PO,
		min_order_qty=0,
	)
	args.update(overrides)
	return calculate_proposed(**args)


class TestABC(unittest.TestCase):
	def test_class_boundaries(self):
		expected = {12: "A", 10: "A", 9: "B", 8: "B", 7: "C", 6: "C", 5: "D", 4: "D", 3: "E", 2: "E", 1: "F"}
		for months, abc_class in expected.items():
			self.assertEqual(classify_abc(months), abc_class, months)

	def test_zero_months_is_non_moving(self):
		self.assertEqual(classify_abc(0), NON_MOVING_CLASS)

	def test_only_positive_months_count(self):
		self.assertEqual(count_months_with_sales([5, 0, -3, 1, 0.5]), 3)


class TestCeil(unittest.TestCase):
	def test_float_noise_is_ignored(self):
		self.assertEqual(ceil_qty(365 / 365 * 30), 30)
		self.assertEqual(ceil_qty(0.1 * 3 * 10), 3)
		self.assertEqual(ceil_qty(30.2), 31)

	def test_small_real_fractions_round_up(self):
		self.assertEqual(ceil_qty(0.0000004), 1)
		self.assertEqual(ceil_qty(30.0000004), 31)
		self.assertEqual(ceil_qty(0), 0)
		self.assertEqual(ceil_qty(-0.5), 0)


class TestSAP(unittest.TestCase):
	def test_formulas(self):
		# 730 / 365 = 2 per day; 730 / 12 per month; 10 selling months.
		sap = calculate_sap(730, 10, stock=100, open_po=50, open_so=30, abc_class="A", grace_days=20, pr_foreign=5)
		self.assertAlmostEqual(sap["avg_mon"], 730 / 12)
		self.assertAlmostEqual(sap["avg_cont"], 73)
		self.assertAlmostEqual(sap["daily_avg"], 2)
		self.assertEqual(sap["reorder"], 40)
		self.assertEqual(sap["safety"], 90)
		self.assertEqual(sap["max"], 130)
		self.assertEqual(sap["miss_qty"], 120)
		self.assertEqual(sap["missing_so"], 125)
		self.assertEqual(sap["to_reorder"], 85)
		self.assertEqual(sap["to_reorder_final"], 80)
		self.assertAlmostEqual(sap["rec_qty"], 730 + 30 - 100 - 50 - 5)

	def test_rec_qty_not_negative(self):
		sap = calculate_sap(12, 1, stock=1000, open_po=0, open_so=0, abc_class="F", grace_days=10, pr_foreign=0)
		self.assertEqual(sap["rec_qty"], 0)

	def test_missing_pr_foreign_is_unavailable_not_zero(self):
		sap = calculate_sap(730, 10, stock=100, open_po=50, open_so=30, abc_class="A", grace_days=20)
		for metric in ("to_reorder", "rec_qty", "missing_so", "to_reorder_final"):
			self.assertIsNone(sap[metric])
			self.assertIn(metric, sap["unavailable"])
		self.assertEqual(sap["miss_qty"], 120)

	def test_missing_grace_days(self):
		sap = calculate_sap(730, 10, stock=0, open_po=0, open_so=0, abc_class="A", pr_foreign=0)
		self.assertIsNone(sap["reorder"])
		self.assertIsNone(sap["max"])
		self.assertIsNone(sap["to_reorder"])
		self.assertEqual(sap["safety"], 90)
		self.assertIsNotNone(sap["missing_so"])

	def test_min_unavailable_without_confirmed_rule(self):
		sap = calculate_sap(730, 10, stock=0, open_po=0, open_so=0, abc_class="A", grace_days=20, pr_foreign=0)
		self.assertIsNone(sap["min"])
		self.assertIn("min", sap["unavailable"])

	def test_no_selling_months(self):
		sap = calculate_sap(0, 0, stock=0, open_po=0, open_so=0, abc_class=NON_MOVING_CLASS)
		self.assertIsNone(sap["avg_cont"])
		self.assertEqual(sap["safety"], 0)


def buckets(**values):
	result = dict.fromkeys(PO_BUCKETS, 0)
	result.update(values)
	return result


class TestPurchaseOrderBuckets(unittest.TestCase):
	def test_split(self):
		today, horizon_end = date(2026, 10, 29), date(2026, 12, 28)
		lines = [(date(2026, 10, 1), 5), (date(2026, 10, 29), 7), (date(2026, 12, 28), 11), (date(2027, 1, 1), 13), (None, 17)]
		self.assertEqual(
			split_purchase_orders(lines, today, horizon_end), buckets(late=5, due=18, beyond=13, undated=17)
		)

	def test_late_tolerance(self):
		today, horizon_end = date(2026, 10, 29), date(2026, 12, 28)
		lines = [(date(2026, 9, 29), 3), (date(2026, 9, 28), 4)]
		self.assertEqual(
			split_purchase_orders(lines, today, horizon_end, late_tolerance_days=30), buckets(late=3, overdue=4)
		)

	def test_in_transit_uses_arrival_date(self):
		today, horizon_end = date(2026, 10, 29), date(2026, 12, 28)
		lines = [
			(date(2026, 11, 5), 10, True),
			(date(2026, 8, 1), 20, True),  # arrival passed: still counted, never overdue
			(date(2027, 2, 1), 30, True),
		]
		self.assertEqual(
			split_purchase_orders(lines, today, horizon_end, late_tolerance_days=30),
			buckets(in_transit=10, in_transit_late=20, beyond=30),
		)


class TestProposed(unittest.TestCase):
	def test_pending_requests_subtracted(self):
		base = proposed()
		self.assertEqual(base["suggested_purchase"], 270)

		partly = proposed(pending_requests=100)
		self.assertEqual(partly["suggested_purchase"], 170)
		self.assertIn("PENDING_MR_SUBTRACTED", partly["warnings"])
		# not supply yet: the risk is unchanged
		self.assertEqual(partly["stockout_risk"], base["stockout_risk"])

		covered = proposed(pending_requests=500)
		self.assertEqual(covered["suggested_purchase"], 0)
		# MOQ applies only to what is still to be requested
		self.assertEqual(proposed(pending_requests=500, min_order_qty=50)["suggested_purchase"], 0)
		self.assertEqual(proposed(pending_requests=250, min_order_qty=50)["suggested_purchase"], 50)

		self.assertNotIn("PENDING_MR_SUBTRACTED", proposed(stock=1000, pending_requests=10)["warnings"])

	def test_formulas(self):
		# AMS = 730/12; ADS = 2/day; lead 60 + review 30 = 90 day horizon.
		result = proposed(stock=50, po_buckets={"late": 10, "due": 20, "beyond": 40, "undated": 5})
		self.assertAlmostEqual(result["ams"], 730 / 12)
		self.assertAlmostEqual(result["ads"], 2)
		self.assertEqual(result["planning_horizon_days"], 90)
		self.assertEqual(result["safety_stock"], 90)
		self.assertEqual(result["forecast_demand"], 180)
		self.assertEqual(result["target_stock"], 270)
		self.assertEqual(result["reorder_level"], 210)
		self.assertEqual(result["open_po_supply"], 30)
		self.assertEqual(result["inventory_position"], 80)
		self.assertEqual(result["baseline_demand"], 180)
		self.assertEqual(result["purchase_need"], 190)
		self.assertEqual(result["suggested_purchase"], 190)
		self.assertTrue(result["below_reorder_level"])
		self.assertEqual(result["stockout_risk"], "High")
		for warning in ("LATE_PO", "UNDATED_PO", "PO_BEYOND_HORIZON"):
			self.assertIn(warning, result["warnings"])

	def test_forecast_and_open_so_not_double_counted(self):
		result = proposed(open_so=100)
		self.assertEqual(result["baseline_demand"], 180)
		self.assertEqual(result["purchase_need"], 270)
		result = proposed(open_so=500)
		self.assertEqual(result["baseline_demand"], 500)
		self.assertEqual(result["purchase_need"], 590)

	def test_non_moving_without_sales_order_gets_no_purchase(self):
		result = proposed(net_sales=50, is_non_moving=True)
		self.assertEqual(result["forecast_demand"], 0)
		self.assertEqual(result["safety_stock"], 0)
		self.assertEqual(result["suggested_purchase"], 0)
		self.assertIn("NON_MOVING", result["warnings"])

	def test_non_moving_firm_sales_order_is_planned(self):
		result = proposed(net_sales=0, is_non_moving=True, stock=10, open_so=25)
		self.assertEqual(result["suggested_purchase"], 15)

	def test_lead_time_fallback_is_flagged(self):
		result = proposed(lead_time_days=0)
		self.assertTrue(result["lead_time_is_fallback"])
		self.assertIn("LEAD_TIME_FALLBACK", result["warnings"])
		self.assertEqual(result["planning_horizon_days"], 30)

	def test_moq_adjustment(self):
		result = proposed(stock=260, min_order_qty=100)
		self.assertEqual(result["suggested_before_moq"], 10)
		self.assertEqual(result["suggested_purchase"], 100)
		self.assertEqual(result["moq_adjustment"], 90)
		self.assertIn("MOQ_APPLIED", result["warnings"])

	def test_moq_not_applied_without_need(self):
		result = proposed(stock=1000, min_order_qty=100)
		self.assertEqual(result["suggested_purchase"], 0)
		self.assertEqual(result["moq_adjustment"], 0)
		self.assertEqual(result["stockout_risk"], "Low")

	def test_new_item_uses_eligible_months(self):
		result = proposed(net_sales=120, eligible_months=3)
		self.assertAlmostEqual(result["ams"], 40)
		self.assertIn("NEW_ITEM", result["warnings"])

	def test_negative_net_sales_floor(self):
		result = proposed(net_sales=-24)
		self.assertEqual(result["ads"], 0)
		self.assertIn("NEGATIVE_NET_SALES", result["warnings"])

	def test_medium_risk_when_safety_stock_is_used(self):
		result = proposed(stock=200)
		self.assertEqual(result["stockout_risk"], "Medium")

	def test_overdue_po_is_not_supply(self):
		result = proposed(stock=50, po_buckets=buckets(late=10, overdue=100, in_transit=5, in_transit_late=7))
		self.assertEqual(result["open_po_supply"], 22)
		self.assertIn("OVERDUE_PO", result["warnings"])
		self.assertIn("ETA_PASSED", result["warnings"])

	def test_order_multiple(self):
		self.assertEqual(round_to_multiple(37, 12), 48)
		self.assertEqual(round_to_multiple(48, 12), 48)
		self.assertEqual(round_to_multiple(0, 12), 0)
		self.assertEqual(round_to_multiple(37, 0), 37)
		# need 10, MOQ 20, multiple 12 -> 24
		result = proposed(stock=260, min_order_qty=20, order_multiple=12)
		self.assertEqual(result["suggested_purchase"], 24)
		self.assertEqual(result["moq_adjustment"], 10)
		self.assertEqual(result["multiple_adjustment"], 4)
		self.assertIn("ORDER_MULTIPLE_APPLIED", result["warnings"])

	def test_default_lead_time_is_flagged(self):
		result = proposed(lead_time_days=45, lead_time_source=SOURCE_DEFAULT)
		self.assertIn("LEAD_TIME_DEFAULT", result["warnings"])
		self.assertEqual(result["planning_horizon_days"], 75)

	def test_approved_parameters_replace_calculated(self):
		result = proposed(stock=50, approved={"safety_stock": 100, "reorder_level": 150, "target_stock": 300})
		self.assertEqual(result["parameter_source"], "Approved")
		self.assertEqual(result["calculated_target_stock"], 270)
		self.assertEqual(result["target_stock"], 300)
		self.assertEqual(result["purchase_need"], 250)
		self.assertEqual(result["baseline_demand"], 200)
		self.assertIn("APPROVED_PARAMETERS", result["warnings"])

	def test_future_sales_orders_are_informational(self):
		result = proposed(open_so=0, open_so_future=999)
		self.assertEqual(result["baseline_demand"], 180)
		self.assertIn("FUTURE_SALES_ORDERS", result["warnings"])

	def test_stockout_exclusion_is_not_a_new_item(self):
		result = proposed(net_sales=600, eligible_months=10, stockout_months_excluded=2)
		self.assertAlmostEqual(result["ams"], 60)
		self.assertNotIn("NEW_ITEM", result["warnings"])
		self.assertIn("STOCKOUT_MONTHS_EXCLUDED", result["warnings"])


class TestStockout(unittest.TestCase):
	def test_opening_balance(self):
		self.assertEqual(opening_balance(10, [(date(2026, 9, 1), -5), (date(2026, 9, 2), 20)]), -5)

	def test_days_out_per_month(self):
		# 0 on hand until 10 Sep, then 5 in, sold out on 21 Sep.
		movements = [(date(2026, 9, 10), 5), (date(2026, 9, 21), -5), (date(2026, 10, 3), 8)]
		days = count_stockout_days(0, movements, ["2026-09", "2026-10"])
		self.assertEqual(days["2026-09"], (9 + 10, 30))
		self.assertEqual(days["2026-10"], (2, 31))
		self.assertEqual(stockout_months(days, 0.5), {"2026-09"})

	def test_movements_before_period_roll_into_opening(self):
		days = count_stockout_days(0, [(date(2026, 8, 15), 3)], ["2026-09"])
		self.assertEqual(days["2026-09"], (0, 30))

	def test_last_day_caps_the_count(self):
		days = count_stockout_days(0, [], ["2026-09"], last_day=date(2026, 9, 10))
		self.assertEqual(days["2026-09"], (10, 10))

	def test_select_demand_months(self):
		sales = {"2026-07": 100, "2026-08": 5, "2026-09": 0}
		used, net, excluded, all_out = select_demand_months(["2026-07", "2026-08", "2026-09"], {"2026-08", "2026-09"}, sales)
		self.assertEqual((used, net, excluded, all_out), (["2026-07"], 100, ["2026-08", "2026-09"], False))

	def test_all_months_stockout_keeps_them(self):
		used, net, excluded, all_out = select_demand_months(["2026-08", "2026-09"], {"2026-08", "2026-09"}, {"2026-08": 4})
		self.assertEqual((used, net, excluded, all_out), (["2026-08", "2026-09"], 4, [], True))


class TestLeadTime(unittest.TestCase):
	def test_summary_by_supplier_and_brand(self):
		samples = [("S1", "B1", 30), ("S1", "B1", 40), ("S1", "B1", 50), ("S1", "B2", 90), ("S1", None, -3)]
		result = summarise_lead_times(samples, min_samples=3)
		self.assertEqual(result[("S1", "B1")], {"lead_time_days": 40, "p90_lead_time_days": 50, "sample_count": 3})
		self.assertEqual(result[("S1", None)]["sample_count"], 4)
		self.assertEqual(result[("S1", None)]["lead_time_days"], 45)
		self.assertNotIn(("S1", "B2"), result)

	def test_effective_entry(self):
		entries = [
			{"from_date": date(2026, 1, 1), "lead_time_days": 30, "idx": 1},
			{"from_date": date(2026, 6, 1), "lead_time_days": 50, "idx": 2},
		]
		self.assertEqual(effective_entry(entries, date(2026, 5, 31))["lead_time_days"], 30)
		self.assertEqual(effective_entry(entries, date(2026, 6, 1))["lead_time_days"], 50)
		self.assertIsNone(effective_entry(entries, date(2025, 12, 31)))

	def test_resolution_order(self):
		profiles = {("S1", "B1"): 40, ("S1", None): 50, (None, "B1"): 60}
		self.assertEqual(resolve_lead_time(10, "S1", "B1", profiles, 90)[:2], (10, SOURCE_ITEM))
		self.assertEqual(resolve_lead_time(0, "S1", "B1", profiles, 90)[:2], (40, SOURCE_PROFILE))
		self.assertEqual(resolve_lead_time(0, "S1", "B9", profiles, 90)[:2], (50, SOURCE_PROFILE))
		self.assertEqual(resolve_lead_time(0, None, "B1", profiles, 90)[:2], (60, SOURCE_PROFILE))
		self.assertEqual(resolve_lead_time(0, "S2", "B2", profiles, 90)[:2], (90, SOURCE_DEFAULT))
		self.assertEqual(resolve_lead_time(0, "S2", "B2", profiles, 0), (None, None, None))

	def test_supplier_resolution(self):
		self.assertEqual(resolve_supplier("A", "B", "C"), ("A", SUPPLIER_ITEM_DEFAULT))
		self.assertEqual(resolve_supplier(None, None, "C"), ("C", SUPPLIER_LAST_PO))
		self.assertEqual(resolve_supplier(None, None, None), (None, None))

	def test_blanket_order_supplier_comes_first(self):
		self.assertEqual(resolve_supplier("A", "B", "C", "BO"), ("BO", SUPPLIER_BLANKET_ORDER))
		self.assertEqual(resolve_supplier("A", None, None, None), ("A", SUPPLIER_ITEM_DEFAULT))

	def test_pick_blanket_order(self):
		from datetime import date as d

		first = {"blanket_order": "BO-1", "remaining": 10, "to_date": d(2026, 6, 30)}
		later = {"blanket_order": "BO-2", "remaining": 50, "to_date": d(2026, 12, 31)}
		used_up = {"blanket_order": "BO-0", "remaining": 0, "to_date": d(2026, 3, 31)}
		self.assertEqual(pick_blanket_order([later, used_up, first])["blanket_order"], "BO-1")
		self.assertIsNone(pick_blanket_order([used_up]))
		self.assertIsNone(pick_blanket_order([]))

	def test_history_supplier_by_quantity(self):
		# a local supplier bought from recently but little loses to the main source
		candidates = [
			("Local", 5, date(2026, 9, 1), 1),
			("Hikvision", 400, date(2026, 6, 1), 3),
		]
		self.assertEqual(pick_history_supplier(candidates), "Hikvision")
		# equal quantity: the latest order wins, then more orders
		self.assertEqual(
			pick_history_supplier([("A", 10, date(2026, 1, 1), 5), ("B", 10, date(2026, 2, 1), 1)]), "B"
		)
		self.assertEqual(
			pick_history_supplier([("A", 10, date(2026, 2, 1), 2), ("B", 10, date(2026, 2, 1), 1)]), "A"
		)
		self.assertIsNone(pick_history_supplier([]))


if __name__ == "__main__":
	unittest.main()

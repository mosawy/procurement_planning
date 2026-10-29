# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Proposed reorder planning calculations.

Pure functions only (no database access) so they can be tested in isolation.
All quantities are in stock UOM.
"""

from procurement_planning.planning.sap_calculations import ceil_qty

# Lead time used when neither the Item, a Lead Time Profile nor the company
# default gives one. Every item that uses it carries LEAD_TIME_FALLBACK.
FALLBACK_LEAD_TIME_DAYS = 0

# POs late by up to this many days still count as supply; POs later than that
# are reported as overdue and are not counted. Overridden by company settings.
DEFAULT_LATE_PO_TOLERANCE_DAYS = 30

PARAMETER_SOURCE_CALCULATED = "Calculated"
PARAMETER_SOURCE_APPROVED = "Approved"

WARNING_LABELS = {
	"LEAD_TIME_FALLBACK": "No lead time from the Item, a Lead Time Profile or the company default: {fallback} days used",
	"LEAD_TIME_DEFAULT": "Lead time is the company default, not maintained for this item, supplier or brand",
	"NO_SALES_HISTORY": "No net sales in the analysis period",
	"NEW_ITEM": "New item: average uses only the months since the item started",
	"NO_ELIGIBLE_HISTORY": "New item without a completed month of history",
	"NEGATIVE_NET_SALES": "Returns exceed deliveries in the analysis period",
	"NON_MOVING": "Non-moving: no forecast-based purchase, firm Sales Orders only",
	"STOCKOUT_MONTHS_EXCLUDED": "Months mostly out of stock were left out of the average",
	"ALL_MONTHS_STOCKOUT": "Item was out of stock in every month: average uses those months anyway",
	"LATE_PO": "Late PO quantity within the tolerance counted as supply",
	"OVERDUE_PO": "PO quantity late beyond the tolerance not counted as supply",
	"IN_TRANSIT": "Shipped quantity counted as supply at its shipment arrival date",
	"ETA_PASSED": "Shipped quantity whose arrival date has passed counted as supply",
	"UNDATED_PO": "PO quantity without expected date not counted as supply",
	"PO_BEYOND_HORIZON": "PO quantity due after the planning horizon not counted as supply",
	"FUTURE_SALES_ORDERS": "Sales Order quantity due after the planning horizon not counted as demand",
	"MOQ_APPLIED": "Raised to the Item Minimum Order Qty",
	"ORDER_MULTIPLE_APPLIED": "Rounded up to the purchase order multiple",
	"APPROVED_PARAMETERS": "Safety stock, reorder level and target stock come from the approved parameter run",
	"NO_SUPPLIER": "No supplier found for the item",
	"SUPPLIER_INFERRED": "Supplier inferred from the latest Purchase Order, not maintained on the item",
}

# Warnings that mean planning data is missing rather than informational.
MISSING_DATA_WARNINGS = ("LEAD_TIME_FALLBACK", "LEAD_TIME_DEFAULT", "UNDATED_PO", "NO_ELIGIBLE_HISTORY")

PO_BUCKETS = ("late", "overdue", "due", "beyond", "undated", "in_transit", "in_transit_late")
SUPPLY_BUCKETS = ("late", "due", "in_transit", "in_transit_late")


def split_purchase_orders(po_lines, analysis_date, horizon_end, late_tolerance_days=None):
	"""Bucket open PO quantities.

	po_lines: [(expected_date or None, qty)] or [(expected_date or None, qty, in_transit)].
	A line in transit carries its shipment arrival date; any other line carries the
	PO expected date.

	- in_transit: shipped, arriving by the horizon end
	- in_transit_late: shipped, arrival date already passed (still counted)
	- due: not shipped, expected between the analysis date and the horizon end
	- late: not shipped, expected before the analysis date, within the tolerance
	- overdue: not shipped, later than the tolerance (not counted)
	- beyond: expected after the horizon end (not counted)
	- undated: no expected date (not counted)

	late_tolerance_days None means every late line counts as late.
	"""
	buckets = dict.fromkeys(PO_BUCKETS, 0)
	for line in po_lines:
		expected_date, qty = line[0], line[1]
		in_transit = bool(line[2]) if len(line) > 2 else False

		if expected_date is None:
			buckets["undated"] += qty
		elif expected_date > horizon_end:
			buckets["beyond"] += qty
		elif in_transit:
			buckets["in_transit_late" if expected_date < analysis_date else "in_transit"] += qty
		elif expected_date >= analysis_date:
			buckets["due"] += qty
		elif late_tolerance_days is None or (analysis_date - expected_date).days <= late_tolerance_days:
			buckets["late"] += qty
		else:
			buckets["overdue"] += qty
	return buckets


def round_to_multiple(qty, multiple):
	"""Round a positive quantity up to the next multiple; 0 stays 0."""
	if not qty or not multiple or multiple <= 0:
		return qty
	return ceil_qty(qty / multiple) * multiple


def calculate_proposed(
	net_sales,
	eligible_months,
	analysis_months,
	is_non_moving,
	lead_time_days,
	safety_stock_days,
	review_period_days,
	stock,
	open_so,
	po_buckets,
	min_order_qty,
	order_multiple=0,
	lead_time_source=None,
	open_so_future=0,
	stockout_months_excluded=0,
	all_months_stockout=False,
	approved=None,
):
	"""Proposed planning values.

	po_buckets comes from split_purchase_orders(). open_so is the Sales Order
	quantity due within the planning horizon; open_so_future is shown only.
	approved, when given, is {"safety_stock", "reorder_level", "target_stock"}
	from an approved parameter run and replaces the calculated parameters.
	"""
	warnings = []

	if eligible_months > 0:
		ams = net_sales / eligible_months
	else:
		ams = 0
		warnings.append("NO_ELIGIBLE_HISTORY")

	if 0 < eligible_months + stockout_months_excluded < analysis_months:
		warnings.append("NEW_ITEM")
	if stockout_months_excluded:
		warnings.append("STOCKOUT_MONTHS_EXCLUDED")
	if all_months_stockout and net_sales > 0:
		warnings.append("ALL_MONTHS_STOCKOUT")
	if not net_sales:
		warnings.append("NO_SALES_HISTORY")
	elif net_sales < 0:
		warnings.append("NEGATIVE_NET_SALES")

	ads = max(0, ams * 12 / 365)
	# Non-moving items get no forecast; only firm Sales Order demand is planned.
	planning_ads = 0 if is_non_moving else ads
	if is_non_moving:
		warnings.append("NON_MOVING")

	if lead_time_days and lead_time_days > 0:
		lead_time = int(lead_time_days)
		if lead_time_source == "Default":
			warnings.append("LEAD_TIME_DEFAULT")
	else:
		lead_time = FALLBACK_LEAD_TIME_DAYS
		lead_time_source = "Fallback"
		warnings.append("LEAD_TIME_FALLBACK")

	horizon = lead_time + review_period_days
	forecast_demand = ceil_qty(planning_ads * horizon)

	calculated_safety = ceil_qty(planning_ads * safety_stock_days)
	calculated = {
		"safety_stock": calculated_safety,
		"reorder_level": ceil_qty(planning_ads * lead_time) + calculated_safety,
		"target_stock": forecast_demand + calculated_safety,
	}
	if approved:
		parameters = {key: approved.get(key, calculated[key]) for key in calculated}
		parameter_source = PARAMETER_SOURCE_APPROVED
		warnings.append("APPROVED_PARAMETERS")
	else:
		parameters = calculated
		parameter_source = PARAMETER_SOURCE_CALCULATED

	safety_stock = parameters["safety_stock"]
	reorder_level = parameters["reorder_level"]
	target_stock = parameters["target_stock"]

	supply = sum(po_buckets.get(bucket, 0) for bucket in SUPPLY_BUCKETS)
	for bucket, warning in (
		("late", "LATE_PO"),
		("overdue", "OVERDUE_PO"),
		("in_transit", "IN_TRANSIT"),
		("in_transit_late", "ETA_PASSED"),
		("undated", "UNDATED_PO"),
		("beyond", "PO_BEYOND_HORIZON"),
	):
		if po_buckets.get(bucket):
			warnings.append(warning)
	if open_so_future:
		warnings.append("FUTURE_SALES_ORDERS")

	inventory_position = stock + supply
	# Forecast already covers ordinary customer demand: take the larger, never the sum.
	# Target stock = cycle demand + safety stock, so the need is the gap to the
	# larger of the target and firm orders plus safety stock.
	required_stock = max(target_stock, open_so + safety_stock)
	baseline_demand = required_stock - safety_stock
	purchase_need = required_stock - inventory_position

	suggested_before_moq = max(0, ceil_qty(purchase_need))
	suggested_purchase = suggested_before_moq
	if suggested_purchase and min_order_qty and suggested_purchase < min_order_qty:
		suggested_purchase = min_order_qty
		warnings.append("MOQ_APPLIED")
	moq_adjustment = suggested_purchase - suggested_before_moq

	before_multiple = suggested_purchase
	suggested_purchase = round_to_multiple(suggested_purchase, order_multiple)
	if suggested_purchase != before_multiple:
		warnings.append("ORDER_MULTIPLE_APPLIED")
	multiple_adjustment = suggested_purchase - before_multiple

	if open_so > stock or inventory_position < baseline_demand:
		stockout_risk = "High"
	elif inventory_position < required_stock:
		stockout_risk = "Medium"
	else:
		stockout_risk = "Low"

	return {
		"ams": ams,
		"ads": ads,
		"planning_ads": planning_ads,
		"lead_time_days": lead_time,
		"lead_time_source": lead_time_source,
		"lead_time_is_fallback": "LEAD_TIME_FALLBACK" in warnings,
		"planning_horizon_days": horizon,
		"parameter_source": parameter_source,
		"calculated_safety_stock": calculated["safety_stock"],
		"calculated_reorder_level": calculated["reorder_level"],
		"calculated_target_stock": calculated["target_stock"],
		"safety_stock": safety_stock,
		"forecast_demand": forecast_demand,
		"open_so_demand": open_so,
		"open_so_future": open_so_future,
		"baseline_demand": baseline_demand,
		"target_stock": target_stock,
		"reorder_level": reorder_level,
		"open_po_supply": supply,
		"inventory_position": inventory_position,
		"below_reorder_level": reorder_level > 0 and inventory_position < reorder_level,
		"required_stock": required_stock,
		"purchase_need": purchase_need,
		"suggested_before_moq": suggested_before_moq,
		"moq_adjustment": moq_adjustment,
		"multiple_adjustment": multiple_adjustment,
		"suggested_purchase": suggested_purchase,
		"stockout_risk": stockout_risk,
		"warnings": warnings,
	}

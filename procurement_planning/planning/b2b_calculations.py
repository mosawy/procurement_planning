# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Back-to-back costing and promise calculations.

Pure functions only (no database access). Costs are per stock UOM unit in the
company currency unless stated otherwise.
"""

import math
from datetime import date, timedelta

EXCESS_CUSTOMER_BEARS = "Customer Bears Excess"
EXCESS_TO_STOCK = "Excess to Stock"

PRIORITY_URGENT = "Urgent"


def estimated_landed_cost(unit_cost, landed_cost_percent, fx_buffer_percent=0, foreign_currency=False):
	"""Supplier unit cost (company currency) plus freight/customs/clearance and,
	for a foreign currency, a buffer against exchange rate movement."""
	uplift = (landed_cost_percent or 0) + ((fx_buffer_percent or 0) if foreign_currency else 0)
	return (unit_cost or 0) * (1 + uplift / 100)


def purchase_quantity(required_qty, min_order_qty=0):
	"""(purchase_qty, excess_qty): a supplier minimum order above the need is bought in full."""
	required_qty = required_qty or 0
	purchase = max(required_qty, min_order_qty or 0)
	return purchase, purchase - required_qty


def customer_unit_cost(landed_cost, required_qty, purchase_qty, excess_pricing):
	"""Unit cost the customer price is built on.

	When the customer bears the excess, the cost of everything bought is spread
	over the customer's quantity; otherwise the excess goes to stock at cost.
	"""
	if excess_pricing == EXCESS_CUSTOMER_BEARS and required_qty:
		return landed_cost * purchase_qty / required_qty
	return landed_cost


def selling_rate(unit_cost, margin_percent):
	"""Rate that gives margin_percent of the selling price (gross margin, not markup)."""
	margin = (margin_percent or 0) / 100
	if margin >= 1:
		raise ValueError("Margin must be below 100%")
	return unit_cost / (1 - margin)


def margin_percent(rate, unit_cost):
	if not rate:
		return 0
	return (rate - unit_cost) / rate * 100


def offer_lead_time(quotation_date, lead_time_days=0, expected_delivery_date=None):
	"""Lead time of a supplier offer in days: its stated lead time, else the days
	to its expected delivery date."""
	if lead_time_days and lead_time_days > 0:
		return int(lead_time_days)
	if expected_delivery_date and quotation_date:
		return max(0, (expected_delivery_date - quotation_date).days)
	return None


def promised_date(start_date, lead_time_days, buffer_days=0):
	"""Date to promise the customer: start + supplier lead time + internal buffer."""
	if lead_time_days is None:
		return None
	return start_date + timedelta(days=int(lead_time_days) + int(buffer_days or 0))


def rank_offers(offers, priority=None):
	"""Offers sorted best first.

	offers: dicts with "customer_unit_cost" and "promised_date" (either may be None).
	Urgent requests rank by the earliest promise, then cost; any other by cost,
	then the earliest promise. Expired offers always go last.
	"""

	def date_key(offer):
		return offer.get("promised_date") or date.max

	def cost_key(offer):
		cost = offer.get("customer_unit_cost")
		return cost if cost is not None else math.inf

	def key(offer):
		expired = 1 if offer.get("expired") else 0
		if priority == PRIORITY_URGENT:
			return (expired, date_key(offer), cost_key(offer))
		return (expired, cost_key(offer), date_key(offer))

	return sorted(offers, key=key)


def weighted_average_cost(lines):
	"""(total_qty, weighted unit cost) of [(qty, unit_cost)]; unit cost None when no quantity."""
	total_qty = sum(qty for qty, _cost in lines)
	if not total_qty:
		return 0, None
	return total_qty, sum(qty * cost for qty, cost in lines) / total_qty


def back_to_back_stage(ordered_qty, shipped_qty, received_qty, delivered_qty, required_qty, has_draft_po=False):
	"""Where a back-to-back Sales Order line stands, from the customer's point of view."""
	if required_qty and delivered_qty >= required_qty:
		return "Delivered"
	if required_qty and received_qty >= required_qty:
		return "Received"
	if received_qty > 0:
		return "Partly Received"
	if shipped_qty > 0:
		return "Shipped"
	if ordered_qty > 0:
		return "Ordered"
	if has_draft_po:
		return "PO Draft"
	return "Not Ordered"


def offer_expired(valid_till, on_date):
	return bool(valid_till and valid_till < on_date)


def evaluate_offer(
	offer,
	required_qty,
	start_date,
	landed_cost_percent=0,
	fx_buffer_percent=0,
	buffer_days=0,
	excess_pricing=EXCESS_TO_STOCK,
):
	"""Cost, quantity and promise of one supplier offer for one customer line.

	offer: unit_cost (company currency per stock UOM), min_order_qty (stock UOM),
	foreign_currency, quotation_date, lead_time_days, expected_delivery_date,
	valid_till. required_qty is in stock UOM.
	"""
	landed = estimated_landed_cost(
		offer.get("unit_cost"),
		landed_cost_percent,
		fx_buffer_percent,
		bool(offer.get("foreign_currency")),
	)
	purchase, excess = purchase_quantity(required_qty, offer.get("min_order_qty"))
	lead_time = offer_lead_time(
		offer.get("quotation_date"), offer.get("lead_time_days"), offer.get("expected_delivery_date")
	)
	return {
		"landed_cost": landed,
		"purchase_qty": purchase,
		"excess_qty": excess,
		"excess_pricing": excess_pricing,
		"customer_unit_cost": customer_unit_cost(landed, required_qty, purchase, excess_pricing),
		"lead_time_days": lead_time,
		"promised_date": promised_date(start_date, lead_time, buffer_days),
		"expired": offer_expired(offer.get("valid_till"), start_date),
	}


def quotation_rate(unit_cost, margin_percent_value, conversion_factor=1, conversion_rate=1):
	"""Selling rate per quotation UOM in the quotation currency, from a unit cost
	per stock UOM in the company currency."""
	rate = selling_rate(unit_cost, margin_percent_value) * (conversion_factor or 1)
	return rate / (conversion_rate or 1)


def sourcing_status(lines):
	"""Quotation sourcing status from its lines (dicts with needs_sourcing and supplier_quotation_item)."""
	sourcing = [line for line in lines if line.get("needs_sourcing")]
	if not sourcing:
		return ""
	if all(line.get("supplier_quotation_item") for line in sourcing):
		return "Ready for Pricing"
	return "Pending Sourcing"


def purchase_order_split(customer_qty, min_order_qty=0):
	"""(customer_qty, excess_qty) for the two Purchase Order lines of a
	back-to-back Sales Order line, in the same UOM as the inputs."""
	purchase, excess = purchase_quantity(customer_qty, min_order_qty)
	return purchase - excess, excess

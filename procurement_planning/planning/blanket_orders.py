# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Link Purchase Order lines to the purchasing agreement (Blanket Order) they
are bought under, so ERPNext counts them against the agreement."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from procurement_planning.planning import data_sources
from procurement_planning.planning.lead_time import pick_blanket_order


def link_purchase_order(doc, method=None):
	"""Purchase Order validate hook.

	A new line (not saved yet) for an item that the PO's supplier has an active,
	submitted Purchasing Blanket Order for is set "Against Blanket Order", so
	ERPNext's own ordered quantity on the agreement goes up when the PO is
	submitted. Saved lines are left as the user set them, so unticking a line
	sticks. A line that needs more than what is left on the agreement (plus
	the Buying Settings allowance) is not linked, and the user is told.

	ERPNext draws an agreement down by every submitted line whose blanket_order
	is set, ticked or not (BlanketOrder.update_ordered_qty), so a line that is
	not Against Blanket Order has its blanket_order cleared.

	Runs on drafts, and on an order submitted without being saved first; a
	saved draft being submitted keeps what its last save decided.
	"""
	if not doc.supplier or doc.docstatus == 2 or (doc.docstatus == 1 and not doc.is_new()):
		return

	for row in doc.items:
		if row.blanket_order and not row.against_blanket_order and not _is_new_line(doc, row):
			row.blanket_order = None
			row.blanket_order_rate = 0

	new_lines = [
		row for row in doc.items if row.item_code and not row.against_blanket_order and _is_new_line(doc, row)
	]
	if not new_lines:
		return

	agreements = data_sources.get_active_blanket_orders(
		doc.company,
		getdate(doc.transaction_date),
		supplier=doc.supplier,
		item_codes=list({row.item_code for row in new_lines}),
	)
	# A line made from a Material Request carries the agreement it was requested
	# under (same fieldname). Keep it only if it belongs to this PO's supplier and
	# is still active; otherwise ERPNext would count the line against it anyway.
	for row in new_lines:
		if row.blanket_order and row.blanket_order not in {
			c["blanket_order"] for c in agreements.get(row.item_code, [])
		}:
			row.blanket_order = None
			row.blanket_order_rate = 0

	if not agreements:
		return

	allowance = flt(frappe.db.get_single_value("Buying Settings", "blanket_order_allowance")) / 100

	# Quantity this PO already takes from each agreement line.
	taken = {}
	for row in doc.items:
		if row.blanket_order and row.against_blanket_order:
			key = (row.blanket_order, row.item_code)
			taken[key] = taken.get(key, 0) + _agreement_qty(row)

	linked, too_large, other_price = [], [], []
	for row in new_lines:
		candidates = [
			dict(c, remaining=c["remaining"] - taken.get((c["blanket_order"], row.item_code), 0))
			for c in agreements.get(row.item_code, [])
		]
		if row.blanket_order:
			# Requested under this agreement: use it if it still has quantity left.
			candidates = [c for c in candidates if c["blanket_order"] == row.blanket_order] or candidates
		agreement = pick_blanket_order(candidates)
		if not agreement:
			row.blanket_order = None
			row.blanket_order_rate = 0
			continue

		qty = _agreement_qty(row)
		if qty > agreement["remaining"] * (1 + allowance) + 1e-9:
			row.blanket_order = None
			row.blanket_order_rate = 0
			too_large.append(
				_("Row {0}: {1} needs {2}, only {3} left on {4}").format(
					row.idx, row.item_code, qty, agreement["remaining"], agreement["blanket_order"]
				)
			)
			continue

		row.against_blanket_order = 1
		row.blanket_order = agreement["blanket_order"]
		row.blanket_order_rate = agreement["rate"]
		key = (agreement["blanket_order"], row.item_code)
		taken[key] = taken.get(key, 0) + qty
		linked.append(row.idx)
		if agreement["rate"] and abs(flt(row.rate) - agreement["rate"]) > 0.005:
			other_price.append(
				_("Row {0}: {1} rate {2}, agreed {3}").format(row.idx, row.item_code, row.rate, agreement["rate"])
			)

	messages = []
	if linked:
		messages.append(
			_("Rows {0} linked to their Blanket Order; they count against it when this order is submitted.").format(
				", ".join(str(idx) for idx in linked)
			)
		)
	if other_price:
		messages.append(_("Rate differs from the agreed price:") + "<br>" + "<br>".join(other_price))
	if too_large:
		messages.append(
			_("Not linked, more than what is left on the agreement:") + "<br>" + "<br>".join(too_large)
		)
	if messages:
		frappe.msgprint("<br><br>".join(messages), title=_("Blanket Orders"), indicator="blue")


def _is_new_line(doc, row):
	"""Line not saved yet. Frappe keeps __islocal on a new row until it is
	written, also after naming it before validate (browser save, server insert,
	rows appended to a saved order)."""
	return bool(doc.is_new() or row.get("__islocal") or not row.name)


def _agreement_qty(row):
	"""Quantity a line takes from an agreement, as both ERPNext checks see it:
	the draw-down counts stock_qty, validate_against_blanket_order compares qty
	(order UOM) with the stock UOM quantity left. Taking the larger keeps a
	linked line from being rejected later when the order UOM is smaller than the
	stock UOM (conversion factor below 1)."""
	stock_qty = flt(row.stock_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1)
	return max(stock_qty, flt(row.qty))

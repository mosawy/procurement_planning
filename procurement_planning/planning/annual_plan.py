# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Annual purchase plan as draft Purchasing Blanket Orders, one per supplier."""

import math

import frappe
from frappe import _
from frappe.utils import flt, getdate, month_diff

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning.parameter_run import LINE, RUN


@frappe.whitelist()
def create_annual_plan(run, from_date, to_date):
	"""Draft Blanket Orders from an approved run.

	Planned quantity per item = average monthly sales × months in the period,
	rounded up, at the Item's last purchase rate. Suppliers that already have a
	Purchasing Blanket Order overlapping the period are skipped.
	"""
	frappe.only_for(ALLOWED_ROLES)
	if not frappe.has_permission("Blanket Order", "create"):
		frappe.throw(_("Not permitted to create Blanket Orders"), frappe.PermissionError)

	run_doc = frappe.get_doc(RUN, run)
	if run_doc.docstatus != 1:
		frappe.throw(_("Only an approved run can create an annual plan"))

	from_date, to_date = getdate(from_date), getdate(to_date)
	if to_date < from_date:
		frappe.throw(_("To Date cannot be before From Date"))
	months = month_diff(to_date, from_date)

	lines = frappe.get_all(
		LINE,
		filters={"run": run, "supplier": ("is", "set"), "ams": (">", 0)},
		fields=["item_code", "supplier", "ams"],
		order_by="supplier, item_code",
	)
	no_supplier = frappe.db.count(LINE, {"run": run, "supplier": ("is", "not set"), "ams": (">", 0)})

	by_supplier = {}
	for line in lines:
		by_supplier.setdefault(line.supplier, []).append(line)

	rates = dict(
		frappe.get_all(
			"Item",
			filters={"name": ("in", [line.item_code for line in lines] or [""])},
			fields=["name", "last_purchase_rate"],
			as_list=True,
		)
	)

	created, skipped = [], []
	for supplier, supplier_lines in by_supplier.items():
		existing = _overlapping_blanket_order(run_doc.company, supplier, from_date, to_date)
		if existing:
			skipped.append(_("{0}: Blanket Order {1} already covers this period").format(supplier, existing))
			continue

		order = frappe.new_doc("Blanket Order")
		order.update(
			{
				"blanket_order_type": "Purchasing",
				"supplier": supplier,
				"company": run_doc.company,
				"from_date": from_date,
				"to_date": to_date,
			}
		)
		for line in supplier_lines:
			qty = math.ceil(flt(line.ams) * months - 1e-9)
			if qty > 0:
				order.append(
					"items", {"item_code": line.item_code, "qty": qty, "rate": flt(rates.get(line.item_code))}
				)

		if not order.get("items"):
			continue
		order.insert()
		created.append(order.name)

	if no_supplier:
		skipped.append(_("{0} items without a supplier").format(no_supplier))

	return {"created": created, "skipped": skipped, "months": months}


def _overlapping_blanket_order(company, supplier, from_date, to_date):
	return frappe.db.get_value(
		"Blanket Order",
		{
			"blanket_order_type": "Purchasing",
			"company": company,
			"supplier": supplier,
			"docstatus": ("<", 2),
			"from_date": ("<=", to_date),
			"to_date": (">=", from_date),
		},
		"name",
	)

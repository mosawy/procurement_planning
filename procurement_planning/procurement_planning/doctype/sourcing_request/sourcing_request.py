# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Purchasing's side of a back-to-back quotation: one supplier offer per line,
priced into a suggested and a minimum rate that go back to the Quotation on
submit. No customer and no selling rate are on this document."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, formatdate, getdate, today

from procurement_planning.planning import back_to_back
from procurement_planning.planning.b2b_calculations import sourcing_request_status
from procurement_planning.planning.settings import get_company_settings


class SourcingRequest(Document):
	def validate(self):
		settings = get_company_settings(self.company)
		# Percent saves 0 when left blank: 0 means "use the settings default".
		if not flt(self.margin_percent):
			self.margin_percent = settings.default_margin_percent
		if not 0 <= flt(self.margin_percent) < 100:
			frappe.throw(_("Margin % must be from 0 up to below 100"))
		if flt(self.margin_percent) < settings.minimum_margin_percent:
			frappe.throw(
				_("Margin % cannot be below the Minimum Margin % of {0}").format(settings.minimum_margin_percent)
			)

		manual = [str(d.idx) for d in self.items if not d.quotation_item]
		if manual:
			frappe.throw(
				_("Rows {0} do not come from the Quotation. Lines are added only by Request Sourcing.").format(
					", ".join(manual)
				)
			)

		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		on_date = getdate(today())
		for line in self.items:
			back_to_back.evaluate_sourcing_line(self, line, settings, company_currency, on_date)
		self.set_status()

	def set_status(self):
		has_rfq = not self.is_new() and frappe.db.exists(
			"Request for Quotation Item", {"sourcing_request": self.name, "docstatus": ("<", 2)}
		)
		self.status = sourcing_request_status(
			self.docstatus,
			len([d for d in self.items if d.supplier_quotation_item]),
			len(self.items),
			bool(has_rfq),
		)

	def before_submit(self):
		missing = [str(d.idx) for d in self.items if not d.supplier_quotation_item]
		if missing:
			frappe.throw(_("Rows {0} have no supplier offer. Choose one with Supplier Offers.").format(", ".join(missing)))

		on_date = getdate(today())
		warnings = [
			_("Row {0}: the offer expired on {1}").format(d.idx, formatdate(d.valid_till))
			for d in self.items
			if d.valid_till and getdate(d.valid_till) < on_date
		] + [_("Row {0}: no lead time, so no promised date").format(d.idx) for d in self.items if not d.promised_date]
		if warnings:
			frappe.msgprint("<br>".join(warnings), title=_("Check the offers"), indicator="orange")

	def on_submit(self):
		back_to_back.return_prices_to_quotation(self)

	def before_cancel(self):
		back_to_back.check_quotation_before_cancel(self)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		back_to_back.clear_prices_on_quotation(self)


@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):
	"""Request for Quotation from a Sourcing Request; its lines keep the link so
	Supplier Quotations made from it point back to the Sourcing Request."""

	def set_missing_values(source, target):
		target.company = source.company
		on_date = getdate(today())
		schedule_date = max(getdate(source.required_by_date), on_date) if source.required_by_date else on_date
		for item in target.items:
			item.schedule_date = schedule_date

	return get_mapped_doc(
		"Sourcing Request",
		source_name,
		{
			"Sourcing Request": {
				"doctype": "Request for Quotation",
				"validation": {"docstatus": ["=", 0]},
				"field_no_map": ["status", "transaction_date"],
			},
			"Sourcing Request Item": {
				"doctype": "Request for Quotation Item",
				"field_map": [["name", "sourcing_request_item"], ["parent", "sourcing_request"]],
				"field_no_map": ["description"],
				"postprocess": lambda source, target, source_parent: target.update(
					{"description": source.description or source.item_name}
				),
			},
		},
		target_doc,
		set_missing_values,
	)

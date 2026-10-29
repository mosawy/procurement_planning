# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

NON_NEGATIVE_FIELDS = (
	"safety_stock_days",
	"review_period_days",
	"late_po_tolerance_days",
	"default_lead_time_days",
	"lead_time_history_months",
	"supplier_history_months",
)


class ProcurementPlanningSettings(Document):
	def validate(self):
		if cint(self.analysis_months) < 1:
			frappe.throw(_("Analysis Months must be at least 1"))

		for fieldname in NON_NEGATIVE_FIELDS:
			if cint(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative").format(_(self.meta.get_label(fieldname))))

		if cint(self.lead_time_min_samples) < 1:
			frappe.throw(_("Minimum Purchase Orders per Lead Time must be at least 1"))

		if not 0 < flt(self.stockout_day_ratio) <= 100:
			frappe.throw(_("Stock-out Month Threshold must be above 0% and at most 100%"))

		if self.default_purchase_warehouse:
			warehouse = frappe.db.get_value(
				"Warehouse", self.default_purchase_warehouse, ["company", "is_group"], as_dict=True
			)
			if warehouse.company != self.company:
				frappe.throw(
					_("Warehouse {0} does not belong to Company {1}").format(
						self.default_purchase_warehouse, self.company
					)
				)
			if warehouse.is_group:
				frappe.throw(_("Default Purchase Warehouse cannot be a group warehouse"))

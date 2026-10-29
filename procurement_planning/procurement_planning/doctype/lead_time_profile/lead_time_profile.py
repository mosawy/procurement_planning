# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, today

from procurement_planning.planning.lead_time import effective_entry


class LeadTimeProfile(Document):
	def validate(self):
		if not self.supplier and not self.brand:
			frappe.throw(_("Set a Supplier, a Brand, or both"))

		self.validate_unique()
		self.validate_entries()
		self.title = " · ".join(value for value in (self.supplier, self.brand) if value)
		self.set_current()

	def validate_unique(self):
		filters = {
			"company": self.company,
			"supplier": self.supplier or ("is", "not set"),
			"brand": self.brand or ("is", "not set"),
			"name": ("!=", self.name),
		}
		existing = frappe.db.get_value("Lead Time Profile", filters, "name")
		if existing:
			frappe.throw(
				_("Lead Time Profile {0} already exists for this company, supplier and brand").format(
					frappe.bold(existing)
				)
			)

	def validate_entries(self):
		seen = set()
		for entry in self.entries:
			if cint(entry.lead_time_days) <= 0:
				frappe.throw(_("Row {0}: Lead Time Days must be greater than 0").format(entry.idx))

			from_date = getdate(entry.from_date)
			if from_date in seen:
				frappe.throw(_("Row {0}: another entry already starts on {1}").format(entry.idx, entry.from_date))
			seen.add(from_date)

		self.entries.sort(key=lambda entry: getdate(entry.from_date))
		for idx, entry in enumerate(self.entries, start=1):
			entry.idx = idx

	def set_current(self):
		entry = effective_entry(
			[{"from_date": getdate(e.from_date), "lead_time_days": e.lead_time_days, "source": e.source, "idx": e.idx} for e in self.entries],
			getdate(today()),
		)
		self.current_lead_time_days = cint(entry["lead_time_days"]) if entry else 0
		self.current_source = entry["source"] if entry else None

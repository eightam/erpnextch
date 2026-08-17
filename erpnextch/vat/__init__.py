"""Swiss VAT (MwSt) tax templates.

Rates as of 2024: 8.1 % standard, 2.6 % reduced, 3.8 % accommodation, 0 %.
Sales VAT books against 2200 (Geschuldete MwSt), input VAT against 1170
(Vorsteuer Material/Waren/DL).

No electronic filing/export here by design — the fiduciary works from an
account statement plus balances. A later ``erpnextch.vat.export`` module can
add that without restructuring.
"""

import frappe

from erpnextch.coa import get_account

SALES_VAT_ACCOUNT = "2200"
INPUT_VAT_ACCOUNT = "1170"

# (title, rate, is_default)
RATES = [
	("MwSt 8.1% (Normalsatz)", 8.1, True),
	("MwSt 2.6% (reduzierter Satz)", 2.6, False),
	("MwSt 3.8% (Beherbergung)", 3.8, False),
	("MwSt 0% (befreit)", 0.0, False),
]


def apply_vat_templates(company: str) -> None:
	for title, rate, is_default in RATES:
		_ensure_template(
			"Sales Taxes and Charges Template",
			company,
			title,
			rate,
			is_default,
			get_account(company, SALES_VAT_ACCOUNT),
		)
		_ensure_template(
			"Purchase Taxes and Charges Template",
			company,
			title.replace("MwSt", "Vorsteuer", 1),
			rate,
			is_default,
			get_account(company, INPUT_VAT_ACCOUNT),
		)


def _ensure_template(
	doctype: str, company: str, title: str, rate: float, is_default: bool, account: str
) -> None:
	if frappe.db.exists(doctype, {"company": company, "title": title}):
		return
	row = {
		"charge_type": "On Net Total",
		"account_head": account,
		"rate": rate,
		"description": title,
	}
	if doctype == "Purchase Taxes and Charges Template":
		row.update({"category": "Total", "add_deduct_tax": "Add"})
	frappe.get_doc(
		{
			"doctype": doctype,
			"title": title,
			"company": company,
			"is_default": int(is_default),
			"taxes": [row],
		}
	).insert(ignore_permissions=True)

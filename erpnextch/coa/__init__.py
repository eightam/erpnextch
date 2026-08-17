"""Kontenrahmen KMU for ERPNext.

ERPNext core ships no Swiss chart of accounts. Core also does not discover
chart JSON from other apps, so the chart is applied via
``create_charts(custom_chart=…)`` from a setup function instead of the
Company-form dropdown: create the Company normally (it gets the standard
chart), then call :func:`apply_kmu_chart` to replace it.

The chart is a starting point following the common Swiss SME structure
(classes 1-8; class 9 is not needed — ERPNext closes periods virtually).
It needs fiduciary (Treuhänder) sign-off before go-live.
"""

import json
from pathlib import Path

import frappe

CHART_NAME = "Kontenrahmen KMU"

# Company default-account fields → KMU account numbers.
DEFAULT_ACCOUNTS = {
	"default_receivable_account": "1100",
	"default_payable_account": "2000",
	"default_cash_account": "1000",
	"default_bank_account": "1020",
	"default_income_account": "3200",
	"default_expense_account": "4200",
	"round_off_account": "6960",
	"write_off_account": "6961",
	"exchange_gain_loss_account": "6949",
	"default_inventory_account": "1200",
	"stock_received_but_not_billed": "2005",
	"service_received_but_not_billed": "2006",
	"default_provisional_account": "2006",
	"stock_adjustment_account": "4290",
}


def load_kmu_chart() -> dict:
	return json.loads((Path(__file__).parent / "kmu.json").read_text())


def apply_kmu_chart(company: str) -> None:
	"""Replace the company's chart of accounts with Kontenrahmen KMU.

	Wipes existing accounts and tax templates (same mechanism as core's
	Chart of Accounts Importer), rebuilds the tree and wires the company's
	default accounts by account number.
	"""
	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
		create_charts,
	)
	from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
		unset_existing_data,
	)

	unset_existing_data(company)
	# create_charts expects the account tree itself, not the chart wrapper.
	create_charts(company, custom_chart=load_kmu_chart()["tree"])
	set_company_default_accounts(company)


def get_account(company: str, account_number: str) -> str:
	name = frappe.db.get_value(
		"Account", {"company": company, "account_number": account_number, "is_group": 0}
	)
	if not name:
		frappe.throw(f"Account {account_number} not found for company {company}")
	return name


def set_company_default_accounts(company: str) -> None:
	doc = frappe.get_doc("Company", company)
	meta = frappe.get_meta("Company")
	for fieldname, account_number in DEFAULT_ACCOUNTS.items():
		if meta.has_field(fieldname):
			doc.set(fieldname, get_account(company, account_number))
	if meta.has_field("round_off_cost_center"):
		doc.round_off_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0})
	doc.save(ignore_permissions=True)

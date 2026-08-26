"""Turn a parsed camt file into ERPNext Bank Transactions.

This is the only part of the camt path that imports Frappe; the parsing in
:mod:`erpnextch.camt` stays site-free and unit-testable.

**Matching is deliberately not done here.** ERPNext ships the Bank
Reconciliation Tool, and a second, worse copy of it is the last thing this
app needs. We produce clean, de-duplicated Bank Transactions with the QR
reference in ``reference_number`` — the field the reconciliation already
looks at — and stop there. :func:`preview` does resolve the reference to an
invoice, but only to *show* the accountant what will happen; it writes
nothing and allocates nothing.

De-duplication is on ``transaction_id`` scoped to the bank account. Banks
re-deliver statements, and an accountant who imports the same file twice
must not end up with the payment twice. The id comes from the parser's
:func:`~erpnextch.camt._natural_id` (``AcctSvcrRef`` first).
"""

from __future__ import annotations

import frappe
from frappe import _

from erpnextch.camt import CamtError, Statement, Transaction, parse

# The invoice field erpnextch freezes the QR reference into on submit
# (Custom Field, see erpnextch.swiss_qr.sales_invoice).
INVOICE_REFERENCE_FIELD = "swiss_qr_reference"


def _clean_iban(iban: str | None) -> str:
	return (iban or "").replace(" ", "").upper()


def _company_bank_accounts() -> list[dict]:
	return frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 1, "disabled": 0},
		fields=["name", "iban", "account", "company", "is_default"],
	)


def find_bank_account(statement: Statement, explicit: str | None = None) -> tuple[str | None, str | None]:
	"""Find the Bank Account this statement belongs to. ``(name, problem)``.

	The IBAN the bank reports is the *account* IBAN. It is not necessarily the
	IBAN we print on a QR-bill: a QR-IBAN is a separate number on the same
	account, so a file can legitimately arrive with an IBAN that no Bank
	Account record carries. That is why an explicit choice always wins and a
	missing match is a question to the user, not an error in the file.

	Returns the problem instead of throwing, so the preview can show the file
	and offer the account list rather than dying on it.
	"""
	if explicit:
		account = frappe.db.get_value(
			"Bank Account", explicit, ["name", "is_company_account", "disabled"], as_dict=True
		)
		if not account:
			return None, _("No such bank account: {0}").format(explicit)
		if not account.is_company_account:
			return None, _("{0} is not a company bank account").format(explicit)
		if account.disabled:
			return None, _("Bank account {0} is disabled").format(explicit)
		return account.name, None

	iban = _clean_iban(statement.iban)
	if not iban:
		return None, _("The file names no account IBAN — choose the bank account.")
	matches = [a for a in _company_bank_accounts() if _clean_iban(a.get("iban")) == iban]
	if len(matches) == 1:
		return matches[0]["name"], None
	if not matches:
		return None, _("No company bank account with IBAN {0} — choose the bank account.").format(iban)
	return None, _("Several company bank accounts carry IBAN {0}").format(iban)


def resolve_bank_account(statement: Statement, explicit: str | None = None) -> str:
	"""Like :func:`find_bank_account`, but a problem is fatal."""
	name, problem = find_bank_account(statement, explicit)
	if not name:
		frappe.throw(problem)
	return name


def _existing(transaction_id: str, bank_account: str) -> str | None:
	"""Name of a Bank Transaction already carrying this id, if any.

	Cancelled documents (``docstatus`` 2) do not count: cancelling one is how
	an accountant undoes a wrong import, and the re-import has to get through.
	"""
	return frappe.db.get_value(
		"Bank Transaction",
		{"transaction_id": transaction_id, "bank_account": bank_account, "docstatus": ["<", 2]},
		"name",
	)


def _matching_invoice(reference: str | None) -> dict | None:
	"""The submitted invoice whose QR reference came back, if we know it."""
	if not reference:
		return None
	invoice = frappe.get_all(
		"Sales Invoice",
		filters={INVOICE_REFERENCE_FIELD: reference, "docstatus": 1},
		fields=["name", "customer", "grand_total", "outstanding_amount", "currency"],
		limit=1,
	)
	return invoice[0] if invoice else None


def _description(transaction: Transaction) -> str:
	"""Everything the bank told us, in one readable line."""
	parts = [
		transaction.party_name,
		transaction.unstructured,
		f"{transaction.reference_type or 'Ref'} {transaction.reference}" if transaction.reference else None,
	]
	if transaction.reversal:
		parts.insert(0, _("Reversal"))
	if transaction.batch_size > 1:
		parts.append(_("Batch booking, {0} entries").format(transaction.batch_size))
	line = " · ".join(p for p in parts if p)
	# Bank charges and the like name no party and carry no reference. An empty
	# description in the reconciliation tool is useless — fall back to what the
	# bank did tell us, its transaction code.
	return line or transaction.bank_transaction_code or ""


def _row(transaction: Transaction, bank_account: str) -> dict:
	"""One transaction as the UI wants to show it, plus why it will be skipped."""
	existing = _existing(transaction.transaction_id, bank_account)
	# Doppel zuerst: ein bereits eingelesener Eintrag darf auch dann nicht
	# noch einmal entstehen, wenn er (mit include_pending) als schwebender
	# gebucht wurde.
	if existing:
		skip = "duplicate"
	elif not transaction.booked:
		skip = "pending"
	else:
		skip = None
	invoice = _matching_invoice(transaction.reference)
	return {
		"transaction_id": transaction.transaction_id,
		"date": transaction.booking_date or transaction.value_date,
		"value_date": transaction.value_date,
		"amount": float(transaction.amount),
		"signed_amount": float(transaction.signed_amount),
		"currency": transaction.currency,
		"credit": transaction.credit,
		"status": transaction.status,
		"reference": transaction.reference,
		"reference_type": transaction.reference_type,
		"party_name": transaction.party_name,
		"party_iban": transaction.party_iban,
		"description": _description(transaction),
		"reversal": transaction.reversal,
		"batch_size": transaction.batch_size,
		"skip": skip,
		"existing": existing,
		"invoice": invoice,
	}


def _statement_summary(statement: Statement, bank_account: str | None, rows: list[dict]) -> dict:
	return {
		"iban": statement.iban,
		"statement_id": statement.statement_id,
		"message_id": statement.message_id,
		"sequence_number": statement.sequence_number,
		"created": statement.created,
		"document_type": statement.document_type,
		"bank_account": bank_account,
		"transactions": rows,
	}


def read(content: str | bytes) -> list[Statement]:
	"""Parse, turning a parser complaint into a Frappe-shaped error."""
	try:
		return parse(content)
	except CamtError as exc:
		frappe.throw(_("Cannot read this camt file: {0}").format(exc))


def preview(content: str | bytes, bank_account: str | None = None) -> dict:
	"""What an import would do. Writes nothing."""
	statements = read(content)
	blocks = []
	for statement in statements:
		resolved, problem = find_bank_account(statement, bank_account)
		rows = [_row(t, resolved) for t in statement.transactions] if resolved else []
		block = _statement_summary(statement, resolved, rows)
		block["problem"] = problem
		blocks.append(block)
	return {
		"statements": blocks,
		"bank_accounts": _company_bank_accounts(),
		"needs_account": any(b["bank_account"] is None for b in blocks),
	}


def import_camt(
	content: str | bytes,
	bank_account: str | None = None,
	include_pending: bool = False,
	submit: bool = True,
) -> dict:
	"""Create Bank Transactions for everything in the file that is new.

	Returns a per-transaction verdict — created, skipped as a duplicate, or
	skipped as not yet booked — so the caller can show the accountant what
	happened instead of a bare count.
	"""
	statements = read(content)
	if bank_account and len(statements) > 1:
		# Forcing one account onto a file that reports several would file
		# another account's bookings under this one.
		frappe.throw(
			_("This file carries {0} accounts — it cannot be imported into a single one.").format(
				len(statements)
			)
		)
	created: list[dict] = []
	skipped: list[dict] = []

	for statement in statements:
		account_name = resolve_bank_account(statement, bank_account)
		account = frappe.get_cached_doc("Bank Account", account_name)
		for transaction in statement.transactions:
			row = _row(transaction, account_name)
			if row["skip"] == "duplicate" or (row["skip"] == "pending" and not include_pending):
				skipped.append(row)
				continue
			doc = _bank_transaction(transaction, account, row["invoice"])
			doc.insert()
			if submit:
				doc.submit()
			row["name"] = doc.name
			created.append(row)

	return {
		"created": created,
		"skipped": skipped,
		"created_count": len(created),
		"skipped_count": len(skipped),
	}


def _bank_transaction(transaction: Transaction, account, invoice: dict | None) -> frappe.Document:
	signed = transaction.signed_amount
	doc = frappe.new_doc("Bank Transaction")
	doc.date = transaction.booking_date or transaction.value_date
	doc.bank_account = account.name
	doc.company = account.company
	doc.currency = transaction.currency
	doc.deposit = float(signed) if signed > 0 else 0.0
	doc.withdrawal = float(-signed) if signed < 0 else 0.0
	doc.description = _description(transaction)
	doc.reference_number = transaction.reference
	doc.transaction_id = transaction.transaction_id
	doc.transaction_type = transaction.bank_transaction_code
	doc.bank_party_name = transaction.party_name
	doc.bank_party_iban = transaction.party_iban

	# Our own QR reference coming back identifies the customer with certainty —
	# it is not a guess, so stamping the party is not the fuzzy matching we
	# leave to the Bank Reconciliation Tool. It earns the transaction a party
	# rank there and prefills "Create Voucher".
	# Only on money in: a QRR on an outgoing payment is somebody else's
	# reference and says nothing about our customer.
	if transaction.credit and invoice:
		doc.party_type = "Customer"
		doc.party = invoice["customer"]
	return doc

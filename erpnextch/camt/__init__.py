"""camt.052 / .053 / .054 reader for Swiss banks.

Produces clean, de-duplicated transactions. **Matching is not our job** —
ERPNext's Bank Reconciliation Tool does that, and doing it twice would mean
maintaining a second, worse copy of it. See :mod:`erpnextch.camt.importer`
for the Frappe seam that turns these into Bank Transactions.

Two design decisions worth not re-opening:

**Namespace-agnostic parsing.** Everything is matched on *local* element
names, never on a namespace URI. This is not a style preference: Raiffeisen's
transition period for ISO 20022 version 2019 ends on 13 November 2026, inside
the go-live window, and the element names are identical between
``camt.053.001.04`` and ``.08`` — only the namespace differs. Reading both
therefore needs no flag, no configuration and no migration. Confirmed against
a real Raiffeisen export on 2026-08-25, which is still ``.04``.

**Version-tolerant field access.** Where the two versions genuinely differ in
*shape* rather than in namespace, both shapes are read: ``<Sts>BOOK</Sts>``
(2013) and ``<Sts><Cd>BOOK</Cd></Sts>`` (2019), ``BookgDt/Dt`` and
``BookgDt/DtTm``.

This module imports no Frappe and is unit-testable without a site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

# The three container shapes a Swiss bank may deliver. camt.053 sends
# statements, camt.052 interim reports, camt.054 debit/credit notifications;
# below the container they are the same document.
CONTAINERS = {
	"BkToCstmrStmt": "Stmt",
	"BkToCstmrAcctRpt": "Rpt",
	"BkToCstmrDbtCdtNtfctn": "Ntfctn",
}

# Booked. `PDNG` is announced but not booked and is skipped by default —
# a pending entry can still change or disappear, and booking it would put a
# transaction into the ledger that the bank has not made.
STATUS_BOOKED = "BOOK"
STATUS_PENDING = "PDNG"

# Banks write this when no end-to-end reference was supplied. It is not an
# identifier and must never be used as one.
NOT_PROVIDED = {"NOTPROVIDED", "NOTPROVIDED "}


class CamtError(ValueError):
	"""The file is not a camt document we can read."""


@dataclass
class Transaction:
	"""One leg of one booking, as the bank reports it."""

	amount: Decimal
	currency: str
	credit: bool  # True = money in
	booking_date: date | None
	value_date: date | None
	status: str
	transaction_id: str
	reference: str | None = None  # QRR/SCOR — our own reference coming back
	reference_type: str | None = None
	unstructured: str | None = None
	end_to_end_id: str | None = None
	account_servicer_reference: str | None = None
	party_name: str | None = None
	party_iban: str | None = None
	bank_transaction_code: str | None = None
	reversal: bool = False
	batch_size: int = 1

	@property
	def signed_amount(self) -> Decimal:
		return self.amount if self.credit else -self.amount

	@property
	def booked(self) -> bool:
		return self.status == STATUS_BOOKED


@dataclass
class Statement:
	"""One account's worth of transactions out of one file."""

	iban: str | None = None
	currency: str | None = None
	message_id: str | None = None
	statement_id: str | None = None
	sequence_number: str | None = None
	created: datetime | None = None
	document_type: str | None = None
	transactions: list[Transaction] = field(default_factory=list)

	@property
	def booked(self) -> list[Transaction]:
		return [t for t in self.transactions if t.booked]


# --- XML helpers, all namespace-agnostic --------------------------------


def _local(tag: str) -> str:
	return tag.rsplit("}", 1)[-1]


def _children(element, name: str) -> list:
	return [child for child in element if _local(child.tag) == name]


def _child(element, name: str):
	for child in element:
		if _local(child.tag) == name:
			return child
	return None


def _dig(element, *names):
	current = element
	for name in names:
		if current is None:
			return None
		current = _child(current, name)
	return current


def _text(element, *names) -> str | None:
	node = _dig(element, *names) if names else element
	if node is None or node.text is None:
		return None
	return node.text.strip() or None


def _texts(element, *names) -> list[str]:
	"""All repetitions of a leaf (``RmtInf/Ustrd`` may appear many times)."""
	parent = _dig(element, *names[:-1]) if len(names) > 1 else element
	if parent is None:
		return []
	return [c.text.strip() for c in _children(parent, names[-1]) if c.text and c.text.strip()]


def _decimal(raw: str | None) -> Decimal:
	try:
		return Decimal(raw)
	except (InvalidOperation, TypeError):
		raise CamtError(f"Not an amount: {raw!r}") from None


def _date(element, name: str) -> date | None:
	"""``<BookgDt><Dt>`` (2013) or ``<BookgDt><DtTm>`` (2019)."""
	node = _child(element, name)
	if node is None:
		return None
	raw = _text(node, "Dt") or _text(node, "DtTm") or _text(node)
	if not raw:
		return None
	try:
		return datetime.fromisoformat(raw).date()
	except ValueError:
		# Last resort for exotic offsets: the leading ISO date is enough.
		try:
			return date.fromisoformat(raw[:10])
		except ValueError:
			return None


def _status(entry) -> str:
	"""``<Sts>BOOK</Sts>`` (2013) or ``<Sts><Cd>BOOK</Cd></Sts>`` (2019)."""
	node = _child(entry, "Sts")
	if node is None:
		return STATUS_BOOKED
	return _text(node, "Cd") or _text(node) or STATUS_BOOKED


def _is_true(value: str | None) -> bool:
	return (value or "").strip().lower() in {"true", "1"}


def _bank_transaction_code(element) -> str | None:
	code = _dig(element, "BkTxCd")
	if code is None:
		return None
	domain = _text(code, "Domn", "Cd")
	family = _dig(code, "Domn", "Fmly")
	parts = [
		domain,
		_text(family, "Cd") if family is not None else None,
		_text(family, "SubFmlyCd") if family is not None else None,
	]
	joined = "/".join(p for p in parts if p)
	return joined or _text(code, "Prtry", "Cd")


# --- Parsing ------------------------------------------------------------


def parse(source: str | bytes) -> list[Statement]:
	"""Read a camt file. One :class:`Statement` per account block in it."""
	if isinstance(source, str):
		source = source.encode("utf-8")
	try:
		root = ElementTree.fromstring(source)
	except ElementTree.ParseError as exc:
		raise CamtError(f"Not well-formed XML: {exc}") from exc

	message_id = None
	statements: list[Statement] = []
	for container_name, report_name in CONTAINERS.items():
		container = _child(root, container_name)
		if container is None:
			continue
		message_id = _text(container, "GrpHdr", "MsgId")
		for report in _children(container, report_name):
			statements.append(_parse_report(report, container_name, message_id))
	if not statements:
		raise CamtError("No camt container found — expected one of " + ", ".join(CONTAINERS))
	return statements


def parse_one(source: str | bytes) -> Statement:
	"""Convenience for the common single-account file."""
	statements = parse(source)
	if len(statements) != 1:
		raise CamtError(f"Expected one account block, found {len(statements)}")
	return statements[0]


def _parse_report(report, container_name: str, message_id: str | None) -> Statement:
	account = _dig(report, "Acct")
	statement = Statement(
		iban=_text(account, "Id", "IBAN") if account is not None else None,
		currency=_text(account, "Ccy") if account is not None else None,
		message_id=message_id,
		statement_id=_text(report, "Id"),
		sequence_number=_text(report, "ElctrncSeqNb") or _text(report, "LglSeqNb"),
		document_type=container_name,
	)
	created = _text(report, "CreDtTm")
	if created:
		try:
			statement.created = datetime.fromisoformat(created)
		except ValueError:
			statement.created = None

	for entry in _children(report, "Ntry"):
		statement.transactions.extend(_parse_entry(entry))
	return statement


def _parse_entry(entry) -> list[Transaction]:
	"""One entry, expanded into one transaction per ``TxDtls``.

	Swiss batch bookings (*Sammelbuchungen*) arrive as a single ``Ntry`` with
	many ``TxDtls`` — one per paying customer, each carrying its own QR
	reference. Booking the sum would throw away exactly the information the
	reconciliation needs, so each leg becomes its own transaction.
	"""
	entry_amount_node = _child(entry, "Amt")
	entry_currency = entry_amount_node.get("Ccy") if entry_amount_node is not None else None
	entry_credit = (_text(entry, "CdtDbtInd") or "CRDT") == "CRDT"
	reversal = _is_true(_text(entry, "RvslInd"))
	status = _status(entry)
	booking_date = _date(entry, "BookgDt")
	value_date = _date(entry, "ValDt")
	entry_servicer_ref = _text(entry, "AcctSvcrRef")
	entry_code = _bank_transaction_code(entry)

	details = [tx for group in _children(entry, "NtryDtls") for tx in _children(group, "TxDtls")]

	if not details:
		# Some banks put everything on the entry itself.
		transactions = [
			_build(
				amount=_decimal(_text(entry_amount_node) if entry_amount_node is not None else None),
				currency=entry_currency,
				credit=entry_credit,
				reversal=reversal,
				status=status,
				booking_date=booking_date,
				value_date=value_date,
				servicer_ref=entry_servicer_ref,
				end_to_end_id=None,
				reference=None,
				reference_type=None,
				unstructured=None,
				party_name=None,
				party_iban=None,
				code=entry_code,
				batch_size=1,
			)
		]
	else:
		transactions = []
		for detail in details:
			amount_node = _child(detail, "Amt")
			amount = (
				_decimal(_text(amount_node))
				if amount_node is not None
				else _decimal(_text(entry_amount_node) if entry_amount_node is not None else None)
			)
			currency = (amount_node.get("Ccy") if amount_node is not None else None) or entry_currency
			credit = (_text(detail, "CdtDbtInd") or ("CRDT" if entry_credit else "DBIT")) == "CRDT"
			reference, reference_type, unstructured = _remittance(detail)
			party_name, party_iban = _counterparty(detail, credit)
			transactions.append(
				_build(
					amount=amount,
					currency=currency,
					credit=credit,
					reversal=reversal,
					status=status,
					booking_date=booking_date,
					value_date=value_date,
					servicer_ref=_text(detail, "Refs", "AcctSvcrRef") or entry_servicer_ref,
					end_to_end_id=_text(detail, "Refs", "EndToEndId"),
					reference=reference,
					reference_type=reference_type,
					unstructured=unstructured,
					party_name=party_name,
					party_iban=party_iban,
					code=_bank_transaction_code(detail) or entry_code,
					batch_size=len(details),
				)
			)

	_disambiguate(transactions)
	return transactions


def _build(
	*,
	amount: Decimal,
	currency: str | None,
	credit: bool,
	reversal: bool,
	status: str,
	booking_date: date | None,
	value_date: date | None,
	servicer_ref: str | None,
	end_to_end_id: str | None,
	reference: str | None,
	reference_type: str | None,
	unstructured: str | None,
	party_name: str | None,
	party_iban: str | None,
	code: str | None,
	batch_size: int,
) -> Transaction:
	# A reversal undoes an earlier booking: the money moves the other way.
	if reversal:
		credit = not credit
	if end_to_end_id in NOT_PROVIDED:
		end_to_end_id = None

	transaction = Transaction(
		amount=amount,
		currency=currency or "CHF",
		credit=credit,
		booking_date=booking_date,
		value_date=value_date,
		status=status,
		transaction_id="",
		reference=reference,
		reference_type=reference_type,
		unstructured=unstructured,
		end_to_end_id=end_to_end_id,
		account_servicer_reference=servicer_ref,
		party_name=party_name,
		party_iban=party_iban,
		bank_transaction_code=code,
		reversal=reversal,
		batch_size=batch_size,
	)
	transaction.transaction_id = _natural_id(transaction)
	return transaction


def _natural_id(transaction: Transaction) -> str:
	"""De-duplication key, best identifier first.

	`AcctSvcrRef` is the bank's own handle on the booking and is stable
	across re-deliveries of the same statement. `EndToEndId` is the payer's
	and only unique if they made it so. The composite is the last resort —
	it re-identifies the same booking from a re-imported file without
	claiming to be a bank reference.
	"""
	if transaction.account_servicer_reference:
		return transaction.account_servicer_reference
	if transaction.end_to_end_id:
		return transaction.end_to_end_id
	parts = [
		transaction.booking_date.isoformat() if transaction.booking_date else "",
		f"{transaction.signed_amount:f}",
		transaction.reference or transaction.unstructured or "",
	]
	return "|".join(parts)


def _disambiguate(transactions: list[Transaction]) -> None:
	"""Give colliding legs of one batch distinct ids.

	Raiffeisen repeats the entry's `AcctSvcrRef` on every `TxDtls`, so a
	batch booking would otherwise collapse into a single transaction on
	import — and the other payers' references would be lost.
	"""
	seen: dict[str, int] = {}
	for transaction in transactions:
		base = transaction.transaction_id
		seen[base] = seen.get(base, 0) + 1
	if all(count == 1 for count in seen.values()):
		return
	counters: dict[str, int] = {}
	for transaction in transactions:
		base = transaction.transaction_id
		if seen[base] == 1:
			continue
		counters[base] = counters.get(base, 0) + 1
		transaction.transaction_id = f"{base}-{counters[base]}"


def _remittance(detail) -> tuple[str | None, str | None, str | None]:
	"""Structured reference (QRR/SCOR) plus whatever prose came along."""
	remittance = _child(detail, "RmtInf")
	if remittance is None:
		return None, None, None

	reference = reference_type = None
	structured = _child(remittance, "Strd")
	if structured is not None:
		info = _child(structured, "CdtrRefInf")
		if info is not None:
			reference = _text(info, "Ref")
			type_node = _dig(info, "Tp", "CdOrPrtry")
			if type_node is not None:
				reference_type = _text(type_node, "Prtry") or _text(type_node, "Cd")

	prose = _texts(remittance, "Ustrd")
	if structured is not None:
		prose += _texts(structured, "AddtlRmtInf")
	return reference, reference_type, " ".join(prose) or None


def _counterparty(detail, credit: bool) -> tuple[str | None, str | None]:
	"""Who the money came from (credit) or went to (debit)."""
	parties = _child(detail, "RltdPties")
	accounts = _child(detail, "RltdPties")
	if parties is None:
		return None, None
	party_tag, account_tag = ("Dbtr", "DbtrAcct") if credit else ("Cdtr", "CdtrAcct")
	name = _text(parties, party_tag, "Nm") or _text(parties, f"Ultmt{party_tag}", "Nm")
	iban = _text(accounts, account_tag, "Id", "IBAN")
	return name, iban

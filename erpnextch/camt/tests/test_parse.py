"""camt parsing, against anonymised files that mirror real bank exports.

The fixtures in ``files/`` carry placeholder names, IBANs and references
only — a real export contains payer names and account numbers and must never
enter the repository.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from erpnextch.camt import CamtError, parse, parse_one

FILES = Path(__file__).parent / "files"


def read(name: str) -> bytes:
	return (FILES / name).read_bytes()


@pytest.fixture
def notification():
	return parse_one(read("camt054_notification.xml"))


@pytest.fixture
def statement():
	return parse_one(read("camt053_statement.xml"))


# --- container shapes and namespaces ------------------------------------


def test_reads_a_2013_notification(notification):
	assert notification.document_type == "BkToCstmrDbtCdtNtfctn"
	assert notification.iban == "CH40999990000000TEST1"
	assert notification.statement_id == "NTF-PLACEHOLDER-0001"
	assert notification.message_id == "MSG-PLACEHOLDER-0001"
	assert notification.sequence_number == "51"


def test_reads_a_2019_statement_from_the_other_namespace(statement):
	"""The .04 and .08 files above differ only in the namespace URI.

	Raiffeisen's transition period for ISO 20022 version 2019 ends on
	13 November 2026, inside the go-live window, so both have to read.
	"""
	assert statement.document_type == "BkToCstmrStmt"
	assert statement.iban == "CH40999990000000TEST1"
	assert statement.currency == "CHF"


def test_rejects_a_file_that_is_not_camt():
	with pytest.raises(CamtError):
		parse("<Document><Something/></Document>")


def test_rejects_junk():
	with pytest.raises(CamtError):
		parse("this is not xml")


# --- the single credit, as a real QR payment arrives --------------------


def test_credit_carries_the_qr_reference(notification):
	transaction = notification.transactions[0]
	assert transaction.amount == Decimal("537.5")
	assert transaction.currency == "CHF"
	assert transaction.credit is True
	assert transaction.signed_amount == Decimal("537.5")
	assert transaction.reference == "099999000000000000000000014"
	assert transaction.reference_type == "QRR"
	assert transaction.booking_date == date(2026, 8, 25)
	assert transaction.value_date == date(2026, 8, 25)
	assert transaction.booked is True


def test_counterparty_is_the_debtor_on_a_credit(notification):
	transaction = notification.transactions[0]
	assert transaction.party_name == "Platzhalter Kundin"
	assert transaction.party_iban == "CH18999990000000TEST9"


def test_notprovided_is_not_an_identifier(notification):
	"""Banks write NOTPROVIDED where no end-to-end id was supplied."""
	assert notification.transactions[0].end_to_end_id is None
	assert notification.transactions[0].transaction_id == "90000000001"


def test_bank_transaction_code_is_flattened(notification):
	assert notification.transactions[0].bank_transaction_code == "PMNT/RCDT/VCOM"


def test_additional_remittance_info_is_kept(notification):
	assert notification.transactions[0].unstructured == "R.0001"


# --- batch bookings -----------------------------------------------------


def test_batch_booking_is_expanded_into_its_legs(statement):
	legs = [t for t in statement.transactions if t.batch_size > 1]
	assert len(legs) == 2
	assert [t.amount for t in legs] == [Decimal("100.00"), Decimal("200.00")]
	assert [t.reference for t in legs] == [
		"099999000000000000000000022",
		"099999000000000000000000038",
	]


def test_batch_legs_get_distinct_ids(statement):
	"""The bank repeats one AcctSvcrRef on every leg.

	Left alone they would de-duplicate against each other on import and all
	but one payer's reference would be lost.
	"""
	legs = [t for t in statement.transactions if t.batch_size > 1]
	assert [t.transaction_id for t in legs] == ["90000000002-1", "90000000002-2"]


def test_ids_are_unique_across_the_file(statement):
	ids = [t.transaction_id for t in statement.transactions]
	assert len(ids) == len(set(ids))


# --- the awkward entries ------------------------------------------------


def test_pending_entries_are_parsed_but_not_booked(statement):
	pending = [t for t in statement.transactions if not t.booked]
	assert len(pending) == 1
	assert pending[0].status == "PDNG"
	assert pending[0] not in statement.booked


def test_debit_is_negative_and_reads_the_creditor(statement):
	debit = next(t for t in statement.transactions if t.transaction_id == "90000000004")
	assert debit.credit is False
	assert debit.signed_amount == Decimal("-89.90")
	assert debit.party_name == "Platzhalter Lieferant"
	assert debit.reference == "RF96PLACEHOLDER01"
	assert debit.reference_type == "SCOR"
	assert debit.end_to_end_id == "PLACEHOLDER-E2E-0004"


def test_reversal_moves_the_money_the_other_way(statement):
	"""A reversal undoes an earlier booking: a reversed credit is an outflow."""
	reversal = next(t for t in statement.transactions if t.reversal)
	assert reversal.credit is False
	assert reversal.signed_amount == Decimal("-50.00")


def test_entry_without_transaction_details_still_books(statement):
	bare = next(t for t in statement.transactions if t.transaction_id == "90000000006")
	assert bare.signed_amount == Decimal("-12.35")
	assert bare.batch_size == 1
	assert bare.reference is None


# --- dates --------------------------------------------------------------


def test_both_date_shapes_read(statement):
	"""BookgDt/Dt (2013) and BookgDt/DtTm (2019)."""
	from_dttm = next(t for t in statement.transactions if t.transaction_id.startswith("90000000002"))
	from_dt = next(t for t in statement.transactions if t.transaction_id == "90000000004")
	assert from_dttm.booking_date == date(2026, 8, 26)
	assert from_dt.booking_date == date(2026, 8, 26)


def test_missing_booking_date_falls_back_to_value_date(statement):
	pending = next(t for t in statement.transactions if not t.booked)
	assert pending.booking_date is None
	assert pending.value_date == date(2026, 8, 27)


# --- multiple accounts in one file --------------------------------------


def test_parse_one_refuses_a_multi_account_file():
	"""A file may carry several accounts; parse() returns one block each."""
	single = read("camt053_statement.xml").decode()
	block = single[single.index("<Stmt>") : single.index("</Stmt>") + len("</Stmt>")]
	second = block.replace("CH40999990000000TEST1", "CH88319990000000TEST2")
	two_accounts = single.replace("</BkToCstmrStmt>", second + "</BkToCstmrStmt>")

	statements = parse(two_accounts)
	assert [s.iban for s in statements] == [
		"CH40999990000000TEST1",
		"CH88319990000000TEST2",
	]
	with pytest.raises(CamtError):
		parse_one(two_accounts)

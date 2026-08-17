"""Unit tests for the QR-bill payload builder. No Frappe, no site."""

import pytest

from erpnextch.swiss_qr.payload import Party, PayloadError, QRBillData, sanitize

QR_IBAN = "CH4431999123000889012"
NORMAL_IBAN = "CH9300762011623852957"
QRR = "210000000003139471430009017"
SCOR = "RF18539007547034"

CREDITOR = Party(
	name="Rad9 GmbH", street="Tödistrasse", building_number="9", postal_code="9400", town="Rorschach"
)
DEBTOR = Party(
	name="Velo Muster AG", street="Bahnhofstrasse", building_number="1", postal_code="8000", town="Zürich"
)


def make_bill(**overrides):
	defaults = dict(
		account=QR_IBAN,
		creditor=CREDITOR,
		amount=3949.75,
		currency="CHF",
		debtor=DEBTOR,
		reference=QRR,
		message="Rechnung SINV-0001",
	)
	defaults.update(overrides)
	return QRBillData(**defaults)


class TestPayload:
	def test_canonical_payload(self):
		expected = "\r\n".join(
			[
				"SPC",
				"0200",
				"1",
				QR_IBAN,
				"S",
				"Rad9 GmbH",
				"Tödistrasse",
				"9",
				"9400",
				"Rorschach",
				"CH",
				*[""] * 7,
				"3949.75",
				"CHF",
				"S",
				"Velo Muster AG",
				"Bahnhofstrasse",
				"1",
				"8000",
				"Zürich",
				"CH",
				"QRR",
				QRR,
				"Rechnung SINV-0001",
				"EPD",
			]
		)
		assert make_bill().payload() == expected

	def test_payload_line_count_without_billing_info(self):
		assert len(make_bill().payload().split("\r\n")) == 31

	def test_billing_info_appended_after_trailer(self):
		lines = make_bill(message="", billing_info="//S1/10/1234").payload().split("\r\n")
		assert lines[-2] == "EPD"
		assert lines[-1] == "//S1/10/1234"

	def test_no_debtor_no_amount(self):
		bill = make_bill(amount=None, debtor=None)
		lines = bill.payload().split("\r\n")
		assert lines[18] == ""  # amount
		assert lines[20:27] == [""] * 7  # debtor block

	def test_reference_spaces_stripped(self):
		bill = make_bill(reference="21 00000 00003 13947 14300 09017")
		assert QRR in bill.payload().split("\r\n")

	def test_scor_with_normal_iban(self):
		bill = make_bill(account=NORMAL_IBAN, reference=SCOR)
		assert bill.payload().split("\r\n")[27] == "SCOR"

	def test_non_with_normal_iban(self):
		bill = make_bill(account=NORMAL_IBAN, reference=None)
		lines = bill.payload().split("\r\n")
		assert lines[27] == "NON"
		assert lines[28] == ""


class TestValidation:
	def test_qrr_with_normal_iban_rejected(self):
		with pytest.raises(PayloadError):
			make_bill(account=NORMAL_IBAN, reference=QRR).payload()

	def test_qr_iban_without_reference_rejected(self):
		with pytest.raises(PayloadError):
			make_bill(reference=None).payload()

	def test_foreign_iban_rejected(self):
		with pytest.raises(PayloadError):
			make_bill(account="DE89370400440532013000", reference=None).payload()

	def test_bad_currency_rejected(self):
		with pytest.raises(PayloadError):
			make_bill(currency="USD").payload()

	def test_amount_out_of_range_rejected(self):
		with pytest.raises(PayloadError):
			make_bill(amount=0.0).payload()
		with pytest.raises(PayloadError):
			make_bill(amount=1_000_000_000.0).payload()

	def test_missing_creditor_name_rejected(self):
		creditor = Party(name="", postal_code="9400", town="Rorschach")
		with pytest.raises(PayloadError):
			make_bill(creditor=creditor).payload()

	def test_bad_country_rejected(self):
		creditor = Party(name="Rad9 GmbH", postal_code="9400", town="Rorschach", country="Schweiz")
		with pytest.raises(PayloadError):
			make_bill(creditor=creditor).payload()

	def test_combined_message_limit(self):
		with pytest.raises(PayloadError):
			make_bill(message="M" * 100, billing_info="B" * 100).payload()


class TestSanitize:
	def test_typographic_replacements(self):
		assert sanitize("Zur «Post» – heute’s Angebot") == 'Zur "Post" - heute\'s Angebot'

	def test_disallowed_characters_dropped(self):
		assert sanitize("Grüße 😀 aus Zürich") == "Grüße  aus Zürich"

	def test_umlauts_preserved(self):
		assert sanitize("Tödistrasse") == "Tödistrasse"

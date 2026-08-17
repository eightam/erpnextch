"""Unit tests for QRR/SCOR reference logic. No Frappe, no site — plain pytest."""

import pytest

from erpnextch.swiss_qr.reference import (
	InvalidReferenceError,
	format_qrr,
	format_scor,
	generate_qrr,
	generate_scor,
	is_qr_iban,
	mod10_recursive,
	reference_type_for_iban,
	validate_iban,
	validate_qrr,
	validate_scor,
)

# Known-good vectors from the briefing / Swiss payment standards.
QRR_BASE = "21000000000313947143000901"
QRR_FULL = "210000000003139471430009017"
SCOR_PAYLOAD = "539007547034"
SCOR_FULL = "RF18539007547034"

QR_IBAN = "CH4431999123000889012"  # QR-IID 31999 (test range)
NORMAL_IBAN = "CH9300762011623852957"


class TestQRR:
	def test_briefing_vector_check_digit(self):
		assert mod10_recursive(QRR_BASE) == 7

	def test_generate(self):
		assert generate_qrr(QRR_BASE) == QRR_FULL

	def test_generate_pads_short_base(self):
		reference = generate_qrr("1")
		assert len(reference) == 27
		assert reference.startswith("0" * 25 + "1")
		validate_qrr(reference)

	def test_validate_roundtrip(self):
		assert validate_qrr(QRR_FULL) == QRR_FULL

	def test_validate_accepts_spaces(self):
		assert validate_qrr("21 00000 00003 13947 14300 09017") == QRR_FULL

	def test_wrong_check_digit_rejected(self):
		with pytest.raises(InvalidReferenceError):
			validate_qrr(QRR_BASE + "8")

	def test_wrong_length_rejected(self):
		with pytest.raises(InvalidReferenceError):
			validate_qrr(QRR_BASE)  # 26 digits

	def test_non_numeric_rejected(self):
		with pytest.raises(InvalidReferenceError):
			generate_qrr("21X00000000313947143000901")

	def test_too_long_base_rejected(self):
		with pytest.raises(InvalidReferenceError):
			generate_qrr("9" * 27)

	def test_format_blocks_of_five_from_right(self):
		assert format_qrr(QRR_FULL) == "21 00000 00003 13947 14300 09017"


class TestSCOR:
	def test_briefing_vector(self):
		assert generate_scor(SCOR_PAYLOAD) == SCOR_FULL

	def test_validate_roundtrip(self):
		assert validate_scor(SCOR_FULL) == SCOR_FULL

	def test_validate_accepts_spaces_and_lowercase(self):
		assert validate_scor("rf18 5390 0754 7034") == SCOR_FULL

	def test_alphanumeric_payload(self):
		reference = generate_scor("AB2G5")
		assert reference.startswith("RF")
		assert validate_scor(reference) == reference

	def test_wrong_check_digits_rejected(self):
		with pytest.raises(InvalidReferenceError):
			validate_scor("RF19539007547034")

	def test_too_long_payload_rejected(self):
		with pytest.raises(InvalidReferenceError):
			generate_scor("1" * 22)

	def test_empty_payload_rejected(self):
		with pytest.raises(InvalidReferenceError):
			generate_scor("")

	def test_format_blocks_of_four(self):
		assert format_scor(SCOR_FULL) == "RF18 5390 0754 7034"


class TestIBAN:
	def test_valid_normal_iban(self):
		assert validate_iban("CH93 0076 2011 6238 5295 7") == NORMAL_IBAN

	def test_invalid_checksum_rejected(self):
		with pytest.raises(InvalidReferenceError):
			validate_iban("CH9300762011623852958")

	def test_qr_iban_detected(self):
		assert is_qr_iban(QR_IBAN) is True

	def test_normal_iban_not_qr(self):
		assert is_qr_iban(NORMAL_IBAN) is False

	def test_foreign_iban_not_qr(self):
		assert is_qr_iban("DE89370400440532013000") is False


class TestSchemeBinding:
	def test_qr_iban_with_qrr(self):
		assert reference_type_for_iban(QR_IBAN, QRR_FULL) == "QRR"

	def test_qr_iban_without_reference_rejected(self):
		with pytest.raises(InvalidReferenceError):
			reference_type_for_iban(QR_IBAN, None)

	def test_qr_iban_with_scor_rejected(self):
		with pytest.raises(InvalidReferenceError):
			reference_type_for_iban(QR_IBAN, SCOR_FULL)

	def test_normal_iban_with_scor(self):
		assert reference_type_for_iban(NORMAL_IBAN, SCOR_FULL) == "SCOR"

	def test_normal_iban_without_reference(self):
		assert reference_type_for_iban(NORMAL_IBAN, None) == "NON"

	def test_normal_iban_with_qrr_rejected(self):
		with pytest.raises(InvalidReferenceError):
			reference_type_for_iban(NORMAL_IBAN, QRR_FULL)

"""Company-level setup: apply the Swiss localisation to an existing Company."""

from erpnextch.coa import apply_kmu_chart
from erpnextch.vat import apply_vat_templates


def setup_company(company: str) -> None:
	"""Replace the chart with Kontenrahmen KMU and create MwSt templates.

	Destructive on existing accounts/tax templates of that company — meant to
	run right after the Company is created (e.g. from a seed script).
	"""
	apply_kmu_chart(company)
	apply_vat_templates(company)

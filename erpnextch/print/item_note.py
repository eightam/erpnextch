"""Optional note line under an item row on the sales documents.

An app that adds its own field to the item tables (Sales Order Item,
Delivery Note Item, Sales Invoice Item) can have it printed under the item
code without forking the print formats. It declares the field in its
``hooks.py``:

    erpnextch_item_note = {
        "field": "my_custom_field",
        "label": {"de": "Referenz", "fr": "Référence"},
    }

A row without a value prints nothing; with no app declaring the hook the
documents render exactly as before. If several apps declare it, the last
one installed wins.

The formatting below is Frappe-free so it is unit-testable without a bench;
only ``item_note`` reads the hooks.
"""

HOOK = "erpnextch_item_note"


def _last(value):
	# Frappe collects hook values from every app into lists.
	return value[-1] if isinstance(value, list) and value else value


def format_note(spec, item, language: str = "de") -> str:
	"""``spec`` as ``frappe.get_hooks(HOOK)`` returns it; "" when nothing to print."""
	if not spec:
		return ""
	field = _last(spec.get("field"))
	if not field:
		return ""
	value = item.get(field)
	if not value:
		return ""
	labels = spec.get("label") or {}
	if isinstance(labels, list):
		merged = {}
		for entry in labels:
			merged.update(entry or {})
		labels = merged
	label = labels.get(language) or labels.get("de")
	return f"{label}: {value}" if label else str(value)


def item_note(item, language: str = "de") -> str:
	"""Jinja method: "Label: value" for this item row, or "" when unset."""
	import frappe

	return format_note(frappe.get_hooks(HOOK), item, language)

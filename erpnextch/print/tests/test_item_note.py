from erpnextch.print.item_note import format_note

# Shape as frappe.get_hooks returns it: every hook value collected into lists.
SPEC = {"field": ["ref"], "label": [{"de": "Referenz", "fr": "Référence"}]}


def test_no_hook_prints_nothing():
	assert format_note(None, {"ref": "Meier"}) == ""
	assert format_note({}, {"ref": "Meier"}) == ""


def test_label_follows_the_document_language():
	assert format_note(SPEC, {"ref": "Meier"}, "de") == "Referenz: Meier"
	assert format_note(SPEC, {"ref": "Meier"}, "fr") == "Référence: Meier"


def test_a_row_without_value_prints_nothing():
	assert format_note(SPEC, {"ref": ""}, "de") == ""
	assert format_note(SPEC, {}, "de") == ""


def test_missing_language_falls_back_to_german():
	spec = {"field": ["ref"], "label": [{"de": "Referenz"}]}
	assert format_note(spec, {"ref": "Meier"}, "fr") == "Referenz: Meier"


def test_without_label_the_value_stands_alone():
	assert format_note({"field": ["ref"]}, {"ref": "Meier"}) == "Meier"

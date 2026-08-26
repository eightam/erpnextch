"""Guard the shared sales-document print template against class-name capture.

Frappe serves `print.bundle.css` — which still carries Bootstrap 3 — into both
the Desk print preview and the wkhtmltopdf render, and several of its selectors
are unscoped. `.label` is the one that bit us: it sets `display: inline` plus a
`@media print` border, so a `<td class="label">` silently stopped being a table
cell and grew a black frame around it. Nothing in the template's own CSS can
defend against that; the only defence is to never use a bare class name.
"""

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "print_formats" / "document_body.html"

#: Classes we deliberately borrow from Frappe to hide its print chrome.
FRAPPE_CLASSES = {"print-format", "no-print", "print-toolbar", "print-hide", "action-banner"}

PREFIX = "qr-"


def template_source():
	return TEMPLATE.read_text(encoding="utf-8")


def split_style(source):
	style = re.search(r"<style>(.*?)</style>", source, re.S)
	assert style, "template lost its <style> block"
	return style.group(1), source[style.end() :]


def strip_jinja(text):
	return re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", text, flags=re.S)


def offenders(names):
	return sorted(n for n in names if not n.startswith(PREFIX) and n not in FRAPPE_CLASSES)


def test_markup_uses_only_namespaced_classes():
	_, markup = split_style(template_source())
	used = set()
	for attr in re.findall(r'class="([^"]*)"', markup):
		# Some class attributes are built with Jinja — drop the tags, keep the
		# literal class tokens they wrap.
		used.update(strip_jinja(attr).split())
	assert used, "no class attributes found — did the template move?"
	assert not offenders(used), (
		f"bare class names in the markup: {offenders(used)}. "
		"Frappe's print bundle may style them; prefix them with 'qr-'."
	)


def test_stylesheet_targets_only_namespaced_classes():
	style, _ = split_style(template_source())
	selectors = style.split("{")[:-1]
	declared = set()
	for chunk in selectors:
		declared.update(re.findall(r"\.([a-zA-Z][\w-]*)", chunk.split("}")[-1]))
	assert declared, "no class selectors found — did the <style> block move?"
	assert not offenders(declared), f"bare class selectors in the stylesheet: {offenders(declared)}"


def test_label_class_is_not_reintroduced():
	# The specific collision that broke the parties block and boxed the total.
	# Markup only — the header comment names it on purpose.
	_, markup = split_style(template_source())
	assert 'class="label"' not in markup

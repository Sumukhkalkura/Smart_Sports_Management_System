from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def cell(value):
    """Render one attribute value of a tuple; SQL NULL is shown explicitly."""
    if value is None:
        return mark_safe('<span class="null">NULL</span>')
    if isinstance(value, bool):
        return format_html('<span class="bool">{}</span>', "true" if value else "false")
    if hasattr(value, "tzinfo") and getattr(value, "tzinfo", None) is not None:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S%z")
    if isinstance(value, Decimal):
        return str(value)
    return value


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def plan_line(line):
    """Highlight plan node names and actual timings in one line of EXPLAIN output."""
    import re

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    from dbms_lab.executor import PLAN_NODE_RE

    text = escape(line)
    head, sep, tail = text.partition("(")
    head = PLAN_NODE_RE.sub(r'<span class="node">\1</span>', head, count=1)
    tail = re.sub(r"(actual time=[\d.]+\.\.[\d.]+ rows=\d+ loops=\d+)", r'<span class="timing">\1</span>', tail)
    text = head + sep + tail
    text = re.sub(r"^(Planning Time:|Execution Time:)", r'<span class="timing">\1</span>', text)
    return mark_safe(text)

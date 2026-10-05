import os
from decimal import Decimal, InvalidOperation

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.filter
def num(value, places=2):
    """1234.5 -> '1,234.50'. Blank for None."""
    if value is None or value == '':
        return ''
    try:
        return f'{Decimal(value):,.{int(places)}f}'
    except (InvalidOperation, ValueError, TypeError):
        return value


@register.filter
def plain(value):
    """Decimal for an <input value>: no grouping, no trailing zeros."""
    if value is None or value == '':
        return ''
    text = format(Decimal(value).normalize(), 'f')
    return text


@register.filter
def at(seq, idx):
    try:
        return seq[idx]
    except (IndexError, KeyError, TypeError):
        return ''


@register.filter
def size_total(line, idx):
    return line.size_total(idx)


@register.filter
def fixed(value, places=2):
    """Decimal for an <input value> rounded to `places`, trailing zeros trimmed."""
    if value is None or value == '':
        return ''
    rounded = round(Decimal(value), int(places))
    return format(rounded.normalize(), 'f') if rounded else '0'


@register.simple_tag
def asset(path):
    """Static URL with the file's modified time as ?v=, so browsers pick up
    a changed CSS/JS file straight after a deploy instead of a cached one."""
    found = finders.find(path)
    version = int(os.path.getmtime(found)) if found else 0
    return f'{static(path)}?v={version}'

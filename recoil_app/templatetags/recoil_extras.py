from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()


@register.filter(name="fmt5")
def fmt5(value):
    if value is None or value == "":
        return "—"

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value

    quantized = number.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    return format(quantized, "f")
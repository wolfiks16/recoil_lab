import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter(name="index_or")
def index_or(seq, idx):
    """`seq[idx]`, либо None при ошибке.

    Поддерживает и список (числовой индекс), и словарь (строковый ключ).
    Шаблонная разметка не позволяет напрямую обращаться к dict с переменным ключом —
    отсюда и фильтр.
    """
    if seq is None:
        return None
    if isinstance(seq, dict):
        return seq.get(idx)
    try:
        return seq[int(idx)]
    except (TypeError, ValueError, IndexError, KeyError):
        try:
            return seq[idx]
        except Exception:  # noqa: BLE001
            return None


@register.filter(name="json_script_data", is_safe=True)
def json_script_data(value):
    """Сериализация значения как JSON для встраивания в <script type="application/json">.

    Простая обёртка над json.dumps с экранированием опасных подпоследовательностей,
    чтобы безопасно встроить в HTML без `</script>` injection.
    """
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("</", "<\\/").replace("<!--", "<\\!--")
    return mark_safe(text)


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

@register.filter(name="smart_num")
def smart_num(value):
    """Умное форматирование числа для отображения в UI:

    - None / "" → "—"
    - целые → "14 700 000" (с разделителями тысяч)
    - дробные → значимые знаки (до 6), без хвостовых нулей
    - очень маленькие или очень большие — научная нотация (1.23e-7)
    """
    if value is None or value == "":
        return "—"

    try:
        f = float(value)
    except (TypeError, ValueError):
        return value

    # Целое число — с разделителями тысяч (NBSP), без дробной части
    if f == int(f) and abs(f) < 1e15:
        n = int(f)
        # Разделитель — неразрывный пробел U+00A0
        sign = "-" if n < 0 else ""
        s = str(abs(n))
        # Группируем по 3 справа
        parts = []
        while s:
            parts.append(s[-3:])
            s = s[:-3]
        return sign + "\u00A0".join(reversed(parts))

    abs_f = abs(f)

    # Очень малые или очень большие — научная нотация
    if abs_f != 0 and (abs_f < 1e-4 or abs_f >= 1e7):
        # Формат с 4 значащими: 1.234e-05
        return f"{f:.4g}"

    # Обычное дробное — до 6 значащих знаков, обрезаем хвостовые нули
    # %g подбирает формат сам
    s = f"{f:.6g}"
    return s

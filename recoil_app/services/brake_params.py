"""Единое описание параметров вихретокового тормоза (подпись, символ, единица, группа).

Одно место правды для всех экранов, где показываются или вводятся 12 полей
`BrakeParametersMixin`: карточка каталога, страница результата, редактор тормоза.
"""

from __future__ import annotations

# (поле модели, подпись, символ, единица, группа)
PARAM_SPECS: list[tuple[str, str, str, str, str]] = [
    ("gamma", "Удельная проводимость шины", "γ", "(Ом·м)⁻¹", "material"),
    ("delta", "Толщина шины", "δ", "м", "material"),
    ("mu", "Магнитная проницаемость шины", "μ", "Гн/м", "material"),
    ("bz", "Индукция в рабочем зазоре", "B̄₃", "Тл", "material"),
    ("n", "Количество блоков", "N", "", "geometry"),
    ("xm", "Размер магнита по оси X", "x_m", "м", "geometry"),
    ("ym", "Размер магнита по оси Y", "y_m", "м", "geometry"),
    ("dh1", "Выступ 1-го края шины", "Δh₁", "м", "geometry"),
    ("dh2", "Выступ 2-го края шины", "Δh₂", "м", "geometry"),
    ("dm", "Промежуток между магнитами", "d_m", "м", "geometry"),
    ("lya", "Параметр λa", "λa", "", "extra"),
    ("wn0", "Начальное состояние wn", "w_n0", "", "extra"),
]

PARAM_GROUPS: list[tuple[str, str]] = [
    ("material", "Шина и магнитное поле"),
    ("geometry", "Геометрия магнитной системы"),
    ("extra", "Параметры модели"),
]

SPEC_BY_FIELD = {spec[0]: spec for spec in PARAM_SPECS}

# Ключевые параметры для краткой сводки тормоза (список расчётов, боковая панель).
SUMMARY_FIELDS = ("n", "bz", "delta", "gamma")

GEOMETRY_3D_FIELDS = ("n", "xm", "ym", "dh1", "dh2", "dm")


def param_rows(obj) -> list[dict]:
    """Строки «символ / подпись / значение / единица» для объекта с полями тормоза."""
    return [
        {"field": field, "label": label, "symbol": symbol, "unit": unit, "group": group,
         "value": getattr(obj, field, None)}
        for field, label, symbol, unit, group in PARAM_SPECS
    ]


def geometry_3d_available(brake) -> bool:
    """Хватает ли размеров для 3D-модели (та же проверка, что в charting.build_brake_geometry_3d)."""
    if getattr(brake, "model_type", None) != "parametric":
        return False
    values = [getattr(brake, f, None) for f in GEOMETRY_3D_FIELDS]
    if any(v is None for v in values):
        return False
    try:
        return int(brake.n) >= 1 and float(brake.xm) > 0 and float(brake.ym) > 0
    except (TypeError, ValueError):
        return False


# Короткие подсказки под полем (там, где символа и подписи мало).
PARAM_HINTS: dict[str, str] = {
    "n": "Число секций тормоза, целое ≥ 1",
    "lya": "Обычно 2.5",
    "wn0": "Начальное значение рекурсивного параметра, обычно 1",
}


def param_field_groups(form, fields: tuple[str, ...] | None = None) -> list[dict]:
    """Поля параметров тормоза из формы, сгруппированные для единого редактора.

    Работает с любой формой, где параметры названы как поля `BrakeParametersMixin`
    (расчёт, свободное падение, пошаговая сессия, каталог). Отсутствующие поля пропускаются.
    """
    wanted = set(fields) if fields else None
    groups = []
    for group_key, title in PARAM_GROUPS:
        items = []
        for field, label, symbol, unit, group in PARAM_SPECS:
            if group != group_key or field not in form.fields:
                continue
            if wanted is not None and field not in wanted:
                continue
            items.append({"bf": form[field], "symbol": symbol, "label": label, "unit": unit,
                          "hint": PARAM_HINTS.get(field, "")})
        if items:
            groups.append({"title": title, "fields": items})
    return groups

"""Пространство поиска Stage 2: что подбирается (в каком диапазоне), что зафиксировано.

Задаёт инженер в форме подбора (или флаги `design_brake`): каждый размер
конструкции либо подбирается в диапазоне [min, max], либо зафиксирован; число
блоков N — один вариант (зафиксировано) или набор вариантов; γ шины — число.
Параметры модели μ, λa, w_n0 всегда фиксированы.

Зафиксированный размер исключается только из ПОИСКА: в оценке робастности он
участвует, как и подбираемые (у купленного магнита B̄₃ тоже есть разброс).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from ..brake_params import FIXED_PARAM_DEFAULTS, PARAM_SPECS, SPEC_BY_FIELD

# Все непрерывные размеры конструкции (порядок вектора поиска и строк формы).
CONT_PARAMS = ("delta", "xm", "ym", "dh1", "dh2", "dm", "bz")

# Размеры, которые могут быть нулевыми (выступ края шины); остальные — строго > 0.
NONNEGATIVE_PARAMS = ("dh1", "dh2")

# Параметры модели, которые не подбираются никогда.
MODEL_FIXED = {"mu": 1.0, "lya": 2.5, "wn0": 1.0}

DEFAULT_GAMMA = 1.77e7
DEFAULT_BOUNDS = {
    "delta": (0.001, 0.008),
    "xm": (0.012, 0.035),
    "ym": (0.10, 0.75),
    "dh1": (0.008, 0.040),
    "dh2": (0.008, 0.040),
    "dm": (0.006, 0.030),
    "bz": (0.40, 2.00),
}
DEFAULT_N_CHOICES = (8, 10, 12, 14, 16, 18, 20, 24)
# Типовой тормоз — значение «зафиксировать» по умолчанию в форме (до «Подставить из донора»).
DEFAULT_FIXED_VALUES = {"delta": 0.006, "xm": 0.022, "ym": 0.55, "dh1": 0.02, "dh2": 0.02,
                        "dm": 0.014, "bz": 0.83, "n": 16}

# Больше вариантов N — подбор кратно дольше (подгон гоняется на каждый вариант).
MAX_N_CHOICES = 12

# Параметр «упёрся в границу», если до края диапазона меньше этой доли ширины.
BOUND_HIT_FRACTION = 0.01


@dataclass(slots=True)
class ParamSpace:
    """Границы конструкции для подбора.

    cont_bounds — диапазоны ПОДБИРАЕМЫХ непрерывных размеров {имя: (lo, hi)};
    n_choices   — варианты числа блоков N (один вариант = N зафиксирован);
    fixed       — всё остальное: зафиксированные размеры + γ, μ, λa, w_n0.
    Каждый размер из CONT_PARAMS — ровно в одном из cont_bounds / fixed.
    """

    cont_bounds: dict
    n_choices: tuple
    fixed: dict

    def __post_init__(self):
        self.cont_bounds = {k: (float(lo), float(hi)) for k, (lo, hi) in self.cont_bounds.items()}
        self.n_choices = tuple(sorted({int(n) for n in self.n_choices}))
        self.fixed = {k: float(v) for k, v in self.fixed.items()}
        for name in self.cont_bounds:
            if name not in CONT_PARAMS:
                raise ValueError(f"Неизвестный подбираемый параметр {name}.")
        for name in CONT_PARAMS:
            if (name in self.cont_bounds) == (name in self.fixed):
                raise ValueError(f"Параметр {name}: нужен либо диапазон, либо фиксированное значение.")
        for name, (lo, hi) in self.cont_bounds.items():
            if not lo < hi:
                raise ValueError(f"Параметр {name}: нижняя граница должна быть меньше верхней.")
        if not self.n_choices or self.n_choices[0] < 1:
            raise ValueError("Число блоков N: нужен хотя бы один вариант, N ≥ 1.")
        for name in ("gamma", *MODEL_FIXED):
            if name not in self.fixed:
                raise ValueError(f"Не задан фиксированный параметр {name}.")

    @classmethod
    def default(cls) -> "ParamSpace":
        return cls(cont_bounds=dict(DEFAULT_BOUNDS), n_choices=DEFAULT_N_CHOICES,
                   fixed={"gamma": DEFAULT_GAMMA, **MODEL_FIXED})

    @property
    def free_params(self) -> tuple:
        """Подбираемые непрерывные размеры в порядке CONT_PARAMS (= порядок вектора поиска)."""
        return tuple(p for p in CONT_PARAMS if p in self.cont_bounds)

    @property
    def n_fixed(self) -> bool:
        return len(self.n_choices) == 1

    def with_n_choices(self, n_choices) -> "ParamSpace":
        return ParamSpace(cont_bounds=dict(self.cont_bounds), n_choices=tuple(n_choices),
                          fixed=dict(self.fixed))

    def min_size(self, name: str) -> float:
        """Наименьшее возможное значение размера (нижняя граница или фиксированное значение)."""
        return self.cont_bounds[name][0] if name in self.cont_bounds else self.fixed[name]

    def to_dict(self) -> dict:
        return {"cont_bounds": {k: [lo, hi] for k, (lo, hi) in self.cont_bounds.items()},
                "n_choices": list(self.n_choices), "fixed": dict(self.fixed)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "ParamSpace":
        """Из `to_dict()` (снапшот, `DesignStudy.param_space`); пусто → по умолчанию."""
        if not data:
            return cls.default()
        return cls(cont_bounds={k: tuple(v) for k, v in data["cont_bounds"].items()},
                   n_choices=tuple(data["n_choices"]), fixed=dict(data["fixed"]))


def n_choices_range(n_min: int, n_max: int, step: int = 1) -> tuple:
    """Варианты N «от n_min до n_max с шагом step» (n_max входит, если попадает в шаг)."""
    return tuple(range(int(n_min), int(n_max) + 1, max(int(step), 1)))


def build_space(rows: dict, n_choices, gamma: float) -> ParamSpace:
    """Пространство из строк формы: rows = {имя: ("free", lo, hi) | ("fixed", value)}."""
    cont_bounds, fixed = {}, {"gamma": float(gamma), **MODEL_FIXED}
    for name in CONT_PARAMS:
        row = rows[name]
        if row[0] == "free":
            cont_bounds[name] = (row[1], row[2])
        else:
            fixed[name] = row[1]
    return ParamSpace(cont_bounds=cont_bounds, n_choices=tuple(n_choices), fixed=fixed)


def space_with_overrides(space: ParamSpace, *, bounds: dict | None = None, fixed: dict | None = None,
                         n_choices=None, gamma: float | None = None) -> ParamSpace:
    """Копия пространства с другими диапазонами/фиксацией (флаги `design_brake`)."""
    cont_bounds = dict(space.cont_bounds)
    fixed_all = dict(space.fixed)
    for name, (lo, hi) in (bounds or {}).items():
        fixed_all.pop(name, None)
        cont_bounds[name] = (lo, hi)
    for name, value in (fixed or {}).items():
        cont_bounds.pop(name, None)
        fixed_all[name] = value
    if gamma is not None:
        fixed_all["gamma"] = gamma
    return ParamSpace(cont_bounds=cont_bounds, fixed=fixed_all,
                      n_choices=tuple(n_choices) if n_choices else space.n_choices)


def bound_hits(params, space: ParamSpace) -> list:
    """Подбираемые параметры, оказавшиеся у края своего диапазона.

    [{"param", "side": "min"|"max", "value", "lo", "hi"}]. «Упёрся в максимум»
    значит, что подбор хотел бы выйти за границу: её стоит расширить.
    """
    hits = []
    for name in space.free_params:
        lo, hi = space.cont_bounds[name]
        value = float(getattr(params, name))
        edge = BOUND_HIT_FRACTION * (hi - lo)
        side = "min" if value <= lo + edge else "max" if value >= hi - edge else None
        if side:
            hits.append({"param": name, "side": side, "value": value, "lo": lo, "hi": hi})
    if not space.n_fixed:
        n, lo, hi = int(params.n), space.n_choices[0], space.n_choices[-1]
        side = "min" if n <= lo else "max" if n >= hi else None
        if side:
            hits.append({"param": "n", "side": side, "value": n, "lo": lo, "hi": hi})
    return hits


def bound_hits_message(hits_per_brake: list) -> str | None:
    """Одно сообщение о параметрах у границ (по всем тормозам) или None."""
    side_text = {"min": "минимума", "max": "максимума"}
    multi = len(hits_per_brake) > 1
    parts = []
    for i, hits in enumerate(hits_per_brake, start=1):
        for h in hits:
            prefix = f"тормоз {i}: " if multi else ""
            parts.append(f"{prefix}{SPEC_BY_FIELD[h['param']][2]} — у {side_text[h['side']]}")
    if not parts:
        return None
    return ("Подбор упёрся в границу диапазона (" + "; ".join(dict.fromkeys(parts)) + "). "
            "Если конструкция позволяет, расширьте этот диапазон.")


def brake_param_table(brakes: list, space: ParamSpace) -> list[dict]:
    """Строки таблицы подобранных тормозов на странице исследования (столбец на тормоз).

    Строка: символ/подпись/единица, диапазон подбора (`free`=False — параметр
    задан) и `cells` по тормозам: значение + `hit` = "min"/"max", если подбор
    упёрся в край диапазона. λa и w_n0 не показываются (как в редакторе тормоза).
    """
    hits = [{h["param"]: h["side"] for h in bound_hits(SimpleNamespace(**p), space)} for p in brakes]
    rows = []
    for field, label, symbol, unit, _group in PARAM_SPECS:
        if field in FIXED_PARAM_DEFAULTS:
            continue
        if field in space.cont_bounds:
            lo, hi = space.cont_bounds[field]
        elif field == "n" and not space.n_fixed:
            lo, hi = space.n_choices[0], space.n_choices[-1]
        else:
            lo = hi = None
        rows.append({"field": field, "symbol": symbol, "label": label, "unit": unit,
                     "free": lo is not None, "lo": lo, "hi": hi,
                     "cells": [{"value": p.get(field), "hit": h.get(field)}
                               for p, h in zip(brakes, hits)]})
    return rows


def donor_brake_values(run) -> list:
    """Значения параметрических тормозов донора — для кнопки «Подставить из расчёта-донора»."""
    fields = (*CONT_PARAMS, "n", "gamma")
    out = []
    for brake in run.brakes.filter(model_type="parametric").order_by("index"):
        values = {f: getattr(brake, f) for f in fields}
        if any(v is None for v in values.values()):
            continue
        out.append({"index": brake.index, "name": brake.name or f"Тормоз {brake.index}",
                    "values": {f: (int(v) if f == "n" else float(v)) for f, v in values.items()}})
    return out

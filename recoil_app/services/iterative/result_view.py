"""Этапы на странице итогового расчёта (`run_detail_v2`): таблицы из `BrakeStage`.

- stages — точки переключения (откат/накат), состав тормозов, изменения;
- brakes — по каждому тормозу параметры во всех этапах (строки — параметры,
  столбцы — этапы) с отметкой ячеек, изменившихся относительно прошлого этапа.
Работает и для расчётов, сохранённых до появления overlay на графиках: всё
берётся из БД.
"""

from __future__ import annotations

from ...models import BrakeStage, CalculationRun, IterativeCalc
from ..magnetic import MagneticParams
from .config import KIND_LABELS, config_diff, config_from_list, curve_summary, slot_kind

PARAM_LABELS = [
    ("gamma", "γ"), ("delta", "δ"), ("xm", "x_m"), ("ym", "y_m"), ("dh1", "Δh₁"), ("dh2", "Δh₂"),
    ("dm", "d_m"), ("n", "N"), ("mu", "μ"), ("bz", "B̄₃"), ("lya", "λ_a"), ("wn0", "w_n0"),
]


def _state_text(slot) -> str:
    kind = slot_kind(slot)
    if kind == "curve":
        return f"{KIND_LABELS[kind]} · {curve_summary(slot)}"
    return KIND_LABELS[kind]


def build_stage_tables(run: CalculationRun) -> dict | None:
    stages = list(BrakeStage.objects.filter(run=run).order_by("stage"))
    if not stages:
        return None
    configs = [config_from_list(s.config) for s in stages]
    n_slots = max(len(c) for c in configs)
    configs = [tuple(c) + (None,) * (n_slots - len(c)) for c in configs]

    stage_rows = []
    for k, (stage, config) in enumerate(zip(stages, configs)):
        stage_rows.append({
            "index": stage.stage,
            "x": stage.x_switch, "t": stage.t_forward, "v": stage.v_forward,
            "return_t": stage.t_return, "return_v": stage.v_return,
            "kinds": [KIND_LABELS[slot_kind(s)] for s in config],
            "changes": config_diff(configs[k - 1], config) if k > 0 else [],
        })

    brakes = []
    for b in range(n_slots):
        slots = [config[b] for config in configs]
        rows = [{
            "label": "состояние",
            "cells": [
                {"value": _state_text(slot), "text": True,
                 "changed": k > 0 and slot != slots[k - 1]}
                for k, slot in enumerate(slots)
            ],
        }]
        changed_params = []
        for field, label in PARAM_LABELS:
            values = [getattr(slot, field) if isinstance(slot, MagneticParams) else None for slot in slots]
            cells = [
                {"value": value, "changed": k > 0 and value != values[k - 1]
                 and value is not None and values[k - 1] is not None}
                for k, value in enumerate(values)
            ]
            if any(c["changed"] for c in cells):
                changed_params.append(label)
            rows.append({"label": label, "cells": cells})
        brakes.append({
            "number": b + 1,
            "rows": rows,
            "changed_params": changed_params,
            "state_changed": any(c["changed"] for c in rows[0]["cells"]),
        })

    return {
        "stages": stage_rows,
        "stage_numbers": [s.stage for s in stages],
        "brakes": brakes,
        "is_free_fall": run.is_free_fall,
    }


def session_for_run(run: CalculationRun) -> IterativeCalc | None:
    """Сессия, из которой сохранён итоговый расчёт (если её не удалили)."""
    return IterativeCalc.objects.filter(result_run=run).first()

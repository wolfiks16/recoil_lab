"""Описание этапов итога итерационного расчёта — для графиков и Excel-отчёта.

`build_stage_overlay(outcome)` — простые словари/списки, чтобы `charting` и
`reporting` рисовали этапы, ничего не зная про `services/iterative`:
  segments — интервалы времени, где действовал этап (этап k на откате и на
             накате — два интервала);
  x_bands  — этап как функция положения: этап k на [x_k, x_{k+1}) (последний —
             до x_max) — полосы на v(x);
  events   — переключения (t, x, v, направление, из какого этапа в какой);
  stages   — точки и конфигурации этапов с изменениями — для листов Excel;
  stage_index — номер этапа в каждой точке временного ряда.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np

from ..magnetic import MagneticParams
from .config import KIND_LABELS, config_diff, curve_summary, slot_kind
from .session import IterativeOutcome


def _segments(t: np.ndarray, stage_index: np.ndarray) -> list[dict]:
    segments = []
    start = 0
    for i in range(1, len(stage_index) + 1):
        if i == len(stage_index) or stage_index[i] != stage_index[start]:
            segments.append({"t0": float(t[start]), "t1": float(t[i - 1]), "stage": int(stage_index[start])})
            start = i
    return segments


def _brake_rows(config) -> list[dict]:
    rows = []
    for k, slot in enumerate(config):
        kind = slot_kind(slot)
        rows.append({
            "number": k + 1,
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "params": asdict(slot) if isinstance(slot, MagneticParams) else None,
            "curve": curve_summary(slot) if kind == "curve" else "",
            "points": [[p.velocity, p.force] for p in slot.points] if kind == "curve" else None,
        })
    return rows


def build_stage_overlay(outcome: IterativeOutcome) -> dict:
    result = outcome.result
    stage_index = np.asarray(outcome.stage_index, dtype=int)
    stages = outcome.stages

    x_bands = []
    x_max = float(np.max(result.x)) if len(result.x) else 0.0
    for k in range(1, len(stages)):
        x0 = stages[k].x
        x1 = stages[k + 1].x if k + 1 < len(stages) else x_max
        if x0 is not None and x1 is not None and x1 > x0:
            x_bands.append({"x0": float(x0), "x1": float(x1), "stage": k})

    return {
        "segments": _segments(result.t, stage_index),
        "x_bands": x_bands,
        "events": [
            {"t": e.t, "x": e.x, "v": e.v, "direction": e.direction,
             "stage_from": e.stage_from, "stage_to": e.stage_to, "row": e.row}
            for e in outcome.switch_events
        ],
        "stages": [
            {
                "stage": s.index,
                "x": s.x, "t": s.t, "v": s.v,
                "return_t": s.return_t, "return_v": s.return_v,
                "changes": config_diff(stages[s.index - 1].config, s.config) if s.index > 0 else [],
                "brakes": _brake_rows(s.config),
            }
            for s in stages
        ],
        "stage_index": stage_index,
    }

"""Опорная характеристика тормозов F(|v|) для графика «Сила торможения от скорости».

График комбинированный: главная линия — то, что ПОСЧИТАНО (|F|(|v|) из шагов
интегрирования), фон — характеристика конфигурации тормозов из МОДЕЛИ
(параметрический — установившаяся сила `magnetic_force_quasistatic`, табличный —
сама таблица). Здесь считается фон и проверка расхождения: если расчёт где-то
отходит от характеристики больше чем на 1 % (переходный процесс тормоза — память
wn, A > 1 %), график ставит пометку. На скоростях отката расхождение ≈ 0
(проверено на #94: 0 Н в 12 626 точках).

`charting` о моделях тормозов не знает — получает готовые кривые и расхождение.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams, magnetic_force_quasistatic

GRID_POINTS = 1500
DEVIATION_WARN = 0.01            # пометка на графике, если расчёт отходит от характеристики > 1 %
DEVIATION_MIN_FRACTION = 0.02    # не сравнивать у нуля: где характеристика < 2 % максимума
MAX_MARKED_POINTS = 400


def _slot_force(slot, grid: np.ndarray) -> np.ndarray:
    """Сила одного тормоза на сетке |v|. У табличного за пределами таблицы — NaN (не экстраполируем)."""
    if slot is None:
        return np.zeros_like(grid)
    if isinstance(slot, MagneticParams):
        return np.array([magnetic_force_quasistatic(float(v), slot) for v in grid])
    vs = np.array([p.velocity for p in slot.points], dtype=float)
    fs = np.array([p.force for p in slot.points], dtype=float)
    out = np.interp(grid, vs, fs)
    out[(grid < vs[0]) | (grid > vs[-1])] = np.nan
    return out


def _grid(config, v_top: float) -> np.ndarray:
    """Равномерная сетка + узлы таблиц (чтобы изломы табличной F(v) не сглаживались)."""
    nodes = [np.linspace(0.0, v_top, GRID_POINTS)]
    for slot in config:
        if isinstance(slot, CurveBrakeParams):
            nodes.append(np.array([p.velocity for p in slot.points if p.velocity <= v_top], dtype=float))
    return np.unique(np.concatenate(nodes))


def build_fv_reference(result, configs: Sequence[Sequence], stage_index=None) -> dict:
    """Характеристики конфигураций + расхождение расчёта с ними.

    configs — конфигурации (списки моделей/None) по этапам; у обычного расчёта — одна.
    stage_index — этап каждой точки расчёта (None → все точки — конфигурация 0).
    """
    v_abs = np.abs(np.asarray(result.v, dtype=float))
    f_calc = np.abs(np.asarray(result.f_magnetic, dtype=float))
    n = len(v_abs)
    stage_index = np.zeros(n, dtype=int) if stage_index is None else np.asarray(stage_index, dtype=int)
    v_top = float(v_abs.max()) * 1.05 if n and v_abs.max() > 0 else 1.0

    curves = []
    f_model = np.full(n, np.nan)
    for k, config in enumerate(configs):
        grid = _grid(config, v_top)
        total = np.sum([_slot_force(slot, grid) for slot in config], axis=0) if len(config) else np.zeros_like(grid)
        valid = np.isfinite(total)
        if not valid.any():
            continue
        curves.append({"stage": k, "v": grid[valid].tolist(), "f": total[valid].tolist()})
        rows = stage_index == k
        if rows.any():
            inside = rows & (v_abs <= grid[valid][-1])
            f_model[inside] = np.interp(v_abs[inside], grid[valid], total[valid])

    considered = np.isfinite(f_model)
    if considered.any():
        considered &= f_model > DEVIATION_MIN_FRACTION * np.nanmax(f_model)
    rel = np.zeros(n)
    rel[considered] = np.abs(f_calc[considered] - f_model[considered]) / f_model[considered]
    flagged = np.flatnonzero(rel > DEVIATION_WARN)
    if len(flagged) > MAX_MARKED_POINTS:
        flagged = flagged[np.linspace(0, len(flagged) - 1, MAX_MARKED_POINTS).astype(int)]
    return {
        "curves": curves,
        "deviation": {"max_rel": float(rel.max()) if n else 0.0, "rows": flagged.tolist()},
    }


def configs_from_stage_overlay(stage_overlay: dict) -> list[list]:
    """Конфигурации этапов из описания этапов итерационного расчёта (`build_stage_overlay`)."""
    configs = []
    for stage in stage_overlay["stages"]:
        config = []
        for brake in stage["brakes"]:
            if brake["kind"] == "parametric":
                config.append(MagneticParams(**brake["params"]))
            elif brake["kind"] == "curve":
                config.append(CurveBrakeParams(points=tuple(
                    ForceCurvePoint(velocity=float(v), force=float(f)) for v, f in brake["points"])))
            else:
                config.append(None)
        configs.append(config)
    return configs

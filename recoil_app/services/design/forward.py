"""Прямая модель для обратной задачи: кривая-кандидат F(v) → метрики цикла.

Обёртка над `simulate_recoil_core` (привод предзагружен один раз в study.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..dynamics import RecoilParams, simulate_recoil_core
from ..magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams


@dataclass(slots=True)
class Metrics:
    """Метрики одного прогона модели."""

    x_max: float
    T: float | None            # время цикла; None если накат не завершился (x=0 не достигнут)
    v_end: float | None        # |v| в момент x=0; None если не завершился
    sigma_f_peak: float        # max_t |ΣF(t)|
    completed: bool


# Привод — кортеж (ext_force, spring_force, t_ext_max, x_range), как из load_recoil_characteristics.
Drive = tuple


def build_curve(v_nodes, f_nodes) -> CurveBrakeParams:
    """Строит табличный тормоз из узлов. Силы клиппируются в ≥0 (для перт. робастности)."""
    points = tuple(
        ForceCurvePoint(velocity=float(v), force=max(0.0, float(f)))
        for v, f in zip(v_nodes, f_nodes)
    )
    return CurveBrakeParams(points=points)


def _metrics_from_result(res) -> Metrics:
    x_max = float(np.max(res.x)) if len(res.x) else 0.0
    sigma_f_peak = float(np.max(np.abs(res.f_magnetic))) if len(res.f_magnetic) else 0.0
    if res.return_end_time is not None:
        return Metrics(x_max=x_max, T=float(res.return_end_time),
                       v_end=abs(float(res.v[-1])), sigma_f_peak=sigma_f_peak, completed=True)
    return Metrics(x_max=x_max, T=None, v_end=None, sigma_f_peak=sigma_f_peak, completed=False)


_FAILED = Metrics(x_max=float("nan"), T=None, v_end=None,
                  sigma_f_peak=float("nan"), completed=False)


def evaluate(drive: Drive, base: RecoilParams, v_nodes, f_nodes) -> Metrics:
    """Прогоняет модель с curve-тормозом из (v_nodes, f_nodes) и снимает метрики.

    Любая ошибка расчёта (например, скорость вышла за диапазон кривой) трактуется
    как «не завершившийся» прогон — оптимизатор получит штраф, а не исключение.
    """
    ext_force, spring_force, t_ext_max, x_range = drive
    try:
        brake = build_curve(v_nodes, f_nodes)
        res = simulate_recoil_core(ext_force, spring_force, t_ext_max, x_range, base, [brake])
    except ValueError:
        return _FAILED
    return _metrics_from_result(res)


def evaluate_brakes(drive: Drive, base: RecoilParams, brake_list) -> Metrics:
    """Прогон модели с произвольным СПИСКОМ тормозов (одним или несколькими).

    Динамика видит суммарную силу; sigma_f_peak = max_t |ΣF(t)| — это и есть
    величина под потолком ΣF_max при любом числе тормозов.
    """
    ext_force, spring_force, t_ext_max, x_range = drive
    try:
        res = simulate_recoil_core(ext_force, spring_force, t_ext_max, x_range, base, list(brake_list))
    except ValueError:
        return _FAILED
    return _metrics_from_result(res)


def evaluate_parametric(drive: Drive, base: RecoilParams, params: MagneticParams) -> Metrics:
    """Один параметрический тормоз (полная переходная динамика wn). Stage 2."""
    return evaluate_brakes(drive, base, [params])

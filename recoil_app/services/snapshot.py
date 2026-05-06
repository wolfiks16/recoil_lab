"""Извлечение частей `CalculationSnapshot` для презентационных слоёв.

Snapshot хранится как JSON. View'хи и сервисы работают с разными частями:
страница результата — phase_analysis / characteristic_points / engineering_metrics;
overlay-сравнение — timeline + forces + phases.
"""

from __future__ import annotations

from ..models import CalculationRun, CalculationSnapshot


def extract_snapshot_parts(run: CalculationRun) -> dict:
    """Достаёт `phase_analysis`, `characteristic_points`, `engineering_metrics`.

    Если у расчёта нет snapshot'а — возвращает пустые словари.
    """
    phase_analysis: dict = {}
    characteristic_points: dict = {}
    engineering_metrics: dict = {}

    try:
        snapshot = run.snapshot
        analysis_snapshot = snapshot.analysis_snapshot or {}
        phase_analysis = analysis_snapshot.get("phase_analysis", {})
        characteristic_points = analysis_snapshot.get("characteristic_points", {})
        engineering_metrics = analysis_snapshot.get("engineering_metrics", {})
    except CalculationSnapshot.DoesNotExist:
        pass

    return {
        "phase_analysis": phase_analysis,
        "characteristic_points": characteristic_points,
        "engineering_metrics": engineering_metrics,
    }


def extract_overlay_data(run: CalculationRun) -> dict:
    """Timeline + ключевые индексы из result_snapshot для overlay-графиков сравнения.

    Возвращает словарь:
        t, x, v, a — временные ряды
        f_magnetic — суммарная магнитная сила (по времени)
        t_recoil_end — момент разворота (для vline на графике)
        recoil_end_index — индекс точки разворота в массиве t
    """
    out: dict = {
        "t": [], "x": [], "v": [], "a": [],
        "f_magnetic": [],
        "t_recoil_end": None,
        "recoil_end_index": None,
    }
    try:
        snap = run.snapshot
    except CalculationSnapshot.DoesNotExist:
        return out

    rs = snap.result_snapshot or {}
    timeline = rs.get("timeline") or {}
    out["t"] = timeline.get("t") or []
    out["x"] = timeline.get("x") or []
    out["v"] = timeline.get("v") or []
    out["a"] = timeline.get("a") or []

    forces = rs.get("forces") or {}
    out["f_magnetic"] = forces.get("magnetic_sum") or []

    phases = rs.get("phases") or {}
    recoil = phases.get("recoil") or {}
    out["t_recoil_end"] = recoil.get("end_time")
    out["recoil_end_index"] = recoil.get("end_index")

    return out

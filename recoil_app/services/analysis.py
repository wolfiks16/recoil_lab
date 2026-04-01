from __future__ import annotations

from dataclasses import asdict
from typing import Any


def _safe_min(values: list[float]) -> float | None:
    return min(values) if values else None


def _safe_max(values: list[float]) -> float | None:
    return max(values) if values else None


def _safe_abs_max(values: list[float]) -> float | None:
    return max((abs(v) for v in values), default=None)


def _argmax(values: list[float]) -> int | None:
    if not values:
        return None
    return max(range(len(values)), key=lambda i: values[i])


def _argmin(values: list[float]) -> int | None:
    if not values:
        return None
    return min(range(len(values)), key=lambda i: values[i])


def _slice_by_phase(model, phase_key: str) -> tuple[list[float], list[float], list[float], list[float], list[int]]:
    phase = model.phases.get(phase_key)
    if not phase or phase.start_index is None or phase.end_index is None:
        return [], [], [], [], []

    start_idx = max(0, phase.start_index)
    end_idx = max(start_idx, phase.end_index)

    t = model.timeline["t"][start_idx:end_idx + 1]
    x = model.timeline["x"][start_idx:end_idx + 1]
    v = model.timeline["v"][start_idx:end_idx + 1]
    a = model.timeline["a"][start_idx:end_idx + 1]
    indices = list(range(start_idx, end_idx + 1))
    return t, x, v, a, indices


def _build_phase_summary(model, phase_key: str) -> dict[str, Any]:
    t, x, v, a, indices = _slice_by_phase(model, phase_key)

    if not t:
        return {
            "phase": phase_key,
            "available": False,
        }

    return {
        "phase": phase_key,
        "available": True,
        "start_index": indices[0],
        "end_index": indices[-1],
        "start_time": t[0],
        "end_time": t[-1],
        "duration": t[-1] - t[0],
        "x_min": _safe_min(x),
        "x_max": _safe_max(x),
        "v_min": _safe_min(v),
        "v_max": _safe_max(v),
        "a_min": _safe_min(a),
        "a_max": _safe_max(a),
        "v_abs_max": _safe_abs_max(v),
        "a_abs_max": _safe_abs_max(a),
    }


def _build_characteristic_points(model) -> dict[str, Any]:
    t = model.timeline["t"]
    x = model.timeline["x"]
    v = model.timeline["v"]
    a = model.timeline["a"]

    if not t:
        return {}

    x_max_idx = _argmax(x)
    v_max_idx = _argmax(v)
    v_min_idx = _argmin(v)
    a_max_idx = _argmax(a)
    a_min_idx = _argmin(a)

    points: dict[str, Any] = {}

    if x_max_idx is not None:
        points["x_max"] = {
            "index": x_max_idx,
            "time": t[x_max_idx],
            "value": x[x_max_idx],
        }

    if v_max_idx is not None:
        points["v_max"] = {
            "index": v_max_idx,
            "time": t[v_max_idx],
            "value": v[v_max_idx],
        }

    if v_min_idx is not None:
        points["v_min"] = {
            "index": v_min_idx,
            "time": t[v_min_idx],
            "value": v[v_min_idx],
        }

    if a_max_idx is not None:
        points["a_max"] = {
            "index": a_max_idx,
            "time": t[a_max_idx],
            "value": a[a_max_idx],
        }

    if a_min_idx is not None:
        points["a_min"] = {
            "index": a_min_idx,
            "time": t[a_min_idx],
            "value": a[a_min_idx],
        }

    if model.phases.get("recoil") and model.phases["recoil"].end_index is not None:
        idx = model.phases["recoil"].end_index
        points["recoil_end"] = {
            "index": idx,
            "time": t[idx],
            "x": x[idx],
            "v": v[idx],
            "a": a[idx],
        }

    if model.phases.get("return") and model.phases["return"].end_index is not None:
        idx = model.phases["return"].end_index
        points["return_end"] = {
            "index": idx,
            "time": t[idx],
            "x": x[idx],
            "v": v[idx],
            "a": a[idx],
        }

    return points


def _build_basic_engineering_metrics(model) -> dict[str, Any]:
    t = model.timeline["t"]
    x = model.timeline["x"]
    v = model.timeline["v"]
    a = model.timeline["a"]

    if not t:
        return {}

    return {
        "total_duration": t[-1] - t[0],
        "x_range": {
            "min": _safe_min(x),
            "max": _safe_max(x),
            "span": (_safe_max(x) - _safe_min(x)) if x else None,
        },
        "v_range": {
            "min": _safe_min(v),
            "max": _safe_max(v),
            "span": (_safe_max(v) - _safe_min(v)) if v else None,
            "abs_max": _safe_abs_max(v),
        },
        "a_range": {
            "min": _safe_min(a),
            "max": _safe_max(a),
            "span": (_safe_max(a) - _safe_min(a)) if a else None,
            "abs_max": _safe_abs_max(a),
        },
        "phase_count": {
            "recoil": 1 if model.phases.get("recoil") and model.phases["recoil"].available else 0,
            "return": 1 if model.phases.get("return") and model.phases["return"].available else 0,
        },
    }


def enrich_with_basic_analysis(model):
    recoil_summary = _build_phase_summary(model, "recoil")
    return_summary = _build_phase_summary(model, "return")
    characteristic_points = _build_characteristic_points(model)
    engineering_metrics = _build_basic_engineering_metrics(model)

    analysis_snapshot = {
        "phase_analysis": {
            "recoil": recoil_summary,
            "return": return_summary,
        },
        "characteristic_points": characteristic_points,
        "engineering_metrics": engineering_metrics,
        "diagnostics": asdict(model.diagnostics),
    }

    return model, analysis_snapshot
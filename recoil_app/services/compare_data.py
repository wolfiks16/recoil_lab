"""Подготовка данных для страницы сравнения двух расчётов.

Overlay-графики двух уровней (Общие / Откат / Накат, как на странице результата)
и дельта-таблица 12 метрик. Графики строит `services.charting`, эта прослойка
только собирает входные данные и проводит их в нужный шаблон фрагмента.
"""

from __future__ import annotations

from ..models import CalculationRun
from .charting import (
    has_phase,
    make_compare_fmag_v_fragment,
    make_compare_forces_main_recoil_fragment,
    make_compare_forces_secondary_fragment,
    make_compare_v_a_t_fragment,
    make_compare_v_a_t_phase_fragment,
    make_compare_v_x_fragment,
    make_compare_x_t_fragment,
    make_compare_x_t_phase_fragment,
)
from .snapshot import extract_overlay_data, extract_snapshot_parts


def build_compare_overlay_charts(run_a: CalculationRun, run_b: CalculationRun) -> dict:
    """Вложенная структура overlay-фрагментов:

        {
          "common": {x_t, v_a_t, v_x, fmag_v, forces_secondary},
          "recoil": {x_t, v_a_t, forces_main, forces_secondary},   # если есть фаза
          "return": {x_t, v_a_t, forces_secondary},                # если есть фаза
          "has_recoil": bool,
          "has_return": bool,
        }

    Фазовые наборы пишутся только если хотя бы у одного из расчётов есть данные
    для фазы — иначе пустые табы не показываются.
    """
    snap_a = extract_overlay_data(run_a)
    snap_b = extract_overlay_data(run_b)
    name_a = run_a.name or f"#{run_a.id}"
    name_b = run_b.name or f"#{run_b.id}"

    out: dict = {
        "common": {
            "x_t":               make_compare_x_t_fragment(snap_a, snap_b, name_a, name_b),
            "v_a_t":             make_compare_v_a_t_fragment(snap_a, snap_b, name_a, name_b),
            "v_x":               make_compare_v_x_fragment(snap_a, snap_b, name_a, name_b),
            "fmag_v":            make_compare_fmag_v_fragment(snap_a, snap_b, name_a, name_b),
            "forces_secondary":  make_compare_forces_secondary_fragment(snap_a, snap_b, name_a, name_b),
        },
    }

    has_rec = has_phase(snap_a, "recoil") or has_phase(snap_b, "recoil")
    has_ret = has_phase(snap_a, "return") or has_phase(snap_b, "return")
    out["has_recoil"] = has_rec
    out["has_return"] = has_ret

    if has_rec:
        out["recoil"] = {
            "x_t":              make_compare_x_t_phase_fragment(snap_a, snap_b, name_a, name_b, "recoil"),
            "v_a_t":            make_compare_v_a_t_phase_fragment(snap_a, snap_b, name_a, name_b, "recoil"),
            "forces_main":      make_compare_forces_main_recoil_fragment(snap_a, snap_b, name_a, name_b),
            "forces_secondary": make_compare_forces_secondary_fragment(snap_a, snap_b, name_a, name_b, phase="recoil"),
        }
    if has_ret:
        out["return"] = {
            "x_t":              make_compare_x_t_phase_fragment(snap_a, snap_b, name_a, name_b, "return"),
            "v_a_t":            make_compare_v_a_t_phase_fragment(snap_a, snap_b, name_a, name_b, "return"),
            "forces_secondary": make_compare_forces_secondary_fragment(snap_a, snap_b, name_a, name_b, phase="return"),
        }

    return out


def build_compare_metrics_table(run_a: CalculationRun, run_b: CalculationRun) -> list[dict]:
    """Дельта-таблица KPI: 12 строк со значениями A/B и относительными отклонениями.

    Каждая строка: {label, unit, value_a, value_b, delta_abs, delta_pct, direction}.
    direction: 'up' | 'down' | 'eq' | 'none'.
    """
    snap_a_parts = extract_snapshot_parts(run_a)
    snap_b_parts = extract_snapshot_parts(run_b)

    pa = snap_a_parts.get("phase_analysis", {}) or {}
    pb = snap_b_parts.get("phase_analysis", {}) or {}
    chars_a = snap_a_parts.get("characteristic_points", {}) or {}
    chars_b = snap_b_parts.get("characteristic_points", {}) or {}
    eng_a = snap_a_parts.get("engineering_metrics", {}) or {}
    eng_b = snap_b_parts.get("engineering_metrics", {}) or {}

    rec_a = (pa.get("recoil") or {}) if isinstance(pa, dict) else {}
    rec_b = (pb.get("recoil") or {}) if isinstance(pb, dict) else {}
    ret_a = (pa.get("return") or {}) if isinstance(pa, dict) else {}
    ret_b = (pb.get("return") or {}) if isinstance(pb, dict) else {}

    rows: list[tuple[str, str, object, object]] = [
        ("Макс. перемещение",       "м",   run_a.x_max,                      run_b.x_max),
        ("Макс. скорость",          "м/с", _nested_value(chars_a, "v_max"),  _nested_value(chars_b, "v_max")),
        ("Время отката",            "с",   run_a.recoil_end_time,            run_b.recoil_end_time),
        ("Время цикла",             "с",   run_a.return_end_time,            run_b.return_end_time),
        ("Энергия подведенная",     "Дж",  run_a.energy_input_total,         run_b.energy_input_total),
        ("Энергия рассеянная",      "Дж",  run_a.energy_brake_total,         run_b.energy_brake_total),
        ("Невязка энергобаланса",   "%",   run_a.energy_residual_pct,        run_b.energy_residual_pct),
        ("Откат: x_max",            "м",   rec_a.get("x_max"),               rec_b.get("x_max")),
        ("Откат: v_max",            "м/с", rec_a.get("v_max"),               rec_b.get("v_max")),
        ("Откат: a_max",            "м/с²", rec_a.get("a_max"),              rec_b.get("a_max")),
        ("Накат: v_max",            "м/с", ret_a.get("v_max"),               ret_b.get("v_max")),
        ("Накат: a_max",            "м/с²", ret_a.get("a_max"),              ret_b.get("a_max")),
    ]

    table: list[dict] = []
    for label, unit, va, vb in rows:
        try:
            fa = float(va) if va is not None else None
            fb = float(vb) if vb is not None else None
        except (TypeError, ValueError):
            fa = fb = None

        if fa is None or fb is None:
            delta_abs = None
            delta_pct = None
            direction = "none"
        else:
            delta_abs = fb - fa
            if fa != 0:
                delta_pct = (fb - fa) / abs(fa) * 100.0
            else:
                delta_pct = None
            if abs(delta_abs) < 1e-9:
                direction = "eq"
            elif delta_abs > 0:
                direction = "up"
            else:
                direction = "down"

        table.append({
            "label":     label,
            "unit":      unit,
            "value_a":   fa,
            "value_b":   fb,
            "delta_abs": delta_abs,
            "delta_pct": delta_pct,
            "direction": direction,
        })

    return table


def _nested_value(d: dict, key: str):
    """В characteristic_points значения хранятся как {value, time}; берём value."""
    v = d.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v

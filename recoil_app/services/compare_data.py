"""Подготовка данных для страницы сравнения двух расчётов.

Ключевые показатели A/B с разницей, осциллограмма A/B на общей оси времени,
v(x) и |F|(|v|) (все графики — из прореженных snapshot'ов, как на странице
результата) и подробная дельта-таблица 12 метрик. Графики строит
`services.charting`, здесь только сборка данных.
"""

from __future__ import annotations

import json

import numpy as np
import plotly.io as pio

from ..models import CalculationRun
from .charting import make_compare_oscillogram_figure, make_compare_phase_figures
from .result_page import G, build_oscillogram_data, fmt_number, load_series
from .snapshot import extract_snapshot_parts


def _key_metrics(run: CalculationRun, series: dict | None) -> dict:
    """Числовые ключевые показатели расчёта (None — нет данных)."""
    out = {"x_max": None, "v_max": None, "a_max": None, "f_max": None,
           "T": run.return_end_time, "v_end": None, "resid": run.energy_residual_pct}
    if series is not None:
        out["x_max"] = float(np.max(series["x"])) * 1000.0
        out["v_max"] = float(np.max(np.abs(series["v"])))
        out["a_max"] = float(np.max(np.abs(series["a"]))) / G
        out["f_max"] = float(np.max(series["f"])) / 1000.0
        idx = series["return_end_index"]
        if idx is not None:
            out["v_end"] = abs(float(series["v"][min(idx, len(series["v"]) - 1)]))
    elif run.x_max is not None:
        out["x_max"] = run.x_max * 1000.0
    if run.is_free_fall and run.v_final is not None:
        out["v_end"] = abs(run.v_final)
    return out


KEY_ROWS = [
    ("x_max", "Максимальный откат", "мм", 1, "x"),
    ("v_max", "Максимальная скорость", "м/с", 3, "v"),
    ("a_max", "Пиковое ускорение", "g", 1, "a"),
    ("f_max", "Сила торможения, максимум", "кН", 2, "f"),
    ("T", "Время цикла", "с", 3, ""),
    ("v_end", "Скорость в конце", "м/с", 3, ""),
    ("resid", "Невязка энергобаланса", "%", 2, ""),
]


def build_compare_page(run_a: CalculationRun, run_b: CalculationRun) -> dict:
    """Сравнение: ключевые показатели A/B с разницей + осциллограмма A/B + v(x), |F|(|v|).

    Графики — из snapshot'ов, прореженных как на странице результата (лёгкие).
    Расчёт без snapshot'а (архивный) — только показатели из полей модели.
    """
    series_a, series_b = load_series(run_a), load_series(run_b)
    ma, mb = _key_metrics(run_a, series_a), _key_metrics(run_b, series_b)

    key_rows = []
    for key, label, unit, digits, quantity in KEY_ROWS:
        a, b = ma[key], mb[key]
        if a is None and b is None:
            continue
        delta = b - a if a is not None and b is not None else None
        pct = delta / abs(a) * 100.0 if delta is not None and a else None
        key_rows.append({
            "label": label, "unit": unit, "quantity": quantity,
            "a": fmt_number(a, digits), "b": fmt_number(b, digits),
            "delta": ("+" if delta is not None and delta > 0 else "") + fmt_number(delta, digits) if delta is not None else "—",
            "pct": ("+" if pct is not None and pct > 0 else "") + fmt_number(pct, 1) + " %" if pct is not None else "",
            "same": delta is not None and abs(delta) < 0.5 * 10.0 ** -digits,
        })

    osc_figure = phase_vx = phase_fv = None
    osc_a = build_oscillogram_data(run_a, series_a)
    osc_b = build_oscillogram_data(run_b, series_b)
    if osc_a is not None and osc_b is not None:
        name_a, name_b = f"A: {run_a.name}", f"B: {run_b.name}"
        to_dict = lambda fig: json.loads(pio.to_json(fig, validate=False))  # noqa: E731
        osc_figure = to_dict(make_compare_oscillogram_figure(osc_a, osc_b, name_a, name_b))
        vx, fv = make_compare_phase_figures(osc_a, osc_b, name_a, name_b)
        phase_vx, phase_fv = to_dict(vx), to_dict(fv)

    missing = [r.name for r, s in ((run_a, series_a), (run_b, series_b)) if s is None]
    return {
        "key_rows": key_rows,
        "osc_figure": osc_figure,
        "phase_vx": phase_vx,
        "phase_fv": phase_fv,
        "missing_snapshots": missing,
    }


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

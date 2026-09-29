"""Данные страницы результата: «протокол» итогов и лёгкая осциллограмма.

Раньше страница результата встраивала 15 готовых Plotly-фрагментов со ВСЕМИ точками
расчёта (до ~17 МБ HTML). Теперь главный график — одна синхронная осциллограмма
x/v/a/F на общей оси времени, построенная из snapshot'а, прореженного до ~3 тыс.
точек с сохранением экстремумов (min/max по корзинам для каждого канала), точек
разворота/возврата и переключений этапов. Остальные графики догружаются по мере
прокрутки (views.run.run_chart_view).

Протокол — итоговые величины одной строкой: что, сколько и КОГДА достигнуто.
Пики считаются по полному (не прореженному) ряду.
"""

from __future__ import annotations

import numpy as np

from ..models import BrakeStage, CalculationRun, CalculationSnapshot

G = 9.81
DECIMATION_BUCKETS = 700     # корзин на канал → до ~2 800 точек после min/max
DECIMATION_MIN_POINTS = 3000  # короче — отдаём как есть


# ---------------------------------------------------------------------------
# Ряды из snapshot'а
# ---------------------------------------------------------------------------

def load_series(run: CalculationRun) -> dict | None:
    """Полные ряды t/x/v/a/|F| и фазы из CalculationSnapshot (None — если нет)."""
    try:
        snap = run.snapshot
    except CalculationSnapshot.DoesNotExist:
        return None
    rs = snap.result_snapshot or {}
    timeline = rs.get("timeline") or {}
    t = np.asarray(timeline.get("t") or [], dtype=float)
    n = len(t)
    if n < 2:
        return None
    x = np.asarray(timeline.get("x") or [], dtype=float)
    v = np.asarray(timeline.get("v") or [], dtype=float)
    a = np.asarray(timeline.get("a") or [], dtype=float)
    f_raw = (rs.get("forces") or {}).get("magnetic_sum") or []
    f = np.abs(np.asarray(f_raw, dtype=float)) if len(f_raw) == n else np.zeros(n)
    if not (len(x) == len(v) == len(a) == n):
        return None

    phases = rs.get("phases") or {}
    recoil = phases.get("recoil") or {}
    ret = phases.get("return") or {}
    return {
        "t": t, "x": x, "v": v, "a": a, "f": f,
        "recoil_end_index": recoil.get("end_index"),
        "recoil_end_time": recoil.get("end_time"),
        "return_end_index": ret.get("end_index"),
        "return_end_time": ret.get("end_time"),
    }


def stage_index_for(run: CalculationRun, t: np.ndarray, t_turn: float | None) -> np.ndarray | None:
    """Номер этапа конфигурации в каждой точке (итерационный расчёт), иначе None.

    Этап k включается на откате в t_forward(k) и снимается на накате в t_return(k)
    (в обратном порядке) — активен старший из включённых и не снятых.
    """
    stages = list(BrakeStage.objects.filter(run=run).order_by("stage"))
    if len(stages) < 2:
        return None
    idx = np.zeros(len(t), dtype=int)
    for s in stages:
        if s.stage == 0 or s.t_forward is None:
            continue
        active = t >= s.t_forward
        if t_turn is not None and s.t_return is not None:
            active &= ~((t > t_turn) & (t >= s.t_return))
        idx[active] = s.stage
    return idx


def stage_segments(t: np.ndarray, stage: np.ndarray) -> list[dict]:
    """Непрерывные участки одного этапа: [{t0, t1, stage}]."""
    segments = []
    start = 0
    for i in range(1, len(stage) + 1):
        if i == len(stage) or stage[i] != stage[start]:
            segments.append({"t0": float(t[start]), "t1": float(t[i - 1]), "stage": int(stage[start])})
            start = i
    return segments


def decimate_indices(channels: list[np.ndarray], keep: list[int]) -> np.ndarray:
    """Индексы для прорежения: min/max каждого канала в каждой корзине + обязательные точки."""
    n = len(channels[0])
    if n <= DECIMATION_MIN_POINTS:
        return np.arange(n)
    edges = np.linspace(0, n, DECIMATION_BUCKETS + 1).astype(int)
    picked = [0, n - 1]
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi <= lo:
            continue
        picked.append(lo)
        for ch in channels:
            seg = ch[lo:hi]
            picked.append(lo + int(np.argmin(seg)))
            picked.append(lo + int(np.argmax(seg)))
    picked.extend(i for i in keep if i is not None and 0 <= i < n)
    return np.unique(np.asarray(picked, dtype=int))


def force_scale(f_max_abs: float) -> tuple[float, str]:
    """Единица силы для показа: кН для больших сил, Н — если максимум меньше 1 кН."""
    return (1000.0, "кН") if f_max_abs >= 1000.0 else (1.0, "Н")


def _round(arr: np.ndarray, digits: int) -> list[float]:
    return [float(v) for v in np.round(arr, digits)]


def build_oscillogram_data(run: CalculationRun, series: dict | None = None) -> dict | None:
    """Прореженные каналы для осциллограммы (x в мм, v в м/с, a в g, |F| в кН)."""
    series = series if series is not None else load_series(run)
    if series is None:
        return None
    t = series["t"]
    t_turn = series["recoil_end_time"]
    stage = stage_index_for(run, t, t_turn)

    keep = [series["recoil_end_index"], series["return_end_index"]]
    if series["recoil_end_index"] is not None:
        keep.append(series["recoil_end_index"] + 1)
    if stage is not None:
        switch_rows = np.nonzero(np.diff(stage))[0]
        keep.extend(int(i) for i in switch_rows)
        keep.extend(int(i) + 1 for i in switch_rows)

    idx = decimate_indices([series["x"], series["v"], series["a"], series["f"]], keep)
    t_end = series["return_end_time"] if series["return_end_time"] is not None else float(t[-1])
    f_div, f_unit = force_scale(float(np.max(series["f"])) if len(series["f"]) else 0.0)
    return {
        "t": _round(t[idx], 6),
        "x_mm": _round(series["x"][idx] * 1000.0, 3),
        "v": _round(series["v"][idx], 5),
        "a_g": _round(series["a"][idx] / G, 4),
        "f": _round(series["f"][idx] / f_div, 4 if f_div > 1 else 3),
        "f_unit": f_unit,
        "stage": [int(s) for s in stage[idx]] if stage is not None else None,
        "segments": stage_segments(t, stage) if stage is not None else [],
        "t0": float(t[0]),
        "t_turn": float(t_turn) if t_turn is not None else None,
        "t_end": float(t_end),
        "n_full": int(len(t)),
    }


# ---------------------------------------------------------------------------
# Протокол
# ---------------------------------------------------------------------------

NBSP = " "   # узкий неразрывный пробел — разделитель тысяч


def fmt_number(value: float | None, digits: int) -> str:
    """Число для протокола: фиксированная точность, тысячи через узкий пробел."""
    if value is None or not np.isfinite(value):
        return "—"
    if abs(value) < 0.5 * 10.0 ** -digits:
        value = 0.0
    return f"{value:,.{digits}f}".replace(",", NBSP).replace("-", "−")


def build_protocol(run: CalculationRun, series: dict | None) -> list[dict]:
    """Ячейки протокола: {label, value, unit, when, quantity, status}.

    quantity — цветовая метка величины (x/v/a/f) или ''; status — ok/warn/bad/''.
    """
    cells: list[dict] = []
    if series is not None:
        t, x, v, a, f = series["t"], series["x"], series["v"], series["a"], series["f"]
        i_x = int(np.argmax(x))
        i_v = int(np.argmax(np.abs(v)))
        i_a = int(np.argmax(np.abs(a)))
        i_f = int(np.argmax(f))
        cells.append({"label": "Максимальный откат" if not run.is_free_fall else "Максимальный путь",
                      "value": fmt_number(x[i_x] * 1000.0, 1), "unit": "мм",
                      "when": f"при t = {fmt_number(t[i_x], 3)} с", "quantity": "x", "status": ""})
        cells.append({"label": "Максимальная скорость", "value": fmt_number(abs(v[i_v]), 2), "unit": "м/с",
                      "when": f"при t = {fmt_number(t[i_v], 3)} с", "quantity": "v", "status": ""})
        cells.append({"label": "Пиковое ускорение", "value": fmt_number(abs(a[i_a]) / G, 1), "unit": "g",
                      "when": f"{fmt_number(abs(a[i_a]), 0)} м/с² при t = {fmt_number(t[i_a], 3)} с",
                      "quantity": "a", "status": ""})
        f_div, f_unit = force_scale(float(f[i_f]))
        cells.append({"label": "Сила торможения", "value": fmt_number(f[i_f] / f_div, 1), "unit": f_unit,
                      "when": f"максимум суммы при t = {fmt_number(t[i_f], 3)} с", "quantity": "f", "status": ""})
    elif run.x_max is not None:
        cells.append({"label": "Максимальный откат", "value": fmt_number(run.x_max * 1000.0, 1), "unit": "мм",
                      "when": "", "quantity": "x", "status": ""})

    if run.is_free_fall:
        if run.v_final is not None:
            cells.append({"label": "Скорость в конце", "value": fmt_number(abs(run.v_final), 3), "unit": "м/с",
                          "when": f"при t = {fmt_number(run.t_max, 3)} с", "quantity": "", "status": ""})
    elif run.return_end_time is not None:
        recoil = run.recoil_end_time
        when = (f"откат {fmt_number(recoil, 3)} + накат {fmt_number(run.return_end_time - recoil, 3)} с"
                if recoil is not None else "откат и накат")
        cells.append({"label": "Время цикла", "value": fmt_number(run.return_end_time, 3), "unit": "с",
                      "when": when, "quantity": "", "status": ""})
        v_end = None
        if series is not None and series["return_end_index"] is not None:
            v_end = abs(float(series["v"][min(series["return_end_index"], len(series["v"]) - 1)]))
        if v_end is not None:
            cells.append({"label": "Скорость в конце наката", "value": fmt_number(v_end, 3), "unit": "м/с",
                          "when": "при возврате в x = 0", "quantity": "", "status": ""})
    else:
        cells.append({"label": "Время цикла", "value": "—", "unit": "",
                      "when": f"не вернулся в x = 0 за {fmt_number(run.t_max, 3)} с", "quantity": "",
                      "status": "warn"})

    if run.energy_residual_pct is not None:
        resid = float(run.energy_residual_pct)
        status = "ok" if resid < 1.0 else ("warn" if resid < 3.0 else "bad")
        note = {"ok": "невязка в норме, до 1 %", "warn": "невязка 1–3 %: уменьшите шаг",
                "bad": "невязка больше 3 %: уменьшите шаг"}[status]
        cells.append({"label": "Энергобаланс", "value": fmt_number(resid, 2), "unit": "%",
                      "when": note, "quantity": "", "status": status})
    return cells


def build_status(run: CalculationRun) -> dict:
    """Строка статуса под заголовком: {text, kind} — kind: ok/warn/info."""
    if run.is_free_fall:
        return {"text": f"Свободное падение до t = {fmt_number(run.t_max, 3)} с", "kind": "info"}
    if run.termination_reason == "returned_to_zero":
        if run.return_end_time is not None:
            return {"text": f"Цикл завершён: вернулся в x = 0 за {fmt_number(run.return_end_time, 3)} с", "kind": "ok"}
        return {"text": "Цикл завершён: вернулся в x = 0", "kind": "ok"}
    if run.termination_reason == "time_limit":
        return {"text": f"Остановлен по пределу времени: x = 0 не достигнут за {fmt_number(run.t_max, 3)} с",
                "kind": "warn"}
    if run.termination_reason == "stopped_by_user":
        return {"text": "Остановлен вручную в пошаговой сессии: графики по посчитанной части", "kind": "warn"}
    if run.termination_reason == "not_finished":
        return {"text": f"Не завершён к t = {fmt_number(run.t_max, 3)} с", "kind": "warn"}
    if run.termination_reason:
        return {"text": f"Завершение: {run.termination_reason}", "kind": "warn"}
    return {"text": "", "kind": ""}


# ---------------------------------------------------------------------------
# Вторичные графики: догружаются по мере прокрутки (views.run.run_chart_view)
# ---------------------------------------------------------------------------

# ключ → (поля-кандидаты FileField по порядку предпочтения)
LAZY_CHART_FIELDS: dict[str, tuple[str, ...]] = {
    "v_x": ("chart_v_x",),
    "fmag_v": ("chart_fmag_v",),
    "energy": ("chart_energy",),
    "forces": ("chart_forces_secondary",),
    "forces_main": ("chart_forces_main_recoil",),
    # Для архивных расчётов без snapshot'а — прежние графики вместо осциллограммы.
    "x_t": ("chart_x_t_annotated", "chart_x_t"),
    "v_a_t": ("chart_v_a_t",),
}


def _field_has_file(run: CalculationRun, field: str) -> bool:
    ff = getattr(run, field, None)
    return bool(ff and getattr(ff, "name", ""))


def available_lazy_charts(run: CalculationRun) -> set[str]:
    return {key for key, fields in LAZY_CHART_FIELDS.items() if any(_field_has_file(run, f) for f in fields)}


def lazy_chart_html(run: CalculationRun, key: str) -> str | None:
    """HTML-фрагмент графика по ключу; None — ключ неизвестен.

    Пропавший файл — понятное сообщение вместо пути и Errno.
    """
    from .chart_files import chart_problem_text, read_chart_fields

    fields = LAZY_CHART_FIELDS.get(key)
    if fields is None:
        return None
    for field in fields:
        if not _field_has_file(run, field):
            continue
        html, problems = read_chart_fields(run, [field])
        if field in html:
            return html[field]
        return f'<p class="rb-chart-missing">{problems[0]}</p>'
    return f'<p class="rb-chart-missing">{chart_problem_text(fields[0])}</p>'


# ---------------------------------------------------------------------------
# Сборка страницы
# ---------------------------------------------------------------------------

def brake_rows(brakes) -> list[dict]:
    """Тормоза для боковой панели: имя, тип, краткая сводка."""
    from .brake_params import SPEC_BY_FIELD, SUMMARY_FIELDS

    rows = []
    for b in brakes:
        if b.model_type == "parametric":
            parts = []
            for field in SUMMARY_FIELDS:
                value = getattr(b, field, None)
                if value is None:
                    continue
                _f, _label, symbol, unit, _g = SPEC_BY_FIELD[field]
                text = f"{value:g}" if isinstance(value, float) else str(value)
                parts.append(f"{symbol} = {text}{(' ' + unit) if unit else ''}")
            rows.append({"name": b.display_name, "kind": "параметры", "summary": ", ".join(parts)})
        else:
            points = list(b.force_points.order_by("order", "id").values_list("velocity", "force"))
            if points:
                v_max = max(p[0] for p in points)
                f_max = max(p[1] for p in points)
                summary = f"{len(points)} точек, v до {v_max:g} м/с, F до {f_max / 1000:g} кН"
            else:
                summary = "таблица не загружена"
            rows.append({"name": b.display_name, "kind": "таблица F(v)", "summary": summary})
    return rows


def stage_rows(stage_tables: dict | None) -> list[dict]:
    """Компактная таблица этапов для боковой панели (цвет — как на ленте осциллограммы)."""
    from .charting import _stage_color

    if not stage_tables:
        return []
    rows = []
    for s in stage_tables["stages"]:
        rows.append({
            "index": s["index"],
            "color": _stage_color(s["index"]),
            "x_mm": fmt_number(s["x"] * 1000.0, 0) if s["x"] is not None else None,
            "kinds": ", ".join(s["kinds"]),
            "changes": s["changes"],
        })
    return rows


def build_result_page(run: CalculationRun) -> dict:
    """Всё для шаблона страницы результата, кроме прав и тепловых сценариев."""
    import json

    import plotly.io as pio

    from .brake_params import geometry_3d_available
    from .charting import make_oscillogram_figure
    from .iterative.result_view import build_stage_tables, session_for_run
    from .kpi import build_kpi_groups
    from .snapshot import extract_snapshot_parts

    brakes = list(run.brakes.order_by("index"))
    series = load_series(run)
    osc = build_oscillogram_data(run, series)
    osc_figure = None
    osc_extra = None
    if osc is not None:
        osc_figure = json.loads(pio.to_json(make_oscillogram_figure(osc, free_fall=run.is_free_fall),
                                            validate=False))
        ranges = {"all": [osc["t0"], osc["t_end"]]}
        if osc["t_turn"] is not None and not run.is_free_fall:
            ranges["recoil"] = [osc["t0"], osc["t_turn"]]
            if run.return_end_time is not None:
                ranges["return"] = [osc["t_turn"], osc["t_end"]]
        osc_extra = {"stage": osc["stage"], "ranges": ranges, "f_unit": osc["f_unit"],
                     "n_full": osc["n_full"], "n_shown": len(osc["t"])}

    stage_tables, iterative_calc = None, None
    if run.is_iterative:
        stage_tables = build_stage_tables(run)
        iterative_calc = session_for_run(run)

    energy_summary = None
    if run.energy_residual_pct is not None or run.energy_input_total is not None:
        resid = run.energy_residual_pct
        energy_summary = {
            "input_total": run.energy_input_total,
            "brake_total": run.energy_brake_total,
            "residual_pct": resid,
            "residual_status": (None if resid is None else "ok" if resid < 1 else "warn" if resid < 3 else "bad"),
        }

    return {
        "brakes": brakes,
        "brake_rows": brake_rows(brakes),
        "protocol": build_protocol(run, series),
        "status": build_status(run),
        "osc_figure": osc_figure,
        "osc_extra": osc_extra,
        "lazy_charts": available_lazy_charts(run),
        "kpi_groups": build_kpi_groups(run, extract_snapshot_parts(run)),
        "energy_summary": energy_summary,
        "stage_tables": stage_tables,
        "stage_rows": stage_rows(stage_tables),
        "iterative_calc": iterative_calc,
        "geometry_brakes": [
            {"name": b.display_name, "tab": f"b{b.index}", "key": f"geometry-{b.index}"}
            for b in brakes if geometry_3d_available(b)
        ],
        "warnings": [w for w in (run.warnings_text or "").splitlines() if w.strip()],
    }

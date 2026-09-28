"""Данные страницы итерационного расчёта: текущий узел, тормоза, этапы, графики.

Один источник для первого рендера страницы и для AJAX-ответов после каждого
действия — чтобы панель не расходилась с тем, что показали после шага.
"""

from __future__ import annotations

from ..charting import make_iterative_preview_figures
from .config import KIND_LABELS, KIND_PARAMETRIC, config_diff, curve_summary, slot_kind
from .overlay import build_stage_overlay
from .session import (
    PHASE_FALL,
    PHASE_RECOIL,
    PHASE_RETURN,
    STOP_FINISHED,
    STOP_STEPS,
    STOP_TARGET,
    STOP_TURNAROUND,
    AdvanceReport,
    IterativeSession,
)

PHASE_LABELS = {PHASE_RECOIL: "откат", PHASE_RETURN: "накат", PHASE_FALL: "падение"}

TERMINATION_LABELS = {
    "returned_to_zero": "накат завершён (x = 0)",
    "time_limit": "достигнуто t_max",
    "free_fall": "достигнуто t_max",
    "not_finished": "не завершён к t_max",
    "stopped_by_user": "остановлен",
}


def build_view_state(session: IterativeSession) -> dict:
    outcome = session.build_result()
    result = outcome.result
    node = session.current()

    brakes = []
    for k, slot in enumerate(session.config):
        kind = slot_kind(slot)
        brakes.append({
            "number": k + 1,
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "force": node["f_each"][k],
            "wn": node["wn"][k] if kind == KIND_PARAMETRIC else None,
            "curve_info": curve_summary(slot) if kind == "curve" else "",
        })

    stages = []
    for stage in session.stages:
        previous = session.stages[stage.index - 1].config if stage.index > 0 else None
        stages.append({
            "index": stage.index,
            "active": stage.index == session.active_stage,
            "x": stage.x, "t": stage.t, "v": stage.v,
            "return_t": stage.return_t, "return_v": stage.return_v,
            "kinds": [KIND_LABELS[slot_kind(s)] for s in stage.config],
            "changes": config_diff(previous, stage.config) if previous is not None else [],
        })

    energy_brake = float(result.energy_brake_cum[-1]) if result.energy_brake_cum is not None else None
    return {
        "mode": session.mode,
        "node": {
            "t": node["t"], "x": node["x"], "v": node["v"], "a": node["a"],
            "f_magnetic": node["f_magnetic"], "f_ext": node["f_ext"],
            "f_spring": node["f_spring"], "f_total": node["f_total"],
            "grid_index": session.grid_index, "grid_total": session.grid_steps_total,
            "on_grid": node["on_grid"], "row": node["row"],
        },
        "phase": session.phase,
        "phase_label": PHASE_LABELS[session.phase],
        "stage": session.active_stage,
        "finished": session.finished,
        "termination_label": TERMINATION_LABELS.get(session.termination_reason or "", ""),
        "can_reconfigure": session.can_reconfigure,
        "can_undo": session.can_undo,
        "undo_hint": (f"вернуться в x = {session.stages[-1].x:.6g} м к этапу {len(session.stages) - 2}"
                      if session.can_undo else ""),
        "brakes": brakes,
        "stages": stages,
        "x_max": float(result.x.max()),
        "recoil_end_time": result.recoil_end_time,
        "energy_brake": energy_brake,
        "energy_residual_pct": result.energy_residual_pct,
        "warnings": list(result.warnings),
        "charts": make_iterative_preview_figures(result, build_stage_overlay(outcome)),
    }


def report_message(report: AdvanceReport) -> str:
    """Что произошло за продвижение — одной строкой для панели сообщений."""
    parts = []
    if report.reason == STOP_STEPS:
        parts.append(f"Сделано шагов: {report.grid_steps}.")
    elif report.reason == STOP_TARGET:
        parts.append("Точка достигнута — узел поставлен точно в неё.")
    elif report.reason == STOP_TURNAROUND:
        parts.append("Разворот наступил раньше — точка не достигнута. Остановились на развороте.")
    elif report.reason == STOP_FINISHED:
        parts.append("Расчёт дошёл до конца.")
    if report.turned and report.reason != STOP_TURNAROUND:
        parts.append("Пройден разворот — дальше накат, конфигурация меняется автоматически.")
    for event in report.switches:
        where = "на накате" if event.direction == "return" else ""
        parts.append(f"Переключение {where} этап {event.stage_from}→{event.stage_to} "
                     f"при x = {event.x:.6g} м.".replace("  ", " "))
    return " ".join(parts)

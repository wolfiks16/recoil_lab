"""Строки таблиц расчётов (рабочий стол, «Все расчёты») и сводка рабочего стола."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ..models import BrakeCatalog, CalculationRun, IterativeCalc
from .permissions import can_delete_run, iterative_visible_to, runs_visible_to

WARNINGS_Q = Q(spring_out_of_range=True) | Q(warnings_text__gt="")


def run_status(run: CalculationRun) -> tuple[str, str]:
    """(вид, подпись) статуса расчёта: ok / warn / info."""
    if run.is_free_fall:
        return "info", "свободное падение"
    if run.termination_reason == "returned_to_zero":
        return "ok", "цикл завершён"
    if run.termination_reason == "time_limit":
        return "warn", "не вернулся к t_max"
    if run.termination_reason == "stopped_by_user":
        return "warn", "остановлен"
    if run.termination_reason:
        return "warn", run.termination_reason
    return "", "—"


def run_rows(runs, user) -> list[dict]:
    """Строки для таблицы расчётов: статус, предупреждения, ссылки и права."""
    rows = []
    for run in runs:
        kind, label = run_status(run)
        copy_name = "free_fall_new" if run.is_free_fall else "index"
        rows.append({
            "run": run,
            "status": kind,
            "status_label": label,
            "has_warnings": bool(run.spring_out_of_range or (run.warnings_text or "").strip()),
            "brakes_count": len(run.brakes.all()),
            "copy_url": f"{reverse(copy_name)}?from_run={run.pk}",
            "can_delete": can_delete_run(user, run),
        })
    return rows


def workspace_summary(user) -> dict:
    """Рабочий стол: последние расчёты, идущие пошаговые сессии, счётчики."""
    week_ago = timezone.now() - timedelta(days=7)
    runs_qs = runs_visible_to(user)
    recent = list(runs_qs.select_related("owner").prefetch_related("brakes").order_by("-created_at")[:8])

    sessions = []
    if getattr(user, "is_authenticated", False):
        sessions = list(
            iterative_visible_to(user).filter(owner=user)
            .exclude(status=IterativeCalc.STATUS_FINISHED).order_by("-updated_at")[:5]
        )

    return {
        "recent_rows": run_rows(recent, user),
        "sessions": sessions,
        "stats": {
            "total": runs_qs.count(),
            "last_week": runs_qs.filter(created_at__gte=week_ago).count(),
            "success": runs_qs.filter(termination_reason="returned_to_zero").count(),
            "warnings": runs_qs.filter(WARNINGS_Q).count(),
            "catalog": BrakeCatalog.objects.count(),
        },
    }

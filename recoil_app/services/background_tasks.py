"""Фоновые задачи пользователя для индикатора в верхней строке.

В проекте два фоновых процесса (оба — демон-потоки, см. CLAUDE.md):
  * исследование подбора тормоза `DesignStudy` (pending/running);
  * «Досчитать до конца» пошаговой сессии `IterativeCalc` (finishing).
Индикатор показывает только СВОИ задачи пользователя — чужие ему не интересны
и не должны светиться в чужом интерфейсе.
"""

from __future__ import annotations

from django.urls import reverse

from ..models import DesignStudy, IterativeCalc


def running_tasks_for(user) -> list[dict]:
    """Список запущенных задач пользователя: {kind, label, status, url}."""
    if not getattr(user, "is_authenticated", False):
        return []

    tasks: list[dict] = []
    studies = (
        DesignStudy.objects
        .filter(owner=user, status__in=[DesignStudy.STATUS_PENDING, DesignStudy.STATUS_RUNNING])
        .order_by("-created_at")[:10]
    )
    for study in studies:
        tasks.append({
            "kind": "optimize",
            "label": f"Подбор тормоза «{study.name}»",
            "status": study.get_status_display(),
            "url": reverse("optimize_detail", args=[study.pk]),
        })

    calcs = (
        IterativeCalc.objects
        .filter(owner=user, status=IterativeCalc.STATUS_FINISHING)
        .order_by("-updated_at")[:10]
    )
    for calc in calcs:
        tasks.append({
            "kind": "iterative",
            "label": f"Пошаговая сессия «{calc.name}»",
            "status": calc.get_status_display(),
            "url": reverse("iterative_detail", args=[calc.pk]),
        })
    return tasks

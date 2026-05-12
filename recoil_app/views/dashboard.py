"""Дашборд — главный экран приложения (`/`).

Только обзорные stat-карточки и быстрые действия. Каталог расчётов с фильтрами
и пагинацией переехал в `views.results.results_view` (страница `/results/`).
"""

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from ..models import BrakeCatalog, CalculationRun
from ..services.permissions import runs_visible_to


def dashboard_view(request):
    week_ago = timezone.now() - timedelta(days=7)
    runs_qs = runs_visible_to(request.user)

    stats = {
        "total":     runs_qs.count(),
        "last_week": runs_qs.filter(created_at__gte=week_ago).count(),
        "success":   runs_qs.filter(termination_reason="returned_to_zero").count(),
        "warnings":  runs_qs.filter(
            Q(spring_out_of_range=True) | Q(warnings_text__gt="")
        ).count(),
        "catalog":   BrakeCatalog.objects.count(),
    }

    return render(
        request,
        "recoil_app/dashboard.html",
        {"stats": stats},
    )

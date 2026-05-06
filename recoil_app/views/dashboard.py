"""Дашборд — главный экран приложения (`/`).

Только обзорные stat-карточки и быстрые действия. Каталог расчётов с фильтрами
и пагинацией переехал в `views.results.results_view` (страница `/results/`).
"""

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from ..models import BrakeCatalog, CalculationRun


def dashboard_view(request):
    week_ago = timezone.now() - timedelta(days=7)

    stats = {
        "total":     CalculationRun.objects.count(),
        "last_week": CalculationRun.objects.filter(created_at__gte=week_ago).count(),
        "success":   CalculationRun.objects.filter(termination_reason="returned_to_zero").count(),
        "warnings":  CalculationRun.objects.filter(
            Q(spring_out_of_range=True) | Q(warnings_text__gt="")
        ).count(),
        "catalog":   BrakeCatalog.objects.count(),
    }

    return render(
        request,
        "recoil_app/dashboard.html",
        {"stats": stats},
    )

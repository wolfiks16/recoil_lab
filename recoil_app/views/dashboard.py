"""Рабочий стол — главный экран приложения (`/`).

Последние расчёты, идущие пошаговые сессии, счётчики по базе. Полный список
с поиском и фильтрами — `views.results.results_view` (`/results/`).
"""

from django.shortcuts import render

from ..services.run_list import workspace_summary


def dashboard_view(request):
    return render(request, "recoil_app/dashboard.html", workspace_summary(request.user))

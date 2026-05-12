"""Страница сравнения двух расчётов (`/compare/`)."""

from django.shortcuts import render

from ..forms import CompareRunsForm
from ..services.compare_data import (
    build_compare_metrics_table,
    build_compare_overlay_charts,
)
from ..services.permissions import can_view_run, runs_visible_to


def compare_view(request):
    # Ограничиваем выборку в dropdown'ах формы по роли:
    # admin/analyst видят все расчёты, engineer — только свои, гость — ничего.
    visible_runs = runs_visible_to(request.user)
    form = CompareRunsForm(request.GET or None)
    form.fields["run_a"].queryset = visible_runs.order_by("-created_at")
    form.fields["run_b"].queryset = visible_runs.order_by("-created_at")

    run_a = None
    run_b = None
    overlay_charts = {}
    metrics_table: list[dict] = []

    if form.is_valid():
        run_a = form.cleaned_data["run_a"]
        run_b = form.cleaned_data["run_b"]
        # Двойная проверка — если кто-то подсунул чужой run_id в URL,
        # form.queryset выше уже отрежет, но на всякий случай:
        if can_view_run(request.user, run_a) and can_view_run(request.user, run_b):
            overlay_charts = build_compare_overlay_charts(run_a, run_b)
            metrics_table = build_compare_metrics_table(run_a, run_b)
        else:
            run_a = run_b = None

    return render(
        request,
        "recoil_app/compare.html",
        {
            "form": form,
            "run_a": run_a,
            "run_b": run_b,
            "overlay_charts": overlay_charts,
            "metrics_table": metrics_table,
        },
    )

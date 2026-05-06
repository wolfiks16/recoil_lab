"""Страница сравнения двух расчётов (`/compare/`)."""

from django.shortcuts import render

from ..forms import CompareRunsForm
from ..services.compare_data import (
    build_compare_metrics_table,
    build_compare_overlay_charts,
)


def compare_view(request):
    form = CompareRunsForm(request.GET or None)

    run_a = None
    run_b = None
    overlay_charts = {}
    metrics_table: list[dict] = []

    if form.is_valid():
        run_a = form.cleaned_data["run_a"]
        run_b = form.cleaned_data["run_b"]
        overlay_charts = build_compare_overlay_charts(run_a, run_b)
        metrics_table = build_compare_metrics_table(run_a, run_b)

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

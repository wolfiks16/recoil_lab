"""Страница «Результаты расчётов» (`/results/`).

Полный список расчётов с поиском, фильтрами, сортировкой, пагинацией и
плавающим баром выбора пары для сравнения. До этого жил на дашборде.
"""

from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from ..models import CalculationRun
from ..services.permissions import runs_visible_to


def results_view(request):
    """Каталог расчётов.

    Query-параметры:
        q       — текстовый поиск по имени расчёта
        filter  — 'all' | 'success' | 'warnings' | 'recent'
        sort    — '-created_at' | 'created_at' | 'name' | '-x_max' | 'return_end_time'
        page    — номер страницы (по 20 на страницу)
    """
    week_ago = timezone.now() - timedelta(days=7)

    # Фильтрация по роли: гость — пустой queryset, engineer — свои, analyst/admin — все.
    qs = runs_visible_to(request.user).prefetch_related("brakes").select_related("owner")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(name__icontains=q)

    flt = request.GET.get("filter") or "all"
    if flt == "success":
        qs = qs.filter(termination_reason="returned_to_zero")
    elif flt == "warnings":
        qs = qs.filter(Q(spring_out_of_range=True) | Q(warnings_text__gt=""))
    elif flt == "recent":
        qs = qs.filter(created_at__gte=week_ago)

    sort = request.GET.get("sort") or "-created_at"
    allowed_sorts = {
        "-created_at":      "-created_at",
        "created_at":       "created_at",
        "name":             "name",
        "-name":            "-name",
        "-x_max":           "-x_max",
        "return_end_time":  "return_end_time",
    }
    sort_field = allowed_sorts.get(sort, "-created_at")
    qs = qs.order_by(sort_field, "-created_at")

    paginator = Paginator(qs, 20)
    page_num = request.GET.get("page") or 1
    page = paginator.get_page(page_num)

    cards = []
    for run in page.object_list:
        if run.termination_reason == "returned_to_zero":
            status = "ok"
            status_label = "завершён"
        elif run.termination_reason == "time_limit":
            status = "warn"
            status_label = "по времени"
        elif run.termination_reason:
            status = "warn"
            status_label = run.termination_reason
        else:
            status = "neutral"
            status_label = "—"

        has_warnings = bool(run.spring_out_of_range or (run.warnings_text or "").strip())

        cards.append({
            "run": run,
            "status": status,
            "status_label": status_label,
            "has_warnings": has_warnings,
        })

    qs_keep: list[str] = []
    for key in ("q", "filter", "sort"):
        val = request.GET.get(key)
        if val:
            qs_keep.append(f"{key}={val}")
    qs_keep_str = "&".join(qs_keep)

    return render(
        request,
        "recoil_app/results.html",
        {
            "cards": cards,
            "page": page,
            "paginator": paginator,
            "q": q,
            "filter_value": flt,
            "sort_value": sort,
            "qs_keep_str": qs_keep_str,
        },
    )

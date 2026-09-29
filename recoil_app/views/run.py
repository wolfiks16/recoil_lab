"""Создание расчёта (форма + симуляция), страница результата v2, удаление."""

import shutil
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import CalculationForm, FreeFallForm, MagneticBrakeFormSet
from ..models import BrakeCatalog, CalculationRun, MagneticBrakeConfig
from ..services.permissions import can_delete_run, can_run_calc, can_view_run, visible_run
from ..services.charting import build_brake_geometry_3d
from ..services.dynamics import RecoilParams, simulate_free_fall, simulate_recoil
from ..services.run_pipeline import (
    brake_initial_from_catalog,
    build_initial_from_run,
    copy_input_file,
    create_brake_objects_and_runtime_models,
    persist_result_and_snapshot,
    resolve_curve_sources,
)
from ..services.result_page import build_result_page, lazy_chart_html


def index_view(request):
    """Новый расчёт в режиме «откат и накат» (форма calc_new.html, mode='recoil').

    Гость может ВИДЕТЬ форму, но не запускать расчёт (POST → на вход).
    ?from_run=<id> — копия расчёта (входной файл можно не загружать заново);
    ?catalog=<id> — первый тормоз подставлен из каталога.
    """
    return _new_calc_view(request, mode=CalculationRun.MODE_RECOIL)


def free_fall_new_view(request):
    """Новый расчёт в режиме свободного падения: без входного файла, `simulate_free_fall`."""
    return _new_calc_view(request, mode=CalculationRun.MODE_FREE_FALL)


def _new_calc_view(request, *, mode: str):
    is_recoil = mode == CalculationRun.MODE_RECOIL
    if request.method == "POST" and not can_run_calc(request.user):
        messages.warning(request, "Для запуска расчёта войдите или зарегистрируйтесь.")
        return redirect(f"/login/?next={request.path}")

    source_run, catalog_prefill = None, None
    if request.method == "POST":
        form = (CalculationForm(request.POST, request.FILES, user=request.user) if is_recoil
                else FreeFallForm(request.POST))
        brake_formset = MagneticBrakeFormSet(request.POST, request.FILES, prefix="brakes")
        forms_valid = form.is_valid() and brake_formset.is_valid()
        curve_sources_valid = resolve_curve_sources(brake_formset, user=request.user) if forms_valid else False

        if forms_valid and curve_sources_valid:
            cd = form.cleaned_data
            try:
                with transaction.atomic():
                    input_file = None
                    if is_recoil:
                        input_file = cd.get("input_file") or copy_input_file(cd["source_run"])
                    run = CalculationRun.objects.create(
                        name=cd["name"],
                        mode=mode,
                        input_file=input_file,
                        mass=cd["mass"],
                        angle_deg=cd["angle_deg"],
                        v0=cd["v0"],
                        x0=cd["x0"],
                        t_max=cd["t_max"],
                        dt=cd["dt"],
                        owner=request.user,
                    )
                    brake_objects, runtime_brakes = create_brake_objects_and_runtime_models(run, brake_formset)
                    recoil = RecoilParams(mass=run.mass, angle_deg=run.angle_deg, v0=run.v0,
                                          x0=run.x0, t_max=run.t_max, dt=run.dt)
                    if is_recoil:
                        result = simulate_recoil(run.input_file.path, recoil, runtime_brakes)
                    else:
                        result = simulate_free_fall(recoil, runtime_brakes)
                    persist_result_and_snapshot(run, brake_objects, result)
                return redirect("run_detail_v2", run_id=run.id)
            except ValueError as exc:
                form.add_error(None, str(exc))
        source_run = visible_run(request.user, request.POST.get("source_run_id"))
    else:
        source_run = visible_run(request.user, request.GET.get("from_run"))
        initial_main, brakes_initial = build_initial_from_run(source_run.pk if source_run else None)
        if source_run is not None and (not is_recoil or not source_run.input_file):
            initial_main.pop("source_run_id", None)

        catalog_prefill = BrakeCatalog.objects.filter(pk=_int_or_none(request.GET.get("catalog"))).first()
        if catalog_prefill is not None and not brakes_initial:
            brakes_initial = [brake_initial_from_catalog(catalog_prefill)]

        form = CalculationForm(initial=initial_main, user=request.user) if is_recoil             else FreeFallForm(initial=initial_main)
        brake_formset = MagneticBrakeFormSet(
            initial=brakes_initial or ([{}, {}] if is_recoil else [{}]), prefix="brakes",
        )

    catalog_items = _build_catalog_items()
    return render(request, "recoil_app/calc_new.html", {
        "mode": "recoil" if is_recoil else "free_fall",
        "form": form,
        "brake_formset": brake_formset,
        "source_run": source_run,
        "catalog_prefill": catalog_prefill,
        "catalog_items": catalog_items,
        "catalog_count": len(catalog_items),
    })


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_catalog_items() -> list[dict]:
    """Каталог тормозов для выбора в форме расчёта (общий для index/free_fall)."""
    catalog_items: list[dict] = []
    for c in BrakeCatalog.objects.order_by("name"):
        catalog_items.append({
            "id": c.pk,
            "name": c.name,
            "description": c.description or "",
            "model_type": c.model_type,
            "is_parametric": c.is_parametric,
            "is_curve": c.is_curve,
            "summary": c.short_summary,
            "params": {
                "gamma": c.gamma,
                "delta": c.delta,
                "n":     c.n,
                "xm":    c.xm,
                "ym":    c.ym,
                "dh1":   c.dh1,
                "dh2":   c.dh2,
                "dm":    c.dm,
                "mu":    c.mu,
                "bz":    c.bz,
                "lya":   c.lya,
                "wn0":   c.wn0,
            },
        })
    return catalog_items


def run_detail_v2_view(request, run_id):
    """Страница результата: протокол итогов, осциллограмма, вторичные графики по требованию.

    Доступ:
      гость           → на вход
      engineer        → только свои
      analyst/admin   → любые
    """
    run = get_object_or_404(CalculationRun, pk=run_id)
    denied = _deny_run_view(request, run)
    if denied is not None:
        return denied

    context = build_result_page(run)
    context.update({
        "run": run,
        "thermal_runs_preview": list(run.thermal_runs.order_by("-created_at")[:3]),
        "thermal_runs_total": run.thermal_runs.count(),
        "perm_can_delete": can_delete_run(request.user, run),
    })
    return render(request, "recoil_app/run_detail_v2.html", context)


def run_chart_view(request, run_id, key):
    """HTML-фрагмент вторичного графика (догружается страницей результата).

    key — из services.result_page.LAZY_CHART_FIELDS или «geometry-<индекс тормоза>».
    """
    run = get_object_or_404(CalculationRun, pk=run_id)
    denied = _deny_run_view(request, run)
    if denied is not None:
        return denied

    if key.startswith("geometry-"):
        try:
            brake = run.brakes.get(index=int(key.split("-", 1)[1]))
        except (ValueError, MagneticBrakeConfig.DoesNotExist):
            raise Http404("Нет такого тормоза")
        html = build_brake_geometry_3d(brake) or (
            '<p class="rb-chart-missing">Для 3D-модели нужны размеры n, x_m, y_m, Δh₁, Δh₂, d_m.</p>'
        )
        return HttpResponse(html)

    html = lazy_chart_html(run, key)
    if html is None:
        raise Http404("Нет такого графика")
    return HttpResponse(html)


def _deny_run_view(request, run):
    """Ответ-отказ, если смотреть расчёт нельзя (иначе None)."""
    if can_view_run(request.user, run):
        return None
    if not request.user.is_authenticated:
        messages.warning(
            request,
            "Результаты доступны только зарегистрированным пользователям. "
            "Войдите или создайте аккаунт.",
        )
        return redirect(f"/login/?next={request.path}")
    return HttpResponseForbidden(
        "У вас нет прав на просмотр этого расчёта. Расчёт создан другим инженером."
    )


@require_POST
def delete_run_view(request, run_id):
    run = get_object_or_404(CalculationRun, pk=run_id)
    if not can_delete_run(request.user, run):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden(
            "Удаление этого расчёта недоступно: он принадлежит другому пользователю."
        )

    folder_path: Path | None = None
    if run.report_file and run.report_file.name:
        folder_path = Path(settings.MEDIA_ROOT) / Path(run.report_file.name).parent

    for brake in run.brakes.all():
        if brake.curve_file:
            try:
                brake.curve_file.delete(save=False)
            except Exception:
                pass

    file_fields = [
        "input_file",
        "report_file",
        "chart_x_t",
        "chart_v_a_t",
        "chart_v_x",
        "chart_fmag_v",
        "chart_forces_secondary",
        "chart_x_t_recoil",
        "chart_v_a_t_recoil",
        "chart_forces_main_recoil",
        "chart_forces_secondary_recoil",
        "chart_x_t_return",
        "chart_v_a_t_return",
        "chart_forces_secondary_return",
        # v2:
        "chart_x_t_annotated",
        "chart_energy",
    ]

    for field_name in file_fields:
        field_file = getattr(run, field_name, None)
        if field_file:
            try:
                field_file.delete(save=False)
            except Exception:
                pass

    run.delete()

    if folder_path and folder_path.exists():
        shutil.rmtree(folder_path, ignore_errors=True)

    messages.success(request, "Расчёт и его файлы удалены.")
    return redirect("dashboard")


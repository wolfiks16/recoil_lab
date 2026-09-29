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
from ..services.permissions import can_delete_run, can_run_calc, can_view_run
from ..services.charting import build_brake_geometry_3d
from ..services.dynamics import RecoilParams, simulate_free_fall, simulate_recoil
from ..services.run_pipeline import (
    build_initial_from_run,
    create_brake_objects_and_runtime_models,
    persist_result_and_snapshot,
    resolve_curve_sources,
)
from ..services.result_page import build_result_page, lazy_chart_html


def index_view(request):
    # Гость может ВИДЕТЬ форму, но не сабмитить расчёт.
    # GET без логина — показать форму + плашка (см. шаблон).
    # POST без логина — редирект на login с next=.
    if request.method == "POST" and not can_run_calc(request.user):
        messages.warning(
            request,
            "Для запуска расчёта войдите или зарегистрируйтесь.",
        )
        return redirect(f"{settings.LOGIN_URL}?next={request.path}" if settings.LOGIN_URL.startswith('/') else f"/login/?next={request.path}")

    if request.method == "POST":
        form = CalculationForm(request.POST, request.FILES)
        brake_formset = MagneticBrakeFormSet(request.POST, request.FILES, prefix="brakes")

        forms_valid = form.is_valid() and brake_formset.is_valid()
        curve_sources_valid = resolve_curve_sources(brake_formset) if forms_valid else False

        if forms_valid and curve_sources_valid:
            try:
                with transaction.atomic():
                    run = CalculationRun.objects.create(
                        name=form.cleaned_data["name"],
                        input_file=form.cleaned_data["input_file"],
                        mass=form.cleaned_data["mass"],
                        angle_deg=form.cleaned_data["angle_deg"],
                        v0=form.cleaned_data["v0"],
                        x0=form.cleaned_data["x0"],
                        t_max=form.cleaned_data["t_max"],
                        dt=form.cleaned_data["dt"],
                        owner=request.user,        # auth: владелец = автор формы
                    )

                    brake_objects, runtime_brakes = create_brake_objects_and_runtime_models(
                        run,
                        brake_formset,
                    )

                    recoil = RecoilParams(
                        mass=run.mass,
                        angle_deg=run.angle_deg,
                        v0=run.v0,
                        x0=run.x0,
                        t_max=run.t_max,
                        dt=run.dt,
                    )

                    result = simulate_recoil(run.input_file.path, recoil, runtime_brakes)

                    persist_result_and_snapshot(run, brake_objects, result)

                return redirect("run_detail_v2", run_id=run.id)

            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        initial_main, brakes_initial = build_initial_from_run(request.GET.get("from_run"))
        form = CalculationForm(initial=initial_main)

        if brakes_initial:
            brake_formset = MagneticBrakeFormSet(initial=brakes_initial, prefix="brakes")
        else:
            brake_formset = MagneticBrakeFormSet(initial=[{}, {}], prefix="brakes")

    # Список «недавних» на форме — то же ограничение видимости, что и на дашборде.
    from ..services.permissions import runs_visible_to
    runs = runs_visible_to(request.user).order_by("-created_at")[:20]

    # Срез 3b: каталог тормозов для выбора в форме.
    catalog_items = _build_catalog_items()

    return render(
        request,
        "recoil_app/index.html",
        {
            "form": form,
            "brake_formset": brake_formset,
            "runs": runs,
            "catalog_items": catalog_items,
            "catalog_count": len(catalog_items),
        },
    )


def free_fall_new_view(request):
    """Создание расчёта в режиме свободного падения.

    Зеркалит `index_view`, но без входного Excel-файла: гравитация задаётся
    углом, выстрел и пружина отсутствуют. Использует `simulate_free_fall`.
    """
    if request.method == "POST" and not can_run_calc(request.user):
        messages.warning(
            request,
            "Для запуска расчёта войдите или зарегистрируйтесь.",
        )
        return redirect(
            f"{settings.LOGIN_URL}?next={request.path}"
            if settings.LOGIN_URL.startswith("/")
            else f"/login/?next={request.path}"
        )

    if request.method == "POST":
        form = FreeFallForm(request.POST)
        brake_formset = MagneticBrakeFormSet(request.POST, request.FILES, prefix="brakes")

        forms_valid = form.is_valid() and brake_formset.is_valid()
        curve_sources_valid = resolve_curve_sources(brake_formset) if forms_valid else False

        if forms_valid and curve_sources_valid:
            try:
                with transaction.atomic():
                    run = CalculationRun.objects.create(
                        name=form.cleaned_data["name"],
                        mode=CalculationRun.MODE_FREE_FALL,
                        input_file=None,        # свободное падение не требует файла
                        mass=form.cleaned_data["mass"],
                        angle_deg=form.cleaned_data["angle_deg"],
                        v0=form.cleaned_data["v0"],
                        x0=form.cleaned_data["x0"],
                        t_max=form.cleaned_data["t_max"],
                        dt=form.cleaned_data["dt"],
                        owner=request.user,
                    )

                    brake_objects, runtime_brakes = create_brake_objects_and_runtime_models(
                        run,
                        brake_formset,
                    )

                    recoil = RecoilParams(
                        mass=run.mass,
                        angle_deg=run.angle_deg,
                        v0=run.v0,
                        x0=run.x0,
                        t_max=run.t_max,
                        dt=run.dt,
                    )

                    result = simulate_free_fall(recoil, runtime_brakes)

                    persist_result_and_snapshot(run, brake_objects, result)

                return redirect("run_detail_v2", run_id=run.id)

            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        # Поддержка ?from_run= — префилл параметров из существующего расчёта.
        initial_main, brakes_initial = build_initial_from_run(request.GET.get("from_run"))
        form = FreeFallForm(initial=initial_main)

        if brakes_initial:
            brake_formset = MagneticBrakeFormSet(initial=brakes_initial, prefix="brakes")
        else:
            brake_formset = MagneticBrakeFormSet(initial=[{}], prefix="brakes")

    from ..services.permissions import runs_visible_to
    runs = runs_visible_to(request.user).order_by("-created_at")[:20]

    catalog_items = _build_catalog_items()

    return render(
        request,
        "recoil_app/free_fall.html",
        {
            "form": form,
            "brake_formset": brake_formset,
            "runs": runs,
            "catalog_items": catalog_items,
            "catalog_count": len(catalog_items),
        },
    )


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


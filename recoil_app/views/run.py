"""Создание расчёта (форма + симуляция), страница результата v2, удаление."""

import shutil
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from ..forms import CalculationForm, MagneticBrakeFormSet
from ..models import BrakeCatalog, CalculationRun, CalculationSnapshot
from ..services.analysis import enrich_with_basic_analysis
from ..services.charting import save_interactive_charts
from ..services.dynamics import RecoilParams, simulate_recoil
from ..services.kpi import build_kpi_groups
from ..services.modeling import build_calculation_model
from ..services.reporting import export_results_to_excel
from ..services.run_pipeline import (
    build_initial_from_run,
    create_brake_objects_and_runtime_models,
    resolve_curve_sources,
)
from ..services.snapshot import extract_snapshot_parts


def index_view(request):
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

                    run.x_max = float(result.x.max())
                    run.v_max = float(result.v.max())
                    run.x_final = float(result.x[-1])
                    run.v_final = float(result.v[-1])
                    run.a_final = float(result.a[-1])
                    run.recoil_end_time = result.recoil_end_time
                    run.return_end_time = result.return_end_time
                    run.termination_reason = result.termination_reason
                    run.spring_out_of_range = result.spring_out_of_range
                    run.warnings_text = "\n".join(result.warnings)

                    safe_name = slugify(run.name) or f"run-{run.id}"
                    run_folder_name = f"{safe_name}_{run.id}"
                    prefix = run_folder_name

                    run_reports_dir = Path(settings.MEDIA_ROOT) / "reports" / run_folder_name
                    run_reports_dir.mkdir(parents=True, exist_ok=True)

                    chart_paths = save_interactive_charts(result, run_reports_dir, prefix=prefix)

                    field_map = {
                        "chart_x_t": "chart_x_t",
                        "chart_v_a_t": "chart_v_a_t",
                        "chart_v_x": "chart_v_x",
                        "chart_fmag_v": "chart_fmag_v",
                        "chart_forces_secondary": "chart_forces_secondary",
                        "chart_x_t_recoil": "chart_x_t_recoil",
                        "chart_v_a_t_recoil": "chart_v_a_t_recoil",
                        "chart_forces_main_recoil": "chart_forces_main_recoil",
                        "chart_forces_secondary_recoil": "chart_forces_secondary_recoil",
                        "chart_x_t_return": "chart_x_t_return",
                        "chart_v_a_t_return": "chart_v_a_t_return",
                        "chart_forces_secondary_return": "chart_forces_secondary_return",
                        # --- v2 ---
                        "chart_x_t_annotated": "chart_x_t_annotated",
                        "chart_energy": "chart_energy",
                    }

                    for chart_key, model_field in field_map.items():
                        if chart_key in chart_paths:
                            setattr(
                                run,
                                model_field,
                                f"reports/{run_folder_name}/{Path(chart_paths[chart_key]).name}",
                            )

                    if result.energy_residual_pct is not None:
                        run.energy_residual_pct = float(result.energy_residual_pct)
                    if result.energy_input_cum is not None and len(result.energy_input_cum):
                        run.energy_input_total = float(result.energy_input_cum[-1])
                    if result.energy_brake_cum is not None and len(result.energy_brake_cum):
                        run.energy_brake_total = float(result.energy_brake_cum[-1])

                    report_name = f"{prefix}_report.xlsx"
                    report_path = run_reports_dir / report_name
                    export_results_to_excel(result, report_path)
                    run.report_file.name = f"reports/{run_folder_name}/{report_name}"

                    run.save()

                    calculation_model = build_calculation_model(run, brake_objects, result)
                    calculation_model, analysis_snapshot = enrich_with_basic_analysis(calculation_model)

                    CalculationSnapshot.objects.update_or_create(
                        run=run,
                        defaults={
                            "model_version": calculation_model.model_version,
                            "input_snapshot": calculation_model.input_snapshot(),
                            "result_snapshot": calculation_model.result_snapshot(),
                            "analysis_snapshot": analysis_snapshot,
                            "thermal_snapshot": {},
                        },
                    )

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

    runs = CalculationRun.objects.order_by("-created_at")[:20]

    # Срез 3b: каталог тормозов для выбора в форме.
    catalog_qs = BrakeCatalog.objects.order_by("name")
    catalog_items = []
    for c in catalog_qs:
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


def run_detail_v2_view(request, run_id):
    """Страница результата расчёта.

    KPI-карточки, аннотированный главный график x(t), энергобаланс, табы графиков.
    """
    run = get_object_or_404(CalculationRun, pk=run_id)
    brakes = list(run.brakes.order_by("index"))

    chart_fields = [
        # v2-специфичные
        "chart_x_t_annotated",
        "chart_energy",
        # общие
        "chart_x_t",
        "chart_v_a_t",
        "chart_v_x",
        "chart_fmag_v",
        "chart_forces_secondary",
        # фаза отката
        "chart_x_t_recoil",
        "chart_v_a_t_recoil",
        "chart_forces_main_recoil",
        "chart_forces_secondary_recoil",
        # фаза наката
        "chart_x_t_return",
        "chart_v_a_t_return",
        "chart_forces_secondary_return",
    ]

    chart_html: dict[str, str] = {}
    chart_errors: list[str] = []
    for field_name in chart_fields:
        field_file = getattr(run, field_name, None)
        if field_file and getattr(field_file, "name", ""):
            try:
                chart_html[field_name] = _read_chart_fragment(field_file.path)
            except (FileNotFoundError, OSError) as exc:
                chart_html[field_name] = ""
                chart_errors.append(f"{field_name}: файл не найден ({exc})")
            except UnicodeDecodeError as exc:
                chart_html[field_name] = ""
                chart_errors.append(f"{field_name}: ошибка кодировки ({exc})")
            except Exception as exc:  # noqa: BLE001
                chart_html[field_name] = ""
                chart_errors.append(f"{field_name}: {type(exc).__name__}: {exc}")

    has_annotated = bool(chart_html.get("chart_x_t_annotated"))
    has_energy = bool(chart_html.get("chart_energy"))
    has_x_t = bool(chart_html.get("chart_x_t"))

    snapshot_parts = extract_snapshot_parts(run)
    kpi_groups = build_kpi_groups(run, snapshot_parts)

    energy_summary = None
    if run.energy_residual_pct is not None or run.energy_input_total is not None:
        energy_summary = {
            "input_total": run.energy_input_total,
            "brake_total": run.energy_brake_total,
            "residual_pct": run.energy_residual_pct,
        }

    has_charts_main = any(chart_html.get(k) for k in [
        "chart_x_t", "chart_v_a_t", "chart_v_x", "chart_fmag_v", "chart_forces_secondary"
    ])
    has_charts_recoil = any(chart_html.get(k) for k in [
        "chart_x_t_recoil", "chart_v_a_t_recoil", "chart_forces_main_recoil", "chart_forces_secondary_recoil"
    ])
    has_charts_return = any(chart_html.get(k) for k in [
        "chart_x_t_return", "chart_v_a_t_return", "chart_forces_secondary_return"
    ])

    thermal_runs_preview = list(run.thermal_runs.order_by("-created_at")[:3])
    thermal_runs_total = run.thermal_runs.count()

    return render(
        request,
        "recoil_app/run_detail_v2.html",
        {
            "run": run,
            "brakes": brakes,
            "chart_html": chart_html,
            "has_annotated": has_annotated,
            "has_energy": has_energy,
            "has_x_t": has_x_t,
            "has_charts_main": has_charts_main,
            "has_charts_recoil": has_charts_recoil,
            "has_charts_return": has_charts_return,
            "chart_errors": chart_errors,
            "kpi_groups": kpi_groups,
            "energy_summary": energy_summary,
            "phase_analysis": snapshot_parts["phase_analysis"],
            "characteristic_points": snapshot_parts["characteristic_points"],
            "engineering_metrics": snapshot_parts["engineering_metrics"],
            "thermal_runs_preview": thermal_runs_preview,
            "thermal_runs_total": thermal_runs_total,
        },
    )


@require_POST
def delete_run_view(request, run_id):
    run = get_object_or_404(CalculationRun, pk=run_id)

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


def _read_chart_fragment(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")

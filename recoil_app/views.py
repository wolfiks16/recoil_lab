import shutil
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import CalculationForm, CompareRunsForm, MagneticBrakeFormSet
from .models import (
    BrakeForcePoint,
    CalculationRun,
    CalculationSnapshot,
    MagneticBrakeConfig,
)
from .services.analysis import enrich_with_basic_analysis
from .services.charting import save_interactive_charts
from .services.dynamics import RecoilParams, simulate_recoil
from .services.magnetic import (
    CurveBrakeParams,
    ForceCurvePoint,
    MagneticParams,
)
from .services.modeling import build_calculation_model
from .services.reporting import export_results_to_excel


COMPARE_CHART_FIELDS = [
    ("chart_x_t", "Перемещение от времени"),
    ("chart_v_a_t", "Скорость и ускорение от времени"),
    ("chart_v_x", "Скорость от перемещения"),
    ("chart_fmag_v", "Магнитные силы от скорости"),
    ("chart_forces_secondary", "Распределение сил от времени"),
    ("chart_x_t_recoil", "Перемещение — откат"),
    ("chart_v_a_t_recoil", "Скорость и ускорение — откат"),
    ("chart_forces_main_recoil", "Движущая и общая сила — откат"),
    ("chart_forces_secondary_recoil", "Распределение сил — откат"),
    ("chart_x_t_return", "Перемещение — накат"),
    ("chart_v_a_t_return", "Скорость и ускорение — накат"),
    ("chart_forces_secondary_return", "Распределение сил — накат"),
]


def _build_initial_from_run(run_id: str | None) -> tuple[dict, list[dict]]:
    initial_main: dict = {}
    brakes_initial: list[dict] = []

    if not run_id:
        return initial_main, brakes_initial

    try:
        source_run = CalculationRun.objects.get(pk=run_id)
    except CalculationRun.DoesNotExist:
        return initial_main, brakes_initial

    initial_main = {
        "name": f"{source_run.name}_1",
        "mass": source_run.mass,
        "angle_deg": source_run.angle_deg,
        "v0": source_run.v0,
        "x0": source_run.x0,
        "t_max": source_run.t_max,
        "dt": source_run.dt,
    }

    for brake in source_run.brakes.order_by("index"):
        brake_initial = {
            "model_type": brake.model_type,
            "name": brake.name,
            "gamma": brake.gamma,
            "delta": brake.delta,
            "xm": brake.xm,
            "ym": brake.ym,
            "dh1": brake.dh1,
            "dh2": brake.dh2,
            "dm": brake.dm,
            "n": brake.n,
            "mu": brake.mu,
            "bz": brake.bz,
            "lya": brake.lya,
            "wn0": brake.wn0,
        }

        if brake.model_type == MagneticBrakeConfig.MODEL_TYPE_CURVE:
            brake_initial["curve_source_brake_id"] = str(brake.pk)

        brakes_initial.append(brake_initial)

    return initial_main, brakes_initial


def _magnetic_params_from_cleaned_data(cleaned_data: dict) -> MagneticParams:
    return MagneticParams(
        gamma=cleaned_data["gamma"],
        delta=cleaned_data["delta"],
        xm=cleaned_data["xm"],
        ym=cleaned_data["ym"],
        dh1=cleaned_data["dh1"],
        dh2=cleaned_data["dh2"],
        dm=cleaned_data["dm"],
        n=cleaned_data["n"],
        mu=cleaned_data["mu"],
        bz=cleaned_data["bz"],
        lya=cleaned_data["lya"],
        wn0=cleaned_data["wn0"],
    )


def _curve_params_from_points(points: list[dict]) -> CurveBrakeParams:
    return CurveBrakeParams(
        points=tuple(
            ForceCurvePoint(
                velocity=point["velocity"],
                force=point["force"],
            )
            for point in points
        )
    )


def _read_chart_fragment(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _collect_chart_html(run: CalculationRun) -> dict[str, str]:
    chart_html: dict[str, str] = {}

    for field_name, _ in COMPARE_CHART_FIELDS:
        field_file = getattr(run, field_name, None)
        if field_file:
            try:
                chart_html[field_name] = _read_chart_fragment(field_file.path)
            except FileNotFoundError:
                chart_html[field_name] = ""

    return chart_html


def _build_compare_chart_blocks(
    run_a: CalculationRun | None,
    run_b: CalculationRun | None,
) -> list[dict]:
    if not run_a or not run_b:
        return []

    chart_html_a = _collect_chart_html(run_a)
    chart_html_b = _collect_chart_html(run_b)

    blocks = []
    for field_name, title in COMPARE_CHART_FIELDS:
        html_a = chart_html_a.get(field_name, "")
        html_b = chart_html_b.get(field_name, "")
        if html_a or html_b:
            blocks.append(
                {
                    "field_name": field_name,
                    "title": title,
                    "html_a": html_a,
                    "html_b": html_b,
                }
            )
    return blocks


def _extract_snapshot_parts(run: CalculationRun) -> dict:
    phase_analysis = {}
    characteristic_points = {}
    engineering_metrics = {}

    try:
        snapshot = run.snapshot
        analysis_snapshot = snapshot.analysis_snapshot or {}
        phase_analysis = analysis_snapshot.get("phase_analysis", {})
        characteristic_points = analysis_snapshot.get("characteristic_points", {})
        engineering_metrics = analysis_snapshot.get("engineering_metrics", {})
    except CalculationSnapshot.DoesNotExist:
        pass

    return {
        "phase_analysis": phase_analysis,
        "characteristic_points": characteristic_points,
        "engineering_metrics": engineering_metrics,
    }


def _load_curve_points_from_source_brake(source_brake_id: str) -> list[dict]:
    source_brake = MagneticBrakeConfig.objects.filter(pk=source_brake_id).first()
    if source_brake is None:
        raise ValueError("Исходный тормоз для curve-характеристики не найден.")

    if source_brake.model_type != MagneticBrakeConfig.MODEL_TYPE_CURVE:
        raise ValueError("Указанный исходный тормоз не является curve-тормозом.")

    points_qs = source_brake.force_points.order_by("order", "id")
    points = [
        {
            "order": int(point.order),
            "velocity": float(point.velocity),
            "force": float(point.force),
        }
        for point in points_qs
    ]

    if len(points) < 2:
        raise ValueError(
            "У исходного curve-тормоза недостаточно точек характеристики F(v)."
        )

    return points


def _resolve_curve_sources(brake_formset) -> bool:
    ok = True

    for form in brake_formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        if not form.cleaned_data:
            continue

        cleaned = form.cleaned_data
        if cleaned.get("model_type") != MagneticBrakeConfig.MODEL_TYPE_CURVE:
            continue

        parsed_points = cleaned.get("parsed_force_curve_points")
        if parsed_points:
            continue

        source_brake_id = (cleaned.get("curve_source_brake_id") or "").strip()
        if not source_brake_id:
            form.add_error(
                "force_curve_file",
                "Не удалось определить источник характеристики curve-тормоза.",
            )
            ok = False
            continue

        try:
            resolved_points = _load_curve_points_from_source_brake(source_brake_id)
        except ValueError as exc:
            form.add_error("force_curve_file", str(exc))
            ok = False
            continue

        cleaned["parsed_force_curve_points"] = resolved_points

    return ok


def _copy_curve_file_from_source(
    source_brake: MagneticBrakeConfig,
    target_brake: MagneticBrakeConfig,
) -> None:
    if not source_brake.curve_file:
        return

    source_brake.curve_file.open("rb")
    try:
        content = source_brake.curve_file.read()
    finally:
        source_brake.curve_file.close()

    original_name = Path(source_brake.curve_file.name).name or "curve.xlsx"
    target_brake.curve_file.save(original_name, ContentFile(content), save=True)


def _create_brake_objects_and_runtime_models(
    run: CalculationRun,
    brake_formset,
) -> tuple[list[MagneticBrakeConfig], list[MagneticParams | CurveBrakeParams]]:
    brake_objects: list[MagneticBrakeConfig] = []
    runtime_brakes: list[MagneticParams | CurveBrakeParams] = []

    next_index = 1
    for form in brake_formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        if not form.cleaned_data:
            continue

        cleaned = form.cleaned_data
        model_type = cleaned["model_type"]
        uploaded_curve_file = cleaned.get("force_curve_file")
        source_brake_id = (cleaned.get("curve_source_brake_id") or "").strip()

        brake_obj = MagneticBrakeConfig.objects.create(
            run=run,
            index=next_index,
            model_type=model_type,
            name=cleaned.get("name", ""),
            curve_file=uploaded_curve_file if model_type == MagneticBrakeConfig.MODEL_TYPE_CURVE else None,
            gamma=cleaned.get("gamma"),
            delta=cleaned.get("delta"),
            xm=cleaned.get("xm"),
            ym=cleaned.get("ym"),
            dh1=cleaned.get("dh1"),
            dh2=cleaned.get("dh2"),
            dm=cleaned.get("dm"),
            n=cleaned.get("n"),
            mu=cleaned.get("mu"),
            bz=cleaned.get("bz"),
            lya=cleaned.get("lya"),
            wn0=cleaned.get("wn0"),
        )

        if model_type == MagneticBrakeConfig.MODEL_TYPE_CURVE:
            parsed_points = cleaned.get("parsed_force_curve_points", [])

            point_objects = [
                BrakeForcePoint(
                    brake=brake_obj,
                    order=point["order"],
                    velocity=point["velocity"],
                    force=point["force"],
                )
                for point in parsed_points
            ]
            if point_objects:
                BrakeForcePoint.objects.bulk_create(point_objects)

            if not uploaded_curve_file and source_brake_id:
                source_brake = MagneticBrakeConfig.objects.filter(pk=source_brake_id).first()
                if source_brake is not None:
                    _copy_curve_file_from_source(source_brake, brake_obj)

            runtime_brakes.append(_curve_params_from_points(parsed_points))
        else:
            runtime_brakes.append(_magnetic_params_from_cleaned_data(cleaned))

        brake_objects.append(brake_obj)
        next_index += 1

    return brake_objects, runtime_brakes


def compare_view(request):
    form = CompareRunsForm(request.GET or None)

    run_a = None
    run_b = None
    compare_chart_blocks = []
    compare_a = {}
    compare_b = {}

    if form.is_valid():
        run_a = form.cleaned_data["run_a"]
        run_b = form.cleaned_data["run_b"]
        compare_chart_blocks = _build_compare_chart_blocks(run_a, run_b)
        compare_a = _extract_snapshot_parts(run_a)
        compare_b = _extract_snapshot_parts(run_b)

    return render(
        request,
        "recoil_app/compare.html",
        {
            "form": form,
            "run_a": run_a,
            "run_b": run_b,
            "compare_chart_blocks": compare_chart_blocks,
            "compare_a": compare_a,
            "compare_b": compare_b,
        },
    )


def index_view(request):
    if request.method == "POST":
        form = CalculationForm(request.POST, request.FILES)
        brake_formset = MagneticBrakeFormSet(request.POST, request.FILES, prefix="brakes")

        forms_valid = form.is_valid() and brake_formset.is_valid()
        curve_sources_valid = _resolve_curve_sources(brake_formset) if forms_valid else False

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

                    brake_objects, runtime_brakes = _create_brake_objects_and_runtime_models(
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
                    }

                    for chart_key, model_field in field_map.items():
                        if chart_key in chart_paths:
                            setattr(
                                run,
                                model_field,
                                f"reports/{run_folder_name}/{Path(chart_paths[chart_key]).name}",
                            )

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

                return redirect("run_detail", run_id=run.id)

            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        initial_main, brakes_initial = _build_initial_from_run(request.GET.get("from_run"))
        form = CalculationForm(initial=initial_main)

        if brakes_initial:
            brake_formset = MagneticBrakeFormSet(initial=brakes_initial, prefix="brakes")
        else:
            brake_formset = MagneticBrakeFormSet(initial=[{}, {}], prefix="brakes")

    runs = CalculationRun.objects.order_by("-created_at")[:20]
    return render(
        request,
        "recoil_app/index.html",
        {
            "form": form,
            "brake_formset": brake_formset,
            "runs": runs,
        },
    )


def run_detail_view(request, run_id):
    run = get_object_or_404(CalculationRun, pk=run_id)
    brakes = list(run.brakes.order_by("index"))

    chart_fields = [
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
    ]

    chart_html: dict[str, str] = {}

    for field_name in chart_fields:
        field_file = getattr(run, field_name, None)
        if field_file:
            try:
                chart_html[field_name] = _read_chart_fragment(field_file.path)
            except FileNotFoundError:
                chart_html[field_name] = ""

    analysis_snapshot = {}
    phase_analysis = {}
    characteristic_points = {}
    engineering_metrics = {}

    try:
        snapshot = run.snapshot
        analysis_snapshot = snapshot.analysis_snapshot or {}
        phase_analysis = analysis_snapshot.get("phase_analysis", {})
        characteristic_points = analysis_snapshot.get("characteristic_points", {})
        engineering_metrics = analysis_snapshot.get("engineering_metrics", {})
    except CalculationSnapshot.DoesNotExist:
        analysis_snapshot = {}
        phase_analysis = {}
        characteristic_points = {}
        engineering_metrics = {}

    return render(
        request,
        "recoil_app/run_detail.html",
        {
            "run": run,
            "brakes": brakes,
            "chart_html": chart_html,
            "analysis_snapshot": analysis_snapshot,
            "phase_analysis": phase_analysis,
            "characteristic_points": characteristic_points,
            "engineering_metrics": engineering_metrics,
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
    return redirect("index")
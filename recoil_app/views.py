import shutil
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import CalculationForm, CompareRunsForm, MagneticBrakeFormSet
from .models import CalculationRun, CalculationSnapshot, MagneticBrakeConfig
from .services.charting import save_interactive_charts
from .services.dynamics import RecoilParams, simulate_recoil
from .services.magnetic import MagneticParams
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
        brakes_initial.append(
            {
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
        )

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


def _build_compare_chart_blocks(run_a: CalculationRun | None, run_b: CalculationRun | None) -> list[dict]:
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


def compare_view(request):
    form = CompareRunsForm(request.GET or None)

    run_a = None
    run_b = None
    compare_chart_blocks = []

    if form.is_valid():
        run_a = form.cleaned_data["run_a"]
        run_b = form.cleaned_data["run_b"]
        compare_chart_blocks = _build_compare_chart_blocks(run_a, run_b)

    return render(
        request,
        "recoil_app/compare.html",
        {
            "form": form,
            "run_a": run_a,
            "run_b": run_b,
            "compare_chart_blocks": compare_chart_blocks,
        },
    )


def index_view(request):
    if request.method == "POST":
        form = CalculationForm(request.POST, request.FILES)
        brake_formset = MagneticBrakeFormSet(request.POST, prefix="brakes")

        if form.is_valid() and brake_formset.is_valid():
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

            brake_objects: list[MagneticBrakeConfig] = []
            magnetic_list: list[MagneticParams] = []

            for index, brake_form in enumerate(brake_formset.cleaned_data, start=1):
                if not brake_form:
                    continue

                brake_obj = MagneticBrakeConfig.objects.create(
                    run=run,
                    index=index,
                    gamma=brake_form["gamma"],
                    delta=brake_form["delta"],
                    xm=brake_form["xm"],
                    ym=brake_form["ym"],
                    dh1=brake_form["dh1"],
                    dh2=brake_form["dh2"],
                    dm=brake_form["dm"],
                    n=brake_form["n"],
                    mu=brake_form["mu"],
                    bz=brake_form["bz"],
                    lya=brake_form["lya"],
                    wn0=brake_form["wn0"],
                )
                brake_objects.append(brake_obj)
                magnetic_list.append(_magnetic_params_from_cleaned_data(brake_form))

            recoil = RecoilParams(
                mass=run.mass,
                angle_deg=run.angle_deg,
                v0=run.v0,
                x0=run.x0,
                t_max=run.t_max,
                dt=run.dt,
            )

            result = simulate_recoil(run.input_file.path, recoil, magnetic_list)

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

            CalculationSnapshot.objects.update_or_create(
                run=run,
                defaults={
                    "model_version": calculation_model.model_version,
                    "input_snapshot": calculation_model.input_snapshot(),
                    "result_snapshot": calculation_model.result_snapshot(),
                    "analysis_snapshot": {},
                    "thermal_snapshot": {},
                },
            )

            return redirect("run_detail", run_id=run.id)
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

    return render(
        request,
        "recoil_app/run_detail.html",
        {
            "run": run,
            "brakes": brakes,
            "chart_html": chart_html,
            "brake_speed_charts": [],
        },
    )


@require_POST
def delete_run_view(request, run_id):
    run = get_object_or_404(CalculationRun, pk=run_id)

    folder_path: Path | None = None
    if run.report_file and run.report_file.name:
        folder_path = Path(settings.MEDIA_ROOT) / Path(run.report_file.name).parent

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
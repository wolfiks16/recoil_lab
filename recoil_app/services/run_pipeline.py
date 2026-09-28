"""Бизнес-логика создания нового расчёта (`index_view` POST).

Сюда вынесены чисто-доменные операции, не зависящие от HTTP:
- `build_initial_from_run` — initial для form/formset из существующего расчёта (GET сценарий «скопировать»);
- `resolve_curve_sources` — для curve-тормозов без uploaded_file разрешает источник характеристики;
- `create_brake_objects_and_runtime_models` — создаёт `MagneticBrakeConfig` + `BrakeForcePoint`'ы и собирает runtime-модели для симулятора;
- `persist_result_and_snapshot` — общий хвост «сохранить результат»: метрики, графики, XLSX, snapshot
  (для всех способов создания расчёта: откат, свободное падение, отпочкование дизайна, итерационный).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.text import slugify

from ..models import (
    BrakeCatalog,
    BrakeForcePoint,
    CalculationRun,
    CalculationSnapshot,
    MagneticBrakeConfig,
)
from .analysis import enrich_with_basic_analysis
from .charting import save_interactive_charts
from .curve_parser import parse_force_curve_sheet
from .fv_reference import build_fv_reference, configs_from_stage_overlay
from .iterative.config import slot_from_brake_config
from .magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams
from .modeling import build_calculation_model
from .reporting import export_results_to_excel

_CHART_FIELDS = (
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
    # --- v2 ---
    "chart_x_t_annotated",
    "chart_energy",
)


def persist_result_and_snapshot(
    run: CalculationRun,
    brake_objects,
    result,
    *,
    input_extra: dict | None = None,
    result_extra: dict | None = None,
    stage_overlay: dict | None = None,
) -> None:
    """Сохраняет результат симуляции: метрики, графики, XLSX, snapshot.

    Общий хвост для всех способов создания расчёта. None-safe к отсутствию фаз
    отката/наката (свободное падение, остановленный итерационный расчёт).
    `input_extra`/`result_extra` — дополнительные ключи верхнего уровня в
    input/result snapshot (итерационный расчёт кладёт туда этапы).
    `stage_overlay` — этапы итерационного расчёта для графиков и XLSX
    (`services/iterative/overlay.build_stage_overlay`).
    """
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

    chart_paths = save_interactive_charts(
        result, run_reports_dir, prefix=prefix, stage_overlay=stage_overlay,
        fv_reference=_fv_reference(brake_objects, result, stage_overlay),
    )

    for field_name in _CHART_FIELDS:
        if field_name in chart_paths:
            setattr(
                run,
                field_name,
                f"reports/{run_folder_name}/{Path(chart_paths[field_name]).name}",
            )

    if result.energy_residual_pct is not None:
        run.energy_residual_pct = float(result.energy_residual_pct)
    if result.energy_input_cum is not None and len(result.energy_input_cum):
        run.energy_input_total = float(result.energy_input_cum[-1])
    if result.energy_brake_cum is not None and len(result.energy_brake_cum):
        run.energy_brake_total = float(result.energy_brake_cum[-1])

    report_name = f"{prefix}_report.xlsx"
    report_path = run_reports_dir / report_name
    export_results_to_excel(result, report_path, stage_overlay=stage_overlay)
    run.report_file.name = f"reports/{run_folder_name}/{report_name}"

    run.save()

    calculation_model = build_calculation_model(run, brake_objects, result)
    calculation_model, analysis_snapshot = enrich_with_basic_analysis(calculation_model)

    input_snapshot = calculation_model.input_snapshot()
    result_snapshot = calculation_model.result_snapshot()
    input_snapshot.update(input_extra or {})
    result_snapshot.update(result_extra or {})

    CalculationSnapshot.objects.update_or_create(
        run=run,
        defaults={
            "model_version": calculation_model.model_version,
            "input_snapshot": input_snapshot,
            "result_snapshot": result_snapshot,
            "analysis_snapshot": analysis_snapshot,
            "thermal_snapshot": {},
        },
    )


def build_initial_from_run(run_id: str | None) -> tuple[dict, list[dict]]:
    """Заполняет initial для CalculationForm и MagneticBrakeFormSet из существующего расчёта.

    Используется для сценария `?from_run=<id>` на `/new/`. Имя получает суффикс `_1`.
    """
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


def resolve_curve_sources(brake_formset) -> bool:
    """Для curve-тормозов без uploaded_file подтягивает точки F(v) из существующего тормоза.

    Возвращает True если все источники разрешены, False если хотя бы один не нашёлся
    (в этом случае на форму добавлены ошибки).
    """
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


def create_brake_objects_and_runtime_models(
    run: CalculationRun,
    brake_formset,
) -> tuple[list[MagneticBrakeConfig], list[MagneticParams | CurveBrakeParams]]:
    """Создаёт `MagneticBrakeConfig` + `BrakeForcePoint`'ы из formset'а
    и параллельно собирает runtime-модели для передачи в симулятор.
    """
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
        catalog_source_id = cleaned.get("catalog_source_id")

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

            # Срез 3b: если выбран тормоз из каталога и файл сам не загружен —
            # копируем curve_file из каталога и парсим его в точки.
            if not uploaded_curve_file and not source_brake_id and catalog_source_id and not parsed_points:
                catalog_entry = BrakeCatalog.objects.filter(pk=catalog_source_id).first()
                if catalog_entry is not None and catalog_entry.curve_file:
                    _copy_curve_file_from_catalog(catalog_entry, brake_obj)
                    try:
                        parsed_points = load_catalog_curve_points(catalog_entry)
                    except Exception:
                        # Если файл не парсится — оставляем пустые точки.
                        # Расчёт упадёт в _curve_params_from_points с понятной ошибкой.
                        parsed_points = []

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


def _fv_reference(brake_objects, result, stage_overlay: dict | None) -> dict | None:
    """Характеристики тормозов (модель) для графика «Сила торможения от скорости».

    Итерационный расчёт — по конфигурациям этапов, обычный — по тормозам расчёта.
    Любая ошибка здесь не должна валить сохранение расчёта: график тогда без фона.
    """
    try:
        if stage_overlay:
            return build_fv_reference(result, configs_from_stage_overlay(stage_overlay),
                                      stage_overlay["stage_index"])
        return build_fv_reference(result, [[slot_from_brake_config(b) for b in brake_objects]])
    except Exception:  # noqa: BLE001 — фон графика необязателен
        return None


def load_catalog_curve_points(catalog_entry: BrakeCatalog) -> list[dict]:
    """Точки F(v) из curve-файла записи каталога (`[{order, velocity, force}]`).

    Бросает исключение, если файла нет или он не парсится — вызывающий решает,
    что с этим делать.
    """
    if not catalog_entry.curve_file:
        raise ValueError(f"У тормоза каталога «{catalog_entry.name}» нет файла характеристики F(v).")
    from openpyxl import load_workbook  # локальный импорт

    catalog_entry.curve_file.open("rb")
    try:
        workbook = load_workbook(catalog_entry.curve_file, read_only=True, data_only=True)
        try:
            return parse_force_curve_sheet(workbook.active)
        finally:
            workbook.close()
    finally:
        catalog_entry.curve_file.close()


# === ВНУТРЕННИЕ ХЕЛПЕРЫ ===

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


def _copy_curve_file_from_catalog(
    catalog_entry: BrakeCatalog,
    target_brake: MagneticBrakeConfig,
) -> None:
    """Копирует curve_file из каталога в новую запись расчёта (copy-on-use)."""
    if not catalog_entry.curve_file:
        return

    catalog_entry.curve_file.open("rb")
    try:
        content = catalog_entry.curve_file.read()
    finally:
        catalog_entry.curve_file.close()

    original_name = Path(catalog_entry.curve_file.name).name or "curve.xlsx"
    target_brake.curve_file.save(original_name, ContentFile(content), save=True)

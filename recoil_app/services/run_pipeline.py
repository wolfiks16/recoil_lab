"""Бизнес-логика создания нового расчёта (`index_view` POST).

Сюда вынесены чисто-доменные операции, не зависящие от HTTP:
- `build_initial_from_run` — initial для form/formset из существующего расчёта (GET сценарий «скопировать»);
- `resolve_curve_sources` — для curve-тормозов без uploaded_file разрешает источник характеристики;
- `create_brake_objects_and_runtime_models` — создаёт `MagneticBrakeConfig` + `BrakeForcePoint`'ы и собирает runtime-модели для симулятора.
"""

from __future__ import annotations

from pathlib import Path

from django.core.files.base import ContentFile

from ..models import BrakeCatalog, BrakeForcePoint, CalculationRun, MagneticBrakeConfig
from .curve_parser import parse_force_curve_sheet
from .magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams


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
                        catalog_entry.curve_file.open("rb")
                        try:
                            from openpyxl import load_workbook  # локальный импорт
                            workbook = load_workbook(
                                catalog_entry.curve_file,
                                read_only=True,
                                data_only=True,
                            )
                            try:
                                parsed_points = parse_force_curve_sheet(workbook.active)
                            finally:
                                workbook.close()
                        finally:
                            catalog_entry.curve_file.close()
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

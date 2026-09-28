"""Редактор конфигурации тормозов: форма (`IterativeSlotFormSet`) ↔ слоты движка.

- `slots_initial(...)` — initial для formset'а: текущая конфигурация сессии
  (для «Изменить конфигурацию») или тормоза расчёта-донора (старт «с этого
  расчёта»). У выключенного/табличного слота параметрические поля
  заполняются последними известными параметрами этого тормоза — чтобы
  включение обратно не требовало вводить всё заново.
- `slots_from_formset(...)` — собрать конфигурацию из провалидированного
  formset'а. Табличная F(v): загруженный файл → каталог → тормоз донора →
  «оставить текущую».
Модуль про Django-модели знает (каталог, донор) — поэтому не импортируется
из `services/iterative/__init__`.
"""

from __future__ import annotations

from dataclasses import asdict

from ...models import BrakeCatalog, CalculationRun, MagneticBrakeConfig
from ..magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams
from ..run_pipeline import load_catalog_curve_points
from .config import Config, Slot, config_from_list, curve_summary, slot_from_brake_config
from .session import IterativeSession

KIND_PARAMETRIC = "parametric"
KIND_CURVE = "curve"
KIND_OFF = "off"

PARAM_FIELDS = ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")


# ------------------------------------------------------------------ initial

def _slot_initial(slot: Slot, fallback: MagneticParams | None, *, keep_curve: bool) -> dict:
    params = slot if isinstance(slot, MagneticParams) else fallback
    initial: dict = asdict(params) if params is not None else {"lya": 2.5, "wn0": 1.0}
    if slot is None:
        initial["kind"] = KIND_OFF
    elif isinstance(slot, MagneticParams):
        initial["kind"] = KIND_PARAMETRIC
    else:
        initial["kind"] = KIND_CURVE
        initial["keep_curve"] = keep_curve
        initial["curve_info"] = curve_summary(slot)
    return initial


def _last_parametric(session: IterativeSession, slot_index: int) -> MagneticParams | None:
    for stage in reversed(session.stages[: session.active_stage + 1]):
        model = stage.config[slot_index]
        if isinstance(model, MagneticParams):
            return model
    return None


def slots_initial_from_session(session: IterativeSession) -> list[dict]:
    """Текущая конфигурация сессии (для редактора «Изменить конфигурацию»)."""
    return [
        _slot_initial(slot, _last_parametric(session, k), keep_curve=True)
        for k, slot in enumerate(session.config)
    ]


def slots_initial_from_run(run: CalculationRun) -> list[dict]:
    """Тормоза расчёта-донора (старт итерационного расчёта «с этого расчёта»).

    У итогов итерационного расчёта (`is_iterative`) берётся исходная
    конфигурация — этап 0. Табличная F(v) подтягивается из «физического»
    тормоза донора (`source_brake_id`): у включённого на этапе 0 тормоза его
    запись и хранит конфигурацию этапа 0.
    """
    brakes = {b.index: b for b in run.brakes.all()}
    stage0 = run.brake_stages.filter(stage=0).first() if run.is_iterative else None
    if stage0 is not None:
        slots = list(config_from_list(stage0.config))
    else:
        slots = [slot_from_brake_config(brakes[i]) for i in sorted(brakes)]

    initial = []
    for k, slot in enumerate(slots):
        brake = brakes.get(k + 1)
        fallback = None
        if (brake is not None and brake.model_type == MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC
                and brake.gamma is not None):
            fallback = slot_from_brake_config(brake)
        item = _slot_initial(slot, fallback, keep_curve=False)
        if (isinstance(slot, CurveBrakeParams) and brake is not None
                and brake.model_type == MagneticBrakeConfig.MODEL_TYPE_CURVE):
            item["source_brake_id"] = brake.pk
        initial.append(item)
    return initial


# ------------------------------------------------------------------ сборка

def _points_to_curve(points: list[dict]) -> CurveBrakeParams:
    return CurveBrakeParams(points=tuple(
        ForceCurvePoint(velocity=float(p["velocity"]), force=float(p["force"])) for p in points
    ))


def _slot_from_cleaned(cleaned: dict, current: Slot, number: int) -> Slot:
    kind = cleaned.get("kind")
    if kind == KIND_OFF:
        return None
    if kind == KIND_PARAMETRIC:
        values = {f: cleaned[f] for f in PARAM_FIELDS}
        values["n"] = int(values["n"])
        return MagneticParams(**values)

    # Табличный.
    if cleaned.get("parsed_points"):
        return _points_to_curve(cleaned["parsed_points"])
    catalog_id = cleaned.get("catalog_source_id")
    if catalog_id:
        entry = BrakeCatalog.objects.filter(pk=catalog_id).first()
        if entry is None:
            raise ValueError(f"Тормоз {number}: запись каталога не найдена.")
        try:
            return _points_to_curve(load_catalog_curve_points(entry))
        except Exception as exc:  # noqa: BLE001 — любая ошибка чтения файла каталога
            raise ValueError(f"Тормоз {number}: не удалось прочитать F(v) из каталога ({exc}).") from exc
    source_brake_id = cleaned.get("source_brake_id")
    if source_brake_id:
        brake = MagneticBrakeConfig.objects.filter(pk=source_brake_id).first()
        if brake is None or brake.model_type != MagneticBrakeConfig.MODEL_TYPE_CURVE:
            raise ValueError(f"Тормоз {number}: исходная таблица F(v) не найдена.")
        return slot_from_brake_config(brake)
    if cleaned.get("keep_curve") and isinstance(current, CurveBrakeParams):
        return current
    raise ValueError(f"Тормоз {number}: загрузите Excel-файл F(v) или выберите тормоз из каталога.")


def slots_from_formset(formset, current: Config | None = None) -> list[Slot]:
    """Конфигурация из провалидированного formset'а.

    `current` — текущая конфигурация сессии (при смене): её тормоза удалять
    нельзя (только выключать), новые добавляются в конец.
    """
    current = tuple(current or ())
    slots: list[Slot] = []
    for position, form in enumerate(formset.forms):
        cleaned = getattr(form, "cleaned_data", None) or {}
        if cleaned.get("DELETE"):
            if position < len(current):
                raise ValueError(
                    f"Тормоз {position + 1} уже участвует в расчёте — его нельзя удалить, "
                    "только выключить."
                )
            continue
        if not cleaned:
            continue
        existing = current[position] if position < len(current) else None
        slots.append(_slot_from_cleaned(cleaned, existing, len(slots) + 1))

    if len(slots) < len(current):
        raise ValueError("Нельзя удалить тормоз из конфигурации — выключите его.")
    if not slots:
        raise ValueError("Задайте хотя бы один тормоз.")
    return slots

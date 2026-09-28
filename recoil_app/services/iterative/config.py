"""Конфигурации тормозов итерационного расчёта.

Конфигурация — кортеж «слотов» фиксированной позиции: слот i — это тормоз №i+1.
Значение слота — рабочая модель (`MagneticParams` / `CurveBrakeParams`) или
`None` («тормоз отключён», F = 0). Слоты можно только добавлять: удаление =
отключение, чтобы номера тормозов (их силы в истории, тепло) не сдвигались.
Добавленный на этапе k слот на всех прошлых этапах считается отключённым.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Optional, TypeAlias

from ..magnetic import (
    BrakeModel,
    CurveBrakeParams,
    ForceCurvePoint,
    MagneticParams,
    initial_brake_state,
)

Slot: TypeAlias = Optional[BrakeModel]
Config: TypeAlias = tuple[Slot, ...]

KIND_PARAMETRIC = "parametric"
KIND_CURVE = "curve"
KIND_OFF = "off"

KIND_LABELS = {KIND_PARAMETRIC: "парам.", KIND_CURVE: "табл.", KIND_OFF: "выкл."}


def slot_kind(slot: Slot) -> str:
    if slot is None:
        return KIND_OFF
    if isinstance(slot, MagneticParams):
        return KIND_PARAMETRIC
    return KIND_CURVE


def normalize_config(config: Iterable[Slot], n_slots: int = 0) -> Config:
    """Кортеж слотов, дополненный отключёнными до `n_slots` (если короче)."""
    slots = tuple(config)
    if not slots and n_slots <= 0:
        raise ValueError("Конфигурация должна содержать хотя бы один тормоз.")
    for i, slot in enumerate(slots):
        if slot is not None and not isinstance(slot, (MagneticParams, CurveBrakeParams)):
            raise ValueError(f"Тормоз {i + 1}: неизвестный тип модели {type(slot).__name__}.")
    if len(slots) < n_slots:
        slots = slots + (None,) * (n_slots - len(slots))
    return slots


def slot_changed(old: Slot, new: Slot) -> bool:
    """Изменилась ли модель слота (тип, любой параметр, точки кривой, вкл/выкл)."""
    return old != new


def initial_slot_state(slot: Slot) -> float:
    """Начальное состояние слота: wn0 параметрического, 0 у табличного/отключённого."""
    return initial_brake_state(slot) if slot is not None else 0.0


def config_diff(old: Config, new: Config) -> list[str]:
    """Изменения конфигурации по тормозам в читаемом виде («тормоз 2: bz 1.61→1.2»)."""
    lines = []
    for k, (a, b) in enumerate(zip(old, new)):
        if a == b:
            continue
        if isinstance(a, MagneticParams) and isinstance(b, MagneticParams):
            changes = [f"{f} {getattr(a, f)}→{getattr(b, f)}"
                       for f in asdict(b) if getattr(a, f) != getattr(b, f)]
            lines.append(f"тормоз {k + 1}: " + ", ".join(changes))
        elif isinstance(a, CurveBrakeParams) and isinstance(b, CurveBrakeParams):
            lines.append(f"тормоз {k + 1}: новая таблица F(v)")
        else:
            lines.append(f"тормоз {k + 1}: {KIND_LABELS[slot_kind(a)]} → {KIND_LABELS[slot_kind(b)]}")
    return lines


def curve_summary(slot: CurveBrakeParams) -> str:
    """Кратко о таблице F(v): число точек и диапазоны."""
    points = slot.points
    f_max = max(p.force for p in points)
    return (f"{len(points)} точек · v {points[0].velocity:g}…{points[-1].velocity:g} м/с · "
            f"F до {f_max:g} Н")


def active_models(config: Config) -> tuple[list[BrakeModel], list[int]]:
    """Включённые модели и их номера слотов (порядок слотов сохранён)."""
    models: list[BrakeModel] = []
    idx: list[int] = []
    for k, slot in enumerate(config):
        if slot is not None:
            models.append(slot)
            idx.append(k)
    return models, idx


# --- сериализация (JSON-совместимо, float'ы восстанавливаются бит-в-бит) ---

def slot_to_dict(slot: Slot) -> dict | None:
    if slot is None:
        return None
    if isinstance(slot, MagneticParams):
        return {"type": KIND_PARAMETRIC, "params": asdict(slot)}
    return {
        "type": KIND_CURVE,
        "points": [[float(p.velocity), float(p.force)] for p in slot.points],
    }


def slot_from_dict(data: dict | None) -> Slot:
    if data is None:
        return None
    kind = data.get("type")
    if kind == KIND_PARAMETRIC:
        return MagneticParams(**data["params"])
    if kind == KIND_CURVE:
        return CurveBrakeParams(points=tuple(
            ForceCurvePoint(velocity=float(v), force=float(f)) for v, f in data["points"]
        ))
    raise ValueError(f"Неизвестный тип слота: {kind!r}")


def config_to_list(config: Config) -> list[dict | None]:
    return [slot_to_dict(slot) for slot in config]


def config_from_list(data: list[dict | None]) -> Config:
    return tuple(slot_from_dict(item) for item in data)


def slot_from_brake_config(brake) -> BrakeModel:
    """Рабочая модель из сохранённого `MagneticBrakeConfig` (для старта с расчёта-донора)."""
    if brake.model_type == brake.MODEL_TYPE_CURVE:
        points = tuple(
            ForceCurvePoint(velocity=float(p.velocity), force=float(p.force))
            for p in brake.force_points.order_by("order", "id")
        )
        return CurveBrakeParams(points=points)
    return MagneticParams(
        gamma=brake.gamma, delta=brake.delta, xm=brake.xm, ym=brake.ym,
        dh1=brake.dh1, dh2=brake.dh2, dm=brake.dm, n=brake.n, mu=brake.mu,
        bz=brake.bz, lya=brake.lya, wn0=brake.wn0,
    )

"""Хранение итерационного расчёта между HTTP-запросами (модель `IterativeCalc`).

Каждое действие: загрузить сессию (state JSON + история .npz + привод) →
продвинуть → сохранить новую версию:
  - история пишется в НОВЫЙ файл `history_v{N+1}.npz`;
  - запись в БД условная (`version == N`) — оптимистичная блокировка: параллельное
    действие (двойной клик, вторая вкладка) не затрёт чужой результат, а получит
    `StaleCalcError`, и на диске останется согласованная версия N;
  - после успешной записи файл версии N удаляется.
Итог (`finish`) — обычный `CalculationRun` (`is_iterative=True`) через общий
`persist_result_and_snapshot`: графики, XLSX, snapshot (+ этапы в `BrakeStage`
и `snapshot["iterative"]`). Сам движок (`session.py`) о Django не знает —
этот модуль не импортируется из `services/iterative/__init__.py`.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from collections import OrderedDict
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from ...models import (
    BrakeForcePoint,
    BrakeStage,
    CalculationRun,
    IterativeCalc,
    MagneticBrakeConfig,
)
from ..dynamics import RecoilParams
from ..io_utils import load_recoil_characteristics
from ..magnetic import CurveBrakeParams, MagneticParams
from ..run_pipeline import persist_result_and_snapshot
from .config import Slot, config_to_list
from .overlay import build_stage_overlay
from .physics import MODE_FREE_FALL, MODE_RECOIL
from .session import AdvanceReport, IterativeOutcome, IterativeSession, Stage

T = TypeVar("T")

_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
_PARAM_FIELDS = ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")


class StaleCalcError(Exception):
    """Сессию изменили параллельно (другая вкладка/двойной клик) — перечитайте её."""


_STALE_MESSAGE = (
    "Итерационный расчёт изменён параллельно (другая вкладка или повторное нажатие) — "
    "обновите страницу."
)


# ------------------------------------------------------------------ привод (кэш)

_DRIVE_CACHE: OrderedDict[tuple[str, float], tuple] = OrderedDict()
_DRIVE_CACHE_SIZE = 8
_DRIVE_LOCK = threading.Lock()


def _load_drive(path: str):
    """Привод из Excel с кэшем по (путь, mtime): не перечитывать файл на каждый шаг."""
    key = (str(path), os.path.getmtime(path))
    with _DRIVE_LOCK:
        drive = _DRIVE_CACHE.get(key)
        if drive is not None:
            _DRIVE_CACHE.move_to_end(key)
            return drive
    drive = load_recoil_characteristics(path)
    with _DRIVE_LOCK:
        _DRIVE_CACHE[key] = drive
        while len(_DRIVE_CACHE) > _DRIVE_CACHE_SIZE:
            _DRIVE_CACHE.popitem(last=False)
    return drive


# ------------------------------------------------------------------- создание

def validate_name(name: str) -> str:
    """Имя будущего расчёта: латиница/цифры/-/_, свободно среди расчётов и сессий."""
    name = (name or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Название: только английские буквы, цифры, дефис и подчёркивание.")
    if CalculationRun.objects.filter(name=name).exists():
        raise ValueError("Расчёт с таким названием уже существует.")
    if IterativeCalc.objects.filter(name=name).exists():
        raise ValueError("Итерационный расчёт с таким названием уже существует.")
    return name


def create_calc(
    *,
    name: str,
    mode: str,
    recoil: RecoilParams,
    config: Iterable[Slot],
    owner=None,
    input_file=None,
    source_run: CalculationRun | None = None,
) -> IterativeCalc:
    """Создать сессию в начальном узле (t=0). `input_file` — File/UploadedFile (для отката)."""
    name = validate_name(name)
    if mode not in (MODE_RECOIL, MODE_FREE_FALL):
        raise ValueError(f"Неизвестный режим: {mode!r}")
    if mode == MODE_RECOIL and input_file is None:
        raise ValueError("Для расчёта отката нужен входной файл характеристик (F(t), F(x)).")

    calc = IterativeCalc.objects.create(
        name=name, owner=owner, mode=mode, source_run=source_run,
        mass=recoil.mass, angle_deg=recoil.angle_deg, v0=recoil.v0, x0=recoil.x0,
        t_max=recoil.t_max, dt=recoil.dt,
    )
    remove_calc_media(calc)    # на случай остатков от записи с тем же id (откат транзакции)
    try:
        drive = None
        if mode == MODE_RECOIL:
            calc.input_file.save(Path(input_file.name).name, input_file, save=True)
            drive = _load_drive(calc.input_file.path)
        session = IterativeSession(mode, recoil, list(config), drive)
        _save(calc, session)
    except Exception:
        calc.delete()          # post_delete-сигнал уберёт папку с файлами
        raise
    return calc


def input_file_from_run(run: CalculationRun) -> ContentFile:
    """Копия входного файла расчёта-донора (у сессии — своя копия)."""
    if not run.input_file:
        raise ValueError(f"У расчёта «{run.name}» нет входного файла.")
    run.input_file.open("rb")
    try:
        content = run.input_file.read()
    finally:
        run.input_file.close()
    return ContentFile(content, name=Path(run.input_file.name).name)


# ------------------------------------------------------------------ загрузка/сохранение

def load_session(calc: IterativeCalc) -> IterativeSession:
    if not calc.state or not calc.history_file:
        raise ValueError("Итерационный расчёт не инициализирован.")
    try:
        with np.load(calc.history_file.path) as data:
            history = {key: data[key] for key in data.files}
    except FileNotFoundError:
        # Файл нашей версии уже удалён параллельным действием, сохранившим следующую.
        current = IterativeCalc.objects.filter(pk=calc.pk).values_list("version", flat=True).first()
        if current is not None and current != calc.version:
            raise StaleCalcError(_STALE_MESSAGE) from None
        raise
    drive = _load_drive(calc.input_file.path) if calc.mode == MODE_RECOIL else None
    return IterativeSession.from_dict(calc.state, history, drive)


def _save(calc: IterativeCalc, session: IterativeSession, **fields) -> None:
    """Новая версия: файл истории v{N+1} + условная запись в БД (version == N)."""
    old_version = calc.version
    new_version = old_version + 1
    old_file = calc.history_file.name if calc.history_file else None

    rel_path = f"{calc.media_folder}/history_v{new_version}.npz"
    abs_path = Path(settings.MEDIA_ROOT) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(abs_path, "wb") as fh:
        np.savez(fh, **session.history_arrays())

    state = session.to_dict()
    now = timezone.now()
    updated = IterativeCalc.objects.filter(pk=calc.pk, version=old_version).update(
        version=new_version, state=state, history_file=rel_path, updated_at=now, **fields,
    )
    if not updated:
        abs_path.unlink(missing_ok=True)
        raise StaleCalcError(_STALE_MESSAGE)

    if old_file and old_file != rel_path:
        try:
            (Path(settings.MEDIA_ROOT) / old_file).unlink(missing_ok=True)
        except OSError:
            pass   # файл открыт параллельным запросом (Windows) — уберётся вместе с папкой сессии

    calc.version = new_version
    calc.state = state
    calc.history_file.name = rel_path
    calc.updated_at = now
    for key, value in fields.items():
        setattr(calc, key, value)


def _ensure_active(calc: IterativeCalc) -> None:
    if calc.is_finishing:
        raise ValueError("Идёт фоновый досчёт до конца — дождитесь итога.")
    if not calc.is_active:
        raise ValueError("Итерационный расчёт уже завершён.")


def perform(calc: IterativeCalc, action: Callable[[IterativeSession], T]) -> tuple[T, IterativeSession]:
    """Загрузить → действие над сессией → сохранить новую версию. Возвращает
    (результат действия, сессию после него) — странице не нужно перечитывать."""
    _ensure_active(calc)
    session = load_session(calc)
    outcome = action(session)
    _save(calc, session)
    return outcome, session


# ------------------------------------------------------------------ действия

def step(calc: IterativeCalc, n: int = 1) -> AdvanceReport:
    return perform(calc, lambda s: s.step(n))[0]


def advance_distance(calc: IterativeCalc, dx: float) -> AdvanceReport:
    return perform(calc, lambda s: s.advance_distance(dx))[0]


def reconfigure(calc: IterativeCalc, config: Iterable[Slot]) -> bool:
    return perform(calc, lambda s: s.reconfigure(list(config)))[0]


def run_to_end(calc: IterativeCalc) -> AdvanceReport:
    """Досчитать без сохранения итога (итог — `finish`, он же досчитывает сам)."""
    return perform(calc, lambda s: s.run_to_end())[0]


def undo_last_change(calc: IterativeCalc):
    """Отменить последнее изменение конфигурации (см. `IterativeSession.undo_last_change`)."""
    return perform(calc, lambda s: s.undo_last_change())[0]


# ------------------------------------------------------------------ клонирование

def suggest_clone_name(source: IterativeCalc) -> str:
    base = source.name
    for i in range(2, 1000):
        candidate = f"{base}_{i}"
        if not (IterativeCalc.objects.filter(name=candidate).exists()
                or CalculationRun.objects.filter(name=candidate).exists()):
            return candidate
    return f"{base}_copy"


def clone_calc(source: IterativeCalc, *, name: str, owner=None) -> IterativeCalc:
    """Копия сессии в её текущем состоянии (история, этапы, узел) под новым именем.

    Вместе с «Отменить последнее изменение» это правка любого этапа: клонировать →
    откатиться до нужного этапа → изменить → считать дальше. Клон остановленной
    сессии продолжает счёт с точки остановки. Оригинал не меняется.
    """
    name = validate_name(name)
    session = load_session(source)
    session.resume()

    calc = IterativeCalc.objects.create(
        name=name, owner=owner, mode=source.mode, source_run=source.source_run,
        mass=source.mass, angle_deg=source.angle_deg, v0=source.v0, x0=source.x0,
        t_max=source.t_max, dt=source.dt,
    )
    remove_calc_media(calc)
    try:
        if source.input_file:
            source.input_file.open("rb")
            try:
                content = source.input_file.read()
            finally:
                source.input_file.close()
            calc.input_file.save(Path(source.input_file.name).name, ContentFile(content), save=True)
        _save(calc, session)
    except Exception:
        calc.delete()
        raise
    return calc


# ------------------------------------------------------------------ завершение

# «Досчитать до конца» с большим остатком шагов — в фоновом потоке (у свободного
# падения — сотни тысяч шагов, десятки секунд: дольше разумного HTTP-запроса).
BACKGROUND_FINISH_STEPS = 20_000
STUCK_FINISHING_AFTER = timedelta(minutes=10)


def remaining_steps(session: IterativeSession) -> int:
    return 0 if session.finished else max(session.grid_steps_total - session.grid_index, 0)


def _validated_run_name(calc: IterativeCalc, name: str | None) -> str:
    run_name = (name or calc.name).strip()
    if not _NAME_RE.fullmatch(run_name):
        raise ValueError("Название: только английские буквы, цифры, дефис и подчёркивание.")
    if CalculationRun.objects.filter(name=run_name).exists():
        raise ValueError(f"Расчёт «{run_name}» уже существует — задайте другое имя.")
    return run_name


def finish(calc: IterativeCalc, *, stop_now: bool = False, name: str | None = None) -> CalculationRun:
    """Завершить и сохранить итог обычным `CalculationRun` (синхронно).

    stop_now=False — «Досчитать до конца» (конец наката / t_max);
    stop_now=True  — «Остановить и построить графики» по посчитанной части.
    `name` — имя расчёта, если имя сессии успели занять.
    """
    _ensure_active(calc)
    run_name = _validated_run_name(calc, name)
    return _finish_session(calc, load_session(calc), stop_now, run_name)


def finish_auto(calc: IterativeCalc, *, stop_now: bool = False,
                name: str | None = None) -> CalculationRun | None:
    """Как `finish`, но долгий досчёт уходит в фоновый поток: тогда возвращает None,
    статус сессии — `finishing`, страница опрашивает его и переходит к итогу."""
    _ensure_active(calc)
    run_name = _validated_run_name(calc, name)
    session = load_session(calc)
    if stop_now or remaining_steps(session) <= BACKGROUND_FINISH_STEPS:
        return _finish_session(calc, session, stop_now, run_name)

    now = timezone.now()
    updated = IterativeCalc.objects.filter(
        pk=calc.pk, version=calc.version, status=IterativeCalc.STATUS_ACTIVE,
    ).update(status=IterativeCalc.STATUS_FINISHING, error_text="", updated_at=now)
    if not updated:
        raise StaleCalcError(_STALE_MESSAGE)
    calc.status, calc.error_text, calc.updated_at = IterativeCalc.STATUS_FINISHING, "", now
    _spawn_worker(calc.pk, calc.version, run_name)
    return None


def _spawn_worker(calc_id: int, version: int, run_name: str) -> None:
    threading.Thread(target=_finish_worker, args=(calc_id, version, run_name), daemon=True).start()


def _finish_worker(calc_id: int, version: int, run_name: str, *, close_connection: bool = True) -> None:
    """Фоновый «Досчитать до конца». Ошибка — сессия возвращается в «идёт» с текстом
    ошибки (состояние не тронуто: итог пишется одной транзакцией в самом конце)."""
    from django.db import connection

    try:
        calc = IterativeCalc.objects.filter(pk=calc_id).first()
        if calc is None or calc.status != IterativeCalc.STATUS_FINISHING or calc.version != version:
            return
        _finish_session(calc, load_session(calc), False, run_name)
    except Exception as exc:  # noqa: BLE001
        IterativeCalc.objects.filter(pk=calc_id, status=IterativeCalc.STATUS_FINISHING).update(
            status=IterativeCalc.STATUS_ACTIVE, error_text=f"{type(exc).__name__}: {exc}",
            updated_at=timezone.now(),
        )
    finally:
        if close_connection:
            connection.close()


def reset_stuck_finishing(calc: IterativeCalc) -> bool:
    """Фоновый досчёт завис (перезапуск сервера посреди потока) — вернуть сессию в «идёт».

    Разрешено, только если досчёт идёт дольше `STUCK_FINISHING_AFTER`. Состояние
    сессии не пострадало: итог записывается лишь по завершении потока.
    """
    if calc.status != IterativeCalc.STATUS_FINISHING:
        return False
    if timezone.now() - calc.updated_at < STUCK_FINISHING_AFTER:
        return False
    updated = IterativeCalc.objects.filter(pk=calc.pk, status=IterativeCalc.STATUS_FINISHING).update(
        status=IterativeCalc.STATUS_ACTIVE,
        error_text="Фоновый досчёт был прерван (вероятно, перезапуск сервера) — запустите заново.",
        updated_at=timezone.now(),
    )
    return bool(updated)


def _finish_session(calc: IterativeCalc, session: IterativeSession, stop_now: bool,
                    run_name: str) -> CalculationRun:
    if not session.finished:
        if stop_now:
            session.stop()
        else:
            session.run_to_end()
    outcome = session.build_result()

    run = None
    try:
        with transaction.atomic():
            run = CalculationRun.objects.create(
                name=run_name, mode=calc.mode, owner=calc.owner, is_iterative=True,
                mass=calc.mass, angle_deg=calc.angle_deg, v0=calc.v0, x0=calc.x0,
                t_max=calc.t_max, dt=calc.dt,
            )
            if calc.input_file:
                calc.input_file.open("rb")
                try:
                    content = calc.input_file.read()
                finally:
                    calc.input_file.close()
                run.input_file.save(Path(calc.input_file.name).name, ContentFile(content), save=True)

            brake_objects = _create_slot_brakes(run, outcome.stages)
            _create_brake_stages(run, outcome.stages)
            persist_result_and_snapshot(
                run, brake_objects, outcome.result,
                input_extra={"iterative": _input_extra(calc, outcome)},
                result_extra={"iterative": _result_extra(outcome)},
                stage_overlay=build_stage_overlay(outcome),
            )
            _save(calc, session, status=IterativeCalc.STATUS_FINISHED, result_run=run)
    except Exception:
        if run is not None and run.pk is not None:
            _remove_run_media(run)
        raise
    return run


def delete_calc(calc: IterativeCalc) -> None:
    """Удалить сессию (файлы уберёт post_delete-сигнал). Итоговый расчёт остаётся."""
    calc.delete()


def remove_calc_media(calc: IterativeCalc) -> None:
    folder = Path(settings.MEDIA_ROOT) / f"iterative/calc_{calc.pk}"
    if calc.pk is not None and folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


# ------------------------------------------------------------------ итог → модели

def _create_slot_brakes(run: CalculationRun, stages: list[Stage]) -> list[MagneticBrakeConfig]:
    """«Физические» тормоза расчёта: по записи на слот (index = слот + 1).

    Параметры — первая включённая конфигурация слота (у исходно включённых —
    C₀). На них опираются тепло (prefill геометрии), 3D, копирование. Полные
    конфигурации по этапам — в `BrakeStage`.
    """
    n_slots = len(stages[0].config)
    objects: list[MagneticBrakeConfig] = []
    for k in range(n_slots):
        first_stage, model = next(
            ((s.index, s.config[k]) for s in stages if s.config[k] is not None), (None, None)
        )
        name = f"Тормоз {k + 1}"
        if first_stage is None:
            name += " (не включался)"
        elif first_stage > 0:
            name += f" (включён с этапа {first_stage})"

        brake = MagneticBrakeConfig(run=run, index=k + 1, name=name)
        if isinstance(model, CurveBrakeParams):
            brake.model_type = MagneticBrakeConfig.MODEL_TYPE_CURVE
            brake.save()
            BrakeForcePoint.objects.bulk_create([
                BrakeForcePoint(brake=brake, order=i + 1, velocity=p.velocity, force=p.force)
                for i, p in enumerate(model.points)
            ])
        else:
            brake.model_type = MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC
            if isinstance(model, MagneticParams):
                for field in _PARAM_FIELDS:
                    setattr(brake, field, getattr(model, field))
            brake.save()
        objects.append(brake)
    return objects


def _create_brake_stages(run: CalculationRun, stages: list[Stage]) -> None:
    BrakeStage.objects.bulk_create([
        BrakeStage(
            run=run, stage=s.index, config=config_to_list(s.config),
            x_switch=s.x, t_forward=s.t, v_forward=s.v,
            t_return=s.return_t, v_return=s.return_v,
        )
        for s in stages
    ])


def _input_extra(calc: IterativeCalc, outcome: IterativeOutcome) -> dict:
    return {
        "calc_id": calc.pk,
        "stages": [
            {
                "stage": s.index,
                "config": config_to_list(s.config),
                "x_switch": s.x, "t_forward": s.t, "v_forward": s.v,
                "t_return": s.return_t, "v_return": s.return_v,
                "row": s.row, "return_row": s.return_row,
            }
            for s in outcome.stages
        ],
    }


def _result_extra(outcome: IterativeOutcome) -> dict:
    return {
        "stage_index": [int(s) for s in outcome.stage_index],
        "switch_events": [asdict(e) for e in outcome.switch_events],
    }


def _remove_run_media(run: CalculationRun) -> None:
    """Откат неудачного finish: папка отчёта (графики/XLSX) и входной файл-копия."""
    safe_name = slugify(run.name) or f"run-{run.id}"
    folder = Path(settings.MEDIA_ROOT) / "reports" / f"{safe_name}_{run.id}"
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    if run.input_file and run.input_file.name:
        (Path(settings.MEDIA_ROOT) / run.input_file.name).unlink(missing_ok=True)

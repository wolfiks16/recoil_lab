"""Итерационный (пошаговый) расчёт с перестройкой тормозов по ходу движения.

Интегратор НЕ перезапускается: сессия хранит состояние (t, x, v, wn по
тормозам, фаза, активная конфигурация) и всю накопленную историю, а каждое
продвижение продолжает ровно с сохранённого узла теми же функциями, что и
обычный расчёт (`physics.py`). Поэтому пошаговый прогон без изменений
совпадает с `simulate_recoil_core` / `simulate_free_fall` бит-в-бит — при любой
нарезке на шаги и после сериализации/восстановления (`to_dict`/`from_dict`).

Этапы. Этап 0 — исходная конфигурация C₀. Изменение на откате в текущем узле
(координата x_k) открывает этап k с конфигурацией C_k. Конфигурация — функция
положения: на накате при прохождении x_k (сверху вниз) система сама
возвращается к C_{k−1}; шаг дробится так, чтобы узел лёг точно в x_k. Ручные
изменения на накате запрещены. В свободном падении наката нет — менять можно
на всём пути.

Узлы переключения. В точке смены конфигурации в истории ДВА узла с одинаковыми
(t, x, v): силы старой и новой конфигурации — честный скачок на графиках и
точный энергобаланс (интервал нулевой длины ничего не добавляет).

Сетка времени. Регулярные узлы — `np.arange(0, t_max + dt, dt)`, как в обычном
расчёте. Узел события (точка «до Δx», обратное переключение) вставляется
внутрь интервала; следующий шаг дошагивает остаток до регулярного узла.
Как и в обычном расчёте (узел x=0 конца наката), узел события продвигает wn
один раз.

wn при переключении (согласовано с пользователем): слот, чья модель
изменилась, стартует с начального состояния НОВОЙ модели (wn0 у
параметрического; у табличного состояния нет); неизменённые слоты продолжают
со своего wn. На скоростях отката это не влияет на результат (коэффициент
памяти A=(ex·ed)² ≈ 0); при A > 1% выдаётся предупреждение.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Iterable

import numpy as np

from ..dynamics import (
    RecoilParams,
    SimulationResult,
    _advance_brake_states,
    compute_energy_balance,
)
from ..magnetic import MagneticParams, wn_memory_coefficient
from .config import (
    Config,
    Slot,
    active_models,
    config_from_list,
    config_to_list,
    initial_slot_state,
    normalize_config,
    slot_changed,
)
from .physics import MODE_FREE_FALL, MODE_RECOIL, make_physics

STATE_VERSION = 1

PHASE_RECOIL = "recoil"
PHASE_RETURN = "return"
PHASE_FALL = "fall"

# Почему остановилось продвижение.
STOP_STEPS = "steps"            # сделано запрошенное число шагов
STOP_TARGET = "target"          # узел поставлен точно в точку «через Δx»
STOP_TURNAROUND = "turnaround"  # разворот раньше, чем достигнута точка
STOP_FINISHED = "finished"      # расчёт завершён (конец наката / t_max / остановлен)

DIRECTION_FORWARD = "forward"
DIRECTION_RETURN = "return"

TERMINATION_STOPPED = "stopped_by_user"
TERMINATION_IN_PROGRESS = "in_progress"

WN_MEMORY_WARN = 0.01

_LAND_TOL = 1e-12       # точность посадки узла на координату события, м (отн. к max(1, |x|))
_LAND_MAX_ITER = 60

_SCALARS = ("t", "x", "v", "a", "f_total", "f_ext", "f_spring", "f_magnetic", "f_angle")


@dataclass
class Stage:
    """Этап — интервал действия одной конфигурации."""

    index: int
    config: Config
    x: float | None = None          # точка включения на откате (у этапа 0 — None)
    t: float | None = None
    v: float | None = None
    row: int | None = None          # строка истории, с которой этап действует
    return_t: float | None = None   # момент снятия этапа на накате (возврат к k−1)
    return_v: float | None = None
    return_row: int | None = None
    # Состояние интегратора в узле до переключения — для «Отменить последнее изменение»
    # (строка истории, индекс сетки, число тормозов, флаги, длины списков событий).
    checkpoint: dict | None = None


@dataclass(frozen=True)
class SwitchEvent:
    direction: str      # DIRECTION_FORWARD | DIRECTION_RETURN
    stage_from: int
    stage_to: int
    t: float
    x: float
    v: float
    row: int            # строка истории с силами НОВОЙ конфигурации


@dataclass
class AdvanceReport:
    reason: str
    grid_steps: int
    switches: list[SwitchEvent] = field(default_factory=list)
    turned: bool = False            # разворот произошёл за это продвижение


@dataclass
class IterativeOutcome:
    result: SimulationResult
    stage_index: np.ndarray         # номер этапа в каждой строке истории
    stages: list[Stage]
    switch_events: list[SwitchEvent]


class _History:
    """Накопленная история узлов в numpy-массивах с запасом ёмкости.

    float64 хранит значения точно (как и списки float). Массивы нужны, чтобы
    сохранение/загрузка сессии между HTTP-запросами были копированием памяти,
    а не поэлементным перебором: у свободного падения — сотни тысяч узлов.
    """

    _MIN_CAPACITY = 1024

    def __init__(self, n_slots: int, capacity: int = _MIN_CAPACITY):
        self._n = 0
        self._cols = {k: np.zeros(capacity, dtype=float) for k in _SCALARS}
        self._f_each = np.zeros((capacity, n_slots), dtype=float)
        self._wn = np.zeros((capacity, n_slots), dtype=float)
        self._stage = np.zeros(capacity, dtype=np.int64)

    def __len__(self) -> int:
        return self._n

    def _reserve(self, size: int) -> None:
        capacity = len(self._stage)
        if size <= capacity:
            return
        new_capacity = max(size, 2 * capacity)
        extra = new_capacity - capacity
        for k in _SCALARS:
            self._cols[k] = np.concatenate([self._cols[k], np.zeros(extra)])
        self._f_each = np.vstack([self._f_each, np.zeros((extra, self._f_each.shape[1]))])
        self._wn = np.vstack([self._wn, np.zeros((extra, self._wn.shape[1]))])
        self._stage = np.concatenate([self._stage, np.zeros(extra, dtype=np.int64)])

    def grow_slots(self, n_slots: int) -> None:
        """Новые тормоза: в прошлых строках их силы и состояния — нули."""
        extra = n_slots - self._f_each.shape[1]
        if extra > 0:
            self._f_each = np.hstack([self._f_each, np.zeros((len(self._stage), extra))])
            self._wn = np.hstack([self._wn, np.zeros((len(self._stage), extra))])

    def append(self, row: dict) -> None:
        self._reserve(self._n + 1)
        i = self._n
        for k in _SCALARS:
            self._cols[k][i] = row[k]
        self._f_each[i, :] = row["f_each"]
        self._wn[i, :] = row["wn"]
        self._stage[i] = row["stage"]
        self._n += 1

    def pop(self) -> None:
        self._n -= 1

    def truncate(self, n: int) -> None:
        """Оставить первые n строк (отмена изменения — всё после узла отбрасывается)."""
        self._n = min(self._n, n)

    def shrink_slots(self, n_slots: int) -> None:
        """Убрать тормоза, добавленные отменённым изменением (колонки сверх n_slots)."""
        self._f_each = self._f_each[:, :n_slots].copy()
        self._wn = self._wn[:, :n_slots].copy()

    def last(self) -> dict:
        i = self._n - 1
        row = {k: float(self._cols[k][i]) for k in _SCALARS}
        row.update(
            f_each=[float(f) for f in self._f_each[i]],
            wn=[float(s) for s in self._wn[i]],
            stage=int(self._stage[i]),
        )
        return row

    def arrays(self) -> dict[str, np.ndarray]:
        n = self._n
        out = {k: self._cols[k][:n].copy() for k in _SCALARS}
        out["f_each"] = self._f_each[:n].copy()
        out["wn"] = self._wn[:n].copy()
        out["stage"] = self._stage[:n].copy()
        return out

    @classmethod
    def from_arrays(cls, arrays: dict) -> "_History":
        stage = np.asarray(arrays["stage"], dtype=np.int64)
        f_each = np.asarray(arrays["f_each"], dtype=float)
        n = len(stage)
        hist = cls(f_each.shape[1], capacity=max(cls._MIN_CAPACITY, n + cls._MIN_CAPACITY))
        for k in _SCALARS:
            hist._cols[k][:n] = np.asarray(arrays[k], dtype=float)
        hist._f_each[:n] = f_each
        hist._wn[:n] = np.asarray(arrays["wn"], dtype=float)
        hist._stage[:n] = stage
        hist._n = n
        return hist


def _crosses(x_from: float, x_to: float, x_mark: float) -> bool:
    """Отрезок движения [x_from → x_to] проходит через x_mark (x_from ≠ x_mark)."""
    return x_from != x_mark and (x_from - x_mark) * (x_to - x_mark) <= 0.0


class IterativeSession:
    """Пошаговый расчёт с перестройкой тормозов. См. docstring модуля."""

    def __init__(
        self,
        mode: str,
        recoil: RecoilParams,
        initial_config: Iterable[Slot],
        drive=None,
    ):
        self.mode = mode
        self.recoil = recoil
        self._physics = make_physics(mode, recoil, drive)
        self._grid = np.arange(0.0, recoil.t_max + recoil.dt, recoil.dt)

        config = normalize_config(initial_config)
        self.stages: list[Stage] = [Stage(index=0, config=config, row=0)]
        self.active_stage = 0
        self.switch_events: list[SwitchEvent] = []
        self.extra_warnings: list[str] = []

        self._j = 0                 # индекс последнего пройденного регулярного узла
        self._on_grid = True        # текущий узел регулярный (иначе — узел события)
        self.t = float(self._grid[0])
        self.x = float(recoil.x0)
        self.v = float(recoil.v0)
        self.wn = [initial_slot_state(slot) for slot in config]

        self.turned = False
        self.recoil_end_time: float | None = None
        self.recoil_end_index: int | None = None
        self.return_end_time: float | None = None
        self.return_end_index: int | None = None
        self.finished = False
        self.termination_reason: str | None = None
        self.spring_out_of_range = False
        self.substep_limit_hit = False

        self._history = _History(len(config))
        self._history.append(self._row(self.t, self.x, self.v, self.wn, 0))
        if len(self._grid) < 2:
            self._finish_at_grid_end()

    # ------------------------------------------------------------------ свойства

    @property
    def n_slots(self) -> int:
        return len(self.stages[0].config)

    @property
    def config(self) -> Config:
        return self.stages[self.active_stage].config

    @property
    def phase(self) -> str:
        if not self._physics.has_return:
            return PHASE_FALL
        return PHASE_RETURN if self.turned else PHASE_RECOIL

    @property
    def can_reconfigure(self) -> bool:
        return not self.finished and not (self._physics.has_return and self.turned)

    @property
    def row_count(self) -> int:
        return len(self._history)

    @property
    def grid_index(self) -> int:
        return self._j

    @property
    def grid_steps_total(self) -> int:
        """Число шагов сетки до t_max (для «шаг j из N»)."""
        return len(self._grid) - 1

    def current(self) -> dict:
        """Состояние в текущем узле (для экрана остановки)."""
        row = self._history.last()
        row.update(
            row=len(self._history) - 1,
            grid_index=self._j,
            on_grid=self._on_grid,
            phase=self.phase,
            finished=self.finished,
            termination_reason=self.termination_reason,
        )
        return row

    # ------------------------------------------------------------ продвижение

    def step(self, n: int = 1) -> AdvanceReport:
        """Ровно `n` шагов интегрирования (до n-го следующего регулярного узла)."""
        if n < 1:
            raise ValueError("Число шагов должно быть ≥ 1.")
        mark = self._mark()
        done = 0
        while done < n and not self.finished:
            self._grid_step()
            done += 1
        return self._report(STOP_FINISHED if self.finished else STOP_STEPS, done, mark)

    def advance_distance(self, dx: float) -> AdvanceReport:
        """Пройти путь `dx` по ходу движения; узел ставится точно в конечную точку.

        На откате (и в свободном падении) — вперёд; на накате — к x=0. Если на
        откате разворот наступил раньше — останавливаемся на развороте
        (STOP_TURNAROUND): точка не достигнута.
        """
        if not dx > 0.0:
            raise ValueError("Путь Δx должен быть > 0.")
        mark = self._mark()
        if self.finished:
            return self._report(STOP_FINISHED, 0, mark)

        backward = self._physics.has_return and self.turned
        target = self.x - dx if backward else self.x + dx
        if backward and target <= 0.0:
            target = None   # точка за концом наката — просто досчитываем

        turned_before = self.turned
        steps = 0
        while not self.finished:
            self._pending_reverse_switches()
            kind = self._segment(x_target=target)
            if kind is None:
                steps += 1
            if kind == "target":
                return self._report(STOP_TARGET, steps, mark)
            if target is not None and not turned_before and self.turned:
                return self._report(STOP_TURNAROUND, steps, mark)
        return self._report(STOP_FINISHED, steps, mark)

    def run_to_end(self) -> AdvanceReport:
        """Досчитать до конца (конец наката / t_max) без ручных изменений."""
        mark = self._mark()
        steps = 0
        while not self.finished:
            self._grid_step()
            steps += 1
        return self._report(STOP_FINISHED, steps, mark)

    def stop(self) -> None:
        """Остановить расчёт в текущем узле (результат — по посчитанной части)."""
        if not self.finished:
            self._finish(TERMINATION_STOPPED)

    # ---------------------------------------------------- изменение конфигурации

    def reconfigure(self, new_config: Iterable[Slot]) -> bool:
        """Сменить конфигурацию в текущем узле. Возвращает False, если ничего не изменилось.

        `new_config` — ПОЛНЫЙ список слотов (можно длиннее — это добавление
        тормозов; короче нельзя — тормоз не удаляют, а отключают `None`).
        Повторное изменение в том же узле правит последний этап, а не плодит
        этапы; возврат к прежней конфигурации в том же узле отменяет этап.
        """
        if self.finished:
            raise ValueError("Расчёт уже завершён — конфигурацию менять нельзя.")
        if self._physics.has_return and self.turned:
            raise ValueError(
                "На накате конфигурацию менять нельзя: переключения идут автоматически "
                "в обратном порядке в точках, записанных на откате."
            )
        slots = tuple(new_config)
        if len(slots) < self.n_slots:
            raise ValueError(
                "Нельзя удалить тормоз из конфигурации — отключите его (слот = None)."
            )

        # Повторное изменение в том же узле: сначала снимаем последний этап
        # (как будто его не было), потом применяем новую конфигурацию к прежней.
        undone = False
        last = self.stages[-1]
        if self.active_stage > 0 and last.row == len(self._history) - 1:
            if last.checkpoint is not None:
                self.undo_last_change()
            else:
                self._undo_forward_switch_at_current_node()   # этап из старой версии состояния
            undone = True

        new_cfg = normalize_config(slots, self.n_slots)
        if new_cfg == normalize_config(self.config, len(new_cfg)):
            return undone    # вернули как было — этап отменён (или ничего не менялось)

        # Ещё не шагали — это правка исходной конфигурации C₀.
        if len(self._history) == 1:
            if len(new_cfg) > self.n_slots:
                self._grow_slots(len(new_cfg))
            self.stages[0].config = new_cfg
            self.wn = [initial_slot_state(slot) for slot in new_cfg]
            row = self._row(self.t, self.x, self.v, self.wn, 0)
            self._history.pop()
            self._history.append(row)
            return True

        checkpoint = self._checkpoint()
        if len(new_cfg) > self.n_slots:
            self._grow_slots(len(new_cfg))

        index = len(self.stages)
        self.stages.append(Stage(index=index, config=new_cfg, x=self.x, t=self.t, v=self.v,
                                 checkpoint=checkpoint))
        try:
            self._switch_to(index, DIRECTION_FORWARD)
        except Exception:
            self.stages.pop()
            if self.n_slots > checkpoint["n_slots"]:
                self._shrink_slots(checkpoint["n_slots"])
            raise
        self.stages[index].row = len(self._history) - 1
        return True

    @property
    def can_undo(self) -> bool:
        """Есть изменение конфигурации, которое можно отменить (со снимком состояния)."""
        return len(self.stages) > 1 and self.stages[-1].checkpoint is not None

    def undo_last_change(self) -> Stage:
        """Отменить последнее изменение конфигурации: вернуться в узел, где оно сделано,
        с прежней конфигурацией; всё посчитанное после него отбрасывается.

        Состояние восстанавливается из снимка точно (t, x, v, wn из строки истории,
        индекс сетки, флаги), поэтому дальнейший расчёт идёт так, будто изменения
        не было. Возвращает снятый этап.
        """
        if len(self.stages) < 2:
            raise ValueError("Изменений конфигурации не было — отменять нечего.")
        stage = self.stages[-1]
        cp = stage.checkpoint
        if cp is None:
            raise ValueError("Это изменение сделано в старой версии расчёта — отменить его нельзя.")

        self.stages.pop()
        self._history.truncate(cp["row"] + 1)
        row = self._history.last()
        self.t, self.x, self.v = row["t"], row["x"], row["v"]
        self.wn = row["wn"]
        self._j, self._on_grid = cp["j"], cp["on_grid"]
        self.active_stage = len(self.stages) - 1

        # Изменения делаются только до разворота, поэтому в узле снимка разворота/конца ещё нет.
        self.turned = False
        self.recoil_end_time = self.recoil_end_index = None
        self.return_end_time = self.return_end_index = None
        self.finished = False
        self.termination_reason = None
        self.spring_out_of_range = cp["spring_out_of_range"]
        self.substep_limit_hit = cp["substep_limit_hit"]
        del self.extra_warnings[cp["n_warnings"]:]
        del self.switch_events[cp["n_events"]:]
        for remaining in self.stages:   # снятия на накате, случившиеся после узла, — тоже отменены
            if remaining.return_row is not None and remaining.return_row > cp["row"]:
                remaining.return_t = remaining.return_v = remaining.return_row = None
        if self.n_slots > cp["n_slots"]:
            self._shrink_slots(cp["n_slots"])
        return stage

    def resume(self) -> bool:
        """Продолжить остановленный пользователем расчёт (для клона остановленной сессии)."""
        if self.termination_reason != TERMINATION_STOPPED:
            return False
        self.finished = False
        self.termination_reason = None
        return True

    # ---------------------------------------------------------------- результат

    def build_result(self) -> IterativeOutcome:
        """Собрать `SimulationResult` из истории (можно и до завершения — превью)."""
        arr = self._history.arrays()

        warnings: list[str] = []
        if self.spring_out_of_range:
            x_min_tab, x_max_tab = self._physics.x_range
            warnings.append(
                f"В ходе расчёта перемещение вышло за диапазон табличной характеристики пружины: "
                f"[{x_min_tab:.6f}, {x_max_tab:.6f}] м."
            )
        if self.substep_limit_hit:
            warnings.append(
                "Численная жёсткость: достигнут предел дробления шага интегрирования. "
                "Результат может быть слегка неточным при очень малой массе — "
                "уменьшите dt для повышения точности."
            )
        warnings.extend(self.extra_warnings)

        result = SimulationResult(
            t=arr["t"],
            x=arr["x"],
            v=arr["v"],
            a=arr["a"],
            f_total=arr["f_total"],
            f_ext=arr["f_ext"],
            f_spring=arr["f_spring"],
            f_magnetic=arr["f_magnetic"],
            f_angle=arr["f_angle"],
            f_magnetic_each=arr["f_each"],
            wn_each=arr["wn"],
            recoil_end_time=self.recoil_end_time,
            recoil_end_index=self.recoil_end_index,
            return_end_time=self.return_end_time,
            return_end_index=self.return_end_index,
            termination_reason=self.termination_reason or TERMINATION_IN_PROGRESS,
            spring_out_of_range=self.spring_out_of_range,
            warnings=warnings,
        )
        compute_energy_balance(result, mass=self.recoil.mass)

        return IterativeOutcome(
            result=result,
            stage_index=arr["stage"],
            stages=copy.deepcopy(self.stages),
            switch_events=list(self.switch_events),
        )

    # ------------------------------------------------------------ сериализация

    def to_dict(self) -> dict:
        """Состояние сессии без истории (JSON-совместимо; float'ы — точно)."""
        return {
            "version": STATE_VERSION,
            "mode": self.mode,
            "recoil": asdict(self.recoil),
            "stages": [
                {
                    "index": s.index,
                    "config": config_to_list(s.config),
                    "x": s.x, "t": s.t, "v": s.v, "row": s.row,
                    "return_t": s.return_t, "return_v": s.return_v, "return_row": s.return_row,
                    "checkpoint": s.checkpoint,
                }
                for s in self.stages
            ],
            "active_stage": self.active_stage,
            "switch_events": [asdict(e) for e in self.switch_events],
            "extra_warnings": list(self.extra_warnings),
            "state": {
                "j": self._j,
                "on_grid": self._on_grid,
                "t": self.t,
                "x": self.x,
                "v": self.v,
                "wn": list(self.wn),
                "turned": self.turned,
                "recoil_end_time": self.recoil_end_time,
                "recoil_end_index": self.recoil_end_index,
                "return_end_time": self.return_end_time,
                "return_end_index": self.return_end_index,
                "finished": self.finished,
                "termination_reason": self.termination_reason,
                "spring_out_of_range": self.spring_out_of_range,
                "substep_limit_hit": self.substep_limit_hit,
            },
        }

    def history_arrays(self) -> dict[str, np.ndarray]:
        """История в виде массивов (для `np.savez`)."""
        return self._history.arrays()

    @classmethod
    def from_dict(cls, data: dict, history: dict, drive=None) -> "IterativeSession":
        if data.get("version") != STATE_VERSION:
            raise ValueError(f"Неподдерживаемая версия состояния: {data.get('version')!r}")

        obj = cls.__new__(cls)
        obj.mode = data["mode"]
        obj.recoil = RecoilParams(**data["recoil"])
        obj._physics = make_physics(obj.mode, obj.recoil, drive)
        obj._grid = np.arange(0.0, obj.recoil.t_max + obj.recoil.dt, obj.recoil.dt)

        obj.stages = [
            Stage(
                index=s["index"], config=config_from_list(s["config"]),
                x=s["x"], t=s["t"], v=s["v"], row=s["row"],
                return_t=s["return_t"], return_v=s["return_v"], return_row=s["return_row"],
                checkpoint=s.get("checkpoint"),   # у состояний до Среза 5 снимков нет
            )
            for s in data["stages"]
        ]
        obj.active_stage = data["active_stage"]
        obj.switch_events = [SwitchEvent(**e) for e in data["switch_events"]]
        obj.extra_warnings = list(data["extra_warnings"])

        st = data["state"]
        obj._j = st["j"]
        obj._on_grid = st["on_grid"]
        obj.t, obj.x, obj.v = st["t"], st["x"], st["v"]
        obj.wn = list(st["wn"])
        obj.turned = st["turned"]
        obj.recoil_end_time = st["recoil_end_time"]
        obj.recoil_end_index = st["recoil_end_index"]
        obj.return_end_time = st["return_end_time"]
        obj.return_end_index = st["return_end_index"]
        obj.finished = st["finished"]
        obj.termination_reason = st["termination_reason"]
        obj.spring_out_of_range = st["spring_out_of_range"]
        obj.substep_limit_hit = st["substep_limit_hit"]

        obj._history = _History.from_arrays(history)
        return obj

    # ========================================================= внутренняя часть

    def _row(self, t: float, x: float, v: float, wn: list[float], stage_idx: int) -> dict:
        """Силы в узле для конфигурации этапа (не меняет состояние сессии)."""
        config = self.stages[stage_idx].config
        models, idx = active_models(config)
        states = np.array([wn[k] for k in idx], dtype=float)
        try:
            fext, fa, fspring, fmag_active, ftotal = self._physics.forces(t, x, v, models, states)
        except ValueError as exc:
            raise ValueError(f"Этап {stage_idx}: {exc}") from exc

        f_each = [0.0] * len(config)
        for k, force in zip(idx, fmag_active):
            f_each[k] = float(force)
        return {
            "t": float(t),
            "x": float(x),
            "v": float(v),
            "a": float(ftotal / self.recoil.mass),
            "f_total": float(ftotal),
            "f_ext": float(fext),
            "f_spring": float(fspring),
            "f_magnetic": float(np.sum(fmag_active)),
            "f_angle": float(fa),
            "f_each": f_each,
            "wn": [float(s) for s in wn],
            "stage": stage_idx,
        }

    def _grid_step(self) -> None:
        """До следующего регулярного узла (события внутри интервала обрабатываются)."""
        while not self.finished:
            self._pending_reverse_switches()
            if self._segment() is None:
                return

    def _segment(self, x_target: float | None = None) -> str | None:
        """Один интервал от текущего узла к следующему регулярному узлу — или к событию.

        Возвращает None (дошли до регулярного узла / конец), "target" (узел в
        x_target) или "switch" (обратное переключение на накате выполнено).
        Порядок проверок повторяет `simulate_recoil_core`.
        """
        if not self._on_grid and float(self._grid[self._j + 1]) - self.t <= 1e-9 * self.recoil.dt:
            # Узел события совпал с регулярным узлом — считаем его регулярным.
            self._j += 1
            self._on_grid = True
            if self._j >= len(self._grid) - 1:
                self._finish_at_grid_end()
                return None

        models, idx = active_models(self.config)
        states = np.array([self.wn[k] for k in idx], dtype=float)
        if self._physics.spring_out_of_range(self.x):
            self.spring_out_of_range = True

        h = self.recoil.dt if self._on_grid else float(self._grid[self._j + 1]) - self.t
        try:
            x_new, v_new, n_sub = self._physics.step(self.t, self.x, self.v, h, models, states)
            kind = None
            event = self._pick_event(x_new, x_target)
            if event is not None:
                kind, x_event = event
                h, x_new, v_new, n_sub = self._land(x_event, h, x_new, v_new, n_sub, models, states)
            states_new = _advance_brake_states(v_new, models, states)
        except ValueError as exc:
            raise ValueError(f"Этап {self.active_stage}: {exc}") from exc

        t_new = self.t + h if kind is not None else float(self._grid[self._j + 1])

        # Разворот (v=0) — линейная интерполяция, как в simulate_recoil_core.
        turned_now = False
        recoil_end_time = None
        if self._physics.has_return and not self.turned and self.v > 0.0 and v_new <= 0.0:
            alpha_v = self.v / (self.v - v_new) if self.v != v_new else 0.0
            recoil_end_time = self.t + alpha_v * h
            turned_now = True

        # Конец наката (x=0) — узел ставится интерполяцией, как в simulate_recoil_core.
        returned = False
        if (
            self._physics.has_return and kind is None and (self.turned or turned_now)
            and self.x > 0.0 and x_new <= 0.0
        ):
            alpha_x = self.x / (self.x - x_new) if self.x != x_new else 0.0
            t_new = self.t + alpha_x * h
            v_new = self.v + alpha_x * (v_new - self.v)
            x_new = 0.0
            states_new = _advance_brake_states(v_new, models, states)
            returned = True

        wn_new = list(self.wn)
        for k, s in zip(idx, states_new):
            wn_new[k] = float(s)
        row = self._row(t_new, x_new, v_new, wn_new, self.active_stage)

        # --- фиксация (всё посчитано — ошибок дальше нет) ---
        if turned_now:
            self.turned = True
            self.recoil_end_time = recoil_end_time
            self.recoil_end_index = len(self._history) - 1
        if n_sub >= getattr(self._physics, "max_substeps", float("inf")):
            self.substep_limit_hit = True
        self.t, self.x, self.v = float(t_new), float(x_new), float(v_new)
        self.wn = wn_new
        if kind is None and not returned:
            self._j += 1
            self._on_grid = True
        elif kind is not None:
            self._on_grid = False
        self._history.append(row)

        if returned:
            self.return_end_time = self.t
            self.return_end_index = len(self._history) - 1
            self._finish("returned_to_zero")
        elif kind is None and self._j >= len(self._grid) - 1:
            self._finish_at_grid_end()
        elif kind == "switch":
            self._reverse_switch()
        return kind

    def _pick_event(self, x_new: float, x_target: float | None):
        """Ближайшее по ходу событие внутри шага: обратное переключение или цель Δx."""
        candidates = []
        if self._physics.has_return and self.turned and self.active_stage > 0:
            x_switch = self.stages[self.active_stage].x
            if self.x > x_switch >= x_new:
                candidates.append(("switch", x_switch))
        if x_target is not None and _crosses(self.x, x_new, x_target):
            candidates.append(("target", x_target))
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c[1] - self.x))

    def _land(self, x_event, h, x_end, v_end, n_end, models, states):
        """Подобрать долю шага h* ∈ (0, h], при которой узел ложится в x_event.

        Иллинойсский вариант regula falsi по реальному шагу интегратора
        (не по интерполяции) — посадка с точностью ~1e-12 м.
        """
        f_a = self.x - x_event
        f_b = x_end - x_event
        if f_b == 0.0:
            return h, x_end, v_end, n_end

        a, b = 0.0, h
        tol = _LAND_TOL * max(1.0, abs(x_event))
        best = (h, x_end, v_end, n_end)
        side = 0
        for _ in range(_LAND_MAX_ITER):
            c = (a * f_b - b * f_a) / (f_b - f_a)
            if not a < c < b:
                c = 0.5 * (a + b)
            x_c, v_c, n_c = self._physics.step(self.t, self.x, self.v, c, models, states)
            f_c = x_c - x_event
            best = (c, x_c, v_c, n_c)
            if abs(f_c) <= tol or (b - a) <= 1e-15 * h:
                break
            if (f_c > 0.0) == (f_b > 0.0):
                b, f_b = c, f_c
                if side == -1:
                    f_a *= 0.5
                side = -1
            else:
                a, f_a = c, f_c
                if side == +1:
                    f_b *= 0.5
                side = +1
        return best

    def _pending_reverse_switches(self) -> None:
        """На накате ниже точки переключения активного этапа — снять этап в текущем узле.

        Обычно снятие происходит посадкой узла в x_k внутри шага. Здесь —
        крайний случай: переключились у самого разворота, и тело оказалось ниже
        x_k, не пересекая её «сверху вниз».
        """
        while (
            not self.finished and self._physics.has_return and self.turned
            and self.active_stage > 0 and self.x <= self.stages[self.active_stage].x
        ):
            self._reverse_switch()

    def _reverse_switch(self) -> None:
        stage = self.stages[self.active_stage]
        self._switch_to(self.active_stage - 1, DIRECTION_RETURN)
        stage.return_t, stage.return_v = self.t, self.v
        stage.return_row = len(self._history) - 1

    def _switch_to(self, new_index: int, direction: str) -> None:
        """Сменить активный этап в текущем узле: правило wn + узел-дубль с новыми силами."""
        old_cfg = self.config
        new_cfg = self.stages[new_index].config
        wn_new = list(self.wn)
        for k, (old, new) in enumerate(zip(old_cfg, new_cfg)):
            if slot_changed(old, new):
                wn_new[k] = initial_slot_state(new)
        row = self._row(self.t, self.x, self.v, wn_new, new_index)

        stage_from = self.active_stage
        self.active_stage = new_index
        self.wn = wn_new
        self._history.append(row)
        self.switch_events.append(SwitchEvent(
            direction=direction, stage_from=stage_from, stage_to=new_index,
            t=self.t, x=self.x, v=self.v, row=len(self._history) - 1,
        ))
        self._warn_wn_memory(old_cfg, new_cfg)

    def _undo_forward_switch_at_current_node(self) -> None:
        """Отменить последний этап, открытый в текущем узле (узел-дубль убирается)."""
        stage = self.stages.pop()
        self._history.pop()
        self.wn = self._history.last()["wn"]
        self.active_stage = len(self.stages) - 1
        if self.switch_events and self.switch_events[-1].stage_to == stage.index:
            self.switch_events.pop()

    def _checkpoint(self) -> dict:
        """Снимок состояния в текущем узле — до переключения (для отмены изменения)."""
        return {
            "row": len(self._history) - 1,
            "j": self._j,
            "on_grid": self._on_grid,
            "n_slots": self.n_slots,
            "spring_out_of_range": self.spring_out_of_range,
            "substep_limit_hit": self.substep_limit_hit,
            "n_warnings": len(self.extra_warnings),
            "n_events": len(self.switch_events),
        }

    def _shrink_slots(self, n_slots: int) -> None:
        """Обратное к `_grow_slots` — при отмене изменения, добавившего тормоза."""
        for stage in self.stages:
            stage.config = tuple(stage.config[:n_slots])
        self.wn = self.wn[:n_slots]
        self._history.shrink_slots(n_slots)

    def _grow_slots(self, n_slots: int) -> None:
        """Добавление тормозов: на всех этапах (прошлых тоже) новые слоты отключены."""
        for stage in self.stages:
            stage.config = normalize_config(stage.config, n_slots)
        self.wn.extend([0.0] * (n_slots - len(self.wn)))
        self._history.grow_slots(n_slots)

    def _warn_wn_memory(self, old_cfg: Config, new_cfg: Config) -> None:
        for k, (old, new) in enumerate(zip(old_cfg, new_cfg)):
            if isinstance(new, MagneticParams) and slot_changed(old, new):
                memory = wn_memory_coefficient(self.v, new)
                if memory > WN_MEMORY_WARN:
                    self.extra_warnings.append(
                        f"Тормоз {k + 1}, переключение при x={self.x:.4f} м (t={self.t:.5f} с): "
                        f"коэффициент памяти wn A={memory:.3f} > {WN_MEMORY_WARN:.0%} — "
                        f"начальное wn0={new.wn0} заметно влияет на силу в первых шагах "
                        f"после переключения."
                    )

    def _finish(self, reason: str) -> None:
        self.finished = True
        self.termination_reason = reason

    def _finish_at_grid_end(self) -> None:
        if self.mode == MODE_FREE_FALL:
            self._finish("free_fall")
        elif np.isclose(self.t, self.recoil.t_max) or self.t >= self.recoil.t_max:
            self._finish("time_limit")
        else:
            self._finish("not_finished")

    def _mark(self) -> tuple[int, bool]:
        return len(self.switch_events), self.turned

    def _report(self, reason: str, steps: int, mark: tuple[int, bool]) -> AdvanceReport:
        n_events, turned_before = mark
        return AdvanceReport(
            reason=reason,
            grid_steps=steps,
            switches=self.switch_events[n_events:],
            turned=self.turned and not turned_before,
        )


__all__ = [
    "AdvanceReport",
    "DIRECTION_FORWARD",
    "DIRECTION_RETURN",
    "IterativeOutcome",
    "IterativeSession",
    "MODE_FREE_FALL",
    "MODE_RECOIL",
    "PHASE_FALL",
    "PHASE_RECOIL",
    "PHASE_RETURN",
    "STOP_FINISHED",
    "STOP_STEPS",
    "STOP_TARGET",
    "STOP_TURNAROUND",
    "Stage",
    "SwitchEvent",
    "TERMINATION_STOPPED",
]

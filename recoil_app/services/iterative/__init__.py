"""Итерационный (пошаговый) расчёт с перестройкой тормозов по ходу движения.

Публичный вход — `IterativeSession` (см. `session.py`): шаг / N шагов / до
точки через Δx / смена конфигурации / досчитать до конца / остановить и
собрать результат. Работает для отката (накат — автоматические обратные
переключения в тех же точках) и для свободного падения.
"""

from .config import (  # noqa: F401
    Config,
    KIND_CURVE,
    KIND_OFF,
    KIND_PARAMETRIC,
    Slot,
    slot_from_brake_config,
    slot_kind,
)
from .physics import MODE_FREE_FALL, MODE_RECOIL  # noqa: F401
from .session import (  # noqa: F401
    DIRECTION_FORWARD,
    DIRECTION_RETURN,
    PHASE_FALL,
    PHASE_RECOIL,
    PHASE_RETURN,
    STOP_FINISHED,
    STOP_STEPS,
    STOP_TARGET,
    STOP_TURNAROUND,
    TERMINATION_STOPPED,
    AdvanceReport,
    IterativeOutcome,
    IterativeSession,
    Stage,
    SwitchEvent,
)

"""Обратное проектирование тормозов (inverse design) — MVP.

Синтез характеристики одиночного curve-тормоза F(|v|) под конечные условия
цикла (время T, откат x_max, скорость в конце наката v_end), при ограничении
на суммарное усилие, с оценкой робастности к разбросу параметров.

Публичный вход — `run_design_study` из `study.py`.
"""

from .targets import DesignConstraints, DesignTargets, ToleranceModel  # noqa: F401
from .forward import Metrics, evaluate  # noqa: F401
from .study import DesignResult, run_design_study  # noqa: F401

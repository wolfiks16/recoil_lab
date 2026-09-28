"""Чтение сохранённых HTML-фрагментов Plotly с понятными сообщениями об ошибках.

Графики расчёта/теплового сценария лежат файлами в `media/` (FileField на модели).
Раньше ошибка чтения уходила в шаблон как «chart_x_t: [Errno 2] No such file ...» —
путь и errno пользователю ничего не говорят. Здесь технические детали идут в лог,
а в UI — фраза «график «…» не найден: пересчитайте расчёт».
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Человеческие названия FileField'ов графиков (для сообщений об ошибках).
CHART_TITLES: dict[str, str] = {
    "chart_x_t_annotated": "перемещение x(t)",
    "chart_energy": "энергобаланс",
    "chart_x_t": "перемещение x(t)",
    "chart_v_a_t": "скорость и ускорение",
    "chart_v_x": "фазовая траектория v(x)",
    "chart_fmag_v": "сила торможения от скорости",
    "chart_forces_secondary": "силы F(t)",
    "chart_x_t_recoil": "перемещение на откате",
    "chart_v_a_t_recoil": "скорость и ускорение на откате",
    "chart_forces_main_recoil": "движущая и суммарная сила на откате",
    "chart_forces_secondary_recoil": "силы на откате",
    "chart_x_t_return": "перемещение на накате",
    "chart_v_a_t_return": "скорость и ускорение на накате",
    "chart_forces_secondary_return": "силы на накате",
    "chart_temperatures": "температуры узлов",
    "chart_power_brakes": "мощность тормозов",
    "chart_heat_brakes": "накопленное тепло",
    "chart_cycle_envelope": "огибающая по циклам",
}


def read_chart_fragment(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_chart_fields(obj, fields: list[str]) -> tuple[dict[str, str], list[str]]:
    """Читает фрагменты графиков из FileField'ов `obj`.

    Возвращает (html по имени поля, список понятных сообщений о пропавших графиках).
    Поле без файла (график не строился) — не ошибка: его просто нет в словаре.
    """
    html: dict[str, str] = {}
    problems: list[str] = []
    for name in fields:
        field_file = getattr(obj, name, None)
        if not field_file or not getattr(field_file, "name", ""):
            continue
        try:
            html[name] = read_chart_fragment(field_file.path)
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Не удалось прочитать график %s у %r: %s", name, obj, exc)
            problems.append(chart_problem_text(name))
    return html, problems


def chart_problem_text(field_name: str) -> str:
    title = CHART_TITLES.get(field_name, field_name)
    return f"График «{title}» не найден в хранилище — пересоздайте расчёт, чтобы построить его заново."

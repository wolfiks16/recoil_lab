"""Plotly-фрагменты для теплового модуля.

Стилистика — общая с проектом: цвета, шрифты, _apply_layout берутся из
recoil_app.services.charting. Сюда импортируем только хелперы; новых палитр
не плодим. Для 9 узлов набор серий — RB-палитра + plotly Set2 расширение,
чтобы каждый узел имел стабильный цвет.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

from ..charting import (
    FONT_FAMILY_MONO,
    FONT_FAMILY_UI,
    LINE_WIDTH_PRIMARY,
    LINE_WIDTH_SECONDARY,
    RB_ACCENT,
    RB_AMBER,
    RB_BLUE,
    RB_GRAY,
    RB_GREEN,
    RB_PINK,
    RB_PURPLE,
    SERIES_PALETTE,
    _apply_layout,
    _hex_to_rgba,
)
from .cycles import CombinedCycleResult
from .decimation import (
    DEFAULT_TARGET_HZ,
    decimate_per_segment,
    merge_indices,
    pick_peak_indices,
)
from .network import ThermalNetwork


# Расширяем палитру до 9 элементов для 9-узловой сети.
NODE_PALETTE = SERIES_PALETTE + ["#0EA5E9", "#84CC16"]  # cyan, lime — для 8-го и 9-го узла


def _node_color(i: int) -> str:
    return NODE_PALETTE[i % len(NODE_PALETTE)]


def _save_fragment(fig: go.Figure, output_dir: Path, filename: str) -> str:
    path = output_dir / filename
    html = pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        default_height="520px",
        validate=True,
    )
    path.write_text(html, encoding="utf-8")
    return str(path)


def _decimated_view(combined: CombinedCycleResult, target_hz: float):
    """Возвращает декиматированный namespace (t, temp_nodes, power_nodes, power_brakes, heat_brakes, cycle_index, segment).

    Сохраняет точки пиков температур и границы сегментов — графики не теряют
    «характерные» особенности.
    """
    n = len(combined.t)
    if n == 0:
        return (
            combined.t, combined.temp_nodes, combined.power_nodes,
            combined.power_brakes, combined.heat_brakes,
            combined.cycle_index, combined.segment,
        )
    seg_idx = decimate_per_segment(
        t=combined.t, segment=combined.segment,
        cycle_index=combined.cycle_index, target_hz=target_hz,
    )
    peaks = pick_peak_indices(combined.temp_nodes)
    keep = merge_indices(seg_idx, peaks)
    return (
        combined.t[keep],
        combined.temp_nodes[keep, :],
        combined.power_nodes[keep, :],
        combined.power_brakes[keep, :] if combined.power_brakes.size else combined.power_brakes,
        combined.heat_brakes[keep, :] if combined.heat_brakes.size else combined.heat_brakes,
        combined.cycle_index[keep],
        combined.segment[keep],
    )


def _add_cycle_boundaries(fig: go.Figure, t: np.ndarray, cycle_index: np.ndarray, segment: np.ndarray) -> None:
    """Вертикальные пунктиры на границах braking↔pause и cycle↔cycle."""
    if len(t) < 2:
        return
    n = len(t)
    keys = list(zip(cycle_index.tolist(), segment.tolist()))
    for i in range(1, n):
        if keys[i] != keys[i - 1]:
            # граница сегмента — рисуем светло-серую линию
            fig.add_vline(
                x=float(t[i]),
                line=dict(color="#C5CDD8", width=1, dash="dot"),
                layer="below",
            )


# --- 1. Температуры узлов во времени --------------------------------------------------


def chart_temperatures(
    combined: CombinedCycleResult,
    network: ThermalNetwork,
    target_hz: float = DEFAULT_TARGET_HZ,
) -> go.Figure:
    t, temp_nodes, _, _, _, cycle_idx, segment = _decimated_view(combined, target_hz)
    fig = go.Figure()
    for k, node in enumerate(network.nodes):
        fig.add_trace(go.Scatter(
            x=t,
            y=temp_nodes[:, k],
            mode="lines",
            name=node.display_name,
            line=dict(color=_node_color(k), width=LINE_WIDTH_SECONDARY),
            hovertemplate=(
                f"<b>{node.display_name}</b><br>"
                "t = %{x:.2f} с<br>"
                "T = %{y:.2f} °C<extra></extra>"
            ),
        ))

    _add_cycle_boundaries(fig, t, cycle_idx, segment)
    _apply_layout(fig, "Температура узлов во времени", "t, с", "T, °C")
    return fig


# --- 2. Мощность тормозов во времени --------------------------------------------------


def chart_power_brakes(
    combined: CombinedCycleResult,
    network: ThermalNetwork,
    target_hz: float = DEFAULT_TARGET_HZ,
) -> go.Figure:
    t, _, _, power_brakes, _, cycle_idx, segment = _decimated_view(combined, target_hz)
    fig = go.Figure()
    n_brakes = power_brakes.shape[1]
    for b in range(n_brakes):
        # Имя источника для тормоза b: возьмём из network.sources, иначе по индексу.
        node_name = next(
            (s.node_name for s in network.sources if s.brake_index == b),
            f"тормоз #{b}",
        )
        node_display = next(
            (n.display_name for n in network.nodes if n.name == node_name),
            f"Тормоз #{b + 1}",
        )
        # P_brake — мощность; пик во время активной фазы, ноль в паузе.
        fig.add_trace(go.Scatter(
            x=t,
            y=power_brakes[:, b] / 1000.0,  # в кВт
            mode="lines",
            name=f"{node_display}",
            line=dict(color=_node_color(b * 3), width=LINE_WIDTH_SECONDARY),
            hovertemplate=(
                f"<b>{node_display}</b><br>"
                "t = %{x:.2f} с<br>"
                "P = %{y:.2f} кВт<extra></extra>"
            ),
        ))
    _add_cycle_boundaries(fig, t, cycle_idx, segment)
    _apply_layout(fig, "Мощность тепловыделения тормозов", "t, с", "P, кВт")
    return fig


# --- 3. Накопленное тепло -------------------------------------------------------------


def chart_heat_brakes(
    combined: CombinedCycleResult,
    network: ThermalNetwork,
    target_hz: float = DEFAULT_TARGET_HZ,
) -> go.Figure:
    t, _, _, _, heat_brakes, cycle_idx, segment = _decimated_view(combined, target_hz)
    fig = go.Figure()
    n_brakes = heat_brakes.shape[1]
    for b in range(n_brakes):
        node_name = next(
            (s.node_name for s in network.sources if s.brake_index == b),
            f"тормоз #{b}",
        )
        node_display = next(
            (n.display_name for n in network.nodes if n.name == node_name),
            f"Тормоз #{b + 1}",
        )
        fig.add_trace(go.Scatter(
            x=t,
            y=heat_brakes[:, b] / 1000.0,  # в кДж
            mode="lines",
            name=node_display,
            line=dict(color=_node_color(b * 3), width=LINE_WIDTH_SECONDARY),
            hovertemplate=(
                f"<b>{node_display}</b><br>"
                "t = %{x:.2f} с<br>"
                "Q = %{y:.1f} кДж<extra></extra>"
            ),
        ))
    _add_cycle_boundaries(fig, t, cycle_idx, segment)
    _apply_layout(fig, "Накопленное тепло, рассеянное тормозами", "t, с", "Q, кДж")
    return fig


# --- 4. Огибающая T_max по циклам -----------------------------------------------------


def chart_cycle_envelope(
    combined: CombinedCycleResult,
    network: ThermalNetwork,
) -> go.Figure:
    """Для каждого узла — три точки на цикл: start / end_braking / end_pause.

    Получается ступенчатый профиль, по которому видно динамику накопления и
    спада за каждый цикл. Для длинных серий стрельб это самый информативный
    график.
    """
    fig = go.Figure()
    cycles = combined.summaries
    if not cycles:
        _apply_layout(fig, "Огибающая температур по циклам", "Цикл", "T, °C")
        return fig

    # Ось X: на каждый цикл три «момента». Делаем точки на 0.0/0.5/1.0 внутри цикла.
    x_positions: list[float] = []
    x_labels: list[str] = []
    for c in cycles:
        n = c.cycle_number
        x_positions.extend([n - 1.0, n - 0.5, n - 0.05])
        x_labels.extend([f"{n}", "→", "пауза"])

    for k, node in enumerate(network.nodes):
        ys = []
        for c in cycles:
            ys.append(c.start_temp_c.get(node.display_name, np.nan))
            ys.append(c.end_temp_after_braking_c.get(node.display_name, np.nan))
            ys.append(c.end_temp_after_pause_c.get(node.display_name, np.nan))
        fig.add_trace(go.Scatter(
            x=x_positions,
            y=ys,
            mode="lines+markers",
            name=node.display_name,
            line=dict(color=_node_color(k), width=LINE_WIDTH_SECONDARY),
            marker=dict(size=6, color=_node_color(k)),
            hovertemplate=(
                f"<b>{node.display_name}</b><br>"
                "T = %{y:.2f} °C<extra></extra>"
            ),
        ))

    # Подпишем оси: каждое целое число — номер цикла.
    cycle_ticks = list(range(1, len(cycles) + 1))
    fig.update_xaxes(tickmode="array", tickvals=cycle_ticks, ticktext=[f"#{c}" for c in cycle_ticks])
    _apply_layout(fig, "Огибающая температур по циклам (старт → конец активной → конец паузы)", "Цикл", "T, °C")
    return fig


# --- save all -------------------------------------------------------------------------


def save_thermal_charts(
    combined: CombinedCycleResult,
    network: ThermalNetwork,
    output_dir: Path,
    prefix: str,
) -> dict[str, str]:
    """Сохраняет 4 HTML-фрагмента с graceful fallback на случай отсутствия данных.

    Возвращает словарь chart_key → path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    paths["chart_temperatures"] = _save_fragment(
        chart_temperatures(combined, network),
        output_dir,
        f"{prefix}_temperatures.html",
    )
    if combined.power_brakes.shape[1] > 0:
        paths["chart_power_brakes"] = _save_fragment(
            chart_power_brakes(combined, network),
            output_dir,
            f"{prefix}_power_brakes.html",
        )
        paths["chart_heat_brakes"] = _save_fragment(
            chart_heat_brakes(combined, network),
            output_dir,
            f"{prefix}_heat_brakes.html",
        )
    if combined.summaries:
        paths["chart_cycle_envelope"] = _save_fragment(
            chart_cycle_envelope(combined, network),
            output_dir,
            f"{prefix}_cycle_envelope.html",
        )

    return paths

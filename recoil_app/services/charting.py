from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio


# === ЕДИНЫЙ СТИЛЬ ГРАФИКОВ (соответствует design_system.css) ===

# Брендовая палитра
RB_BLUE        = "#3D73EB"
RB_BLUE_FILL   = "rgba(61, 115, 235, 0.12)"
RB_ACCENT      = "#B44D7A"   # розово-магентовый акцент
RB_GREEN       = "#10B981"
RB_AMBER       = "#F59E0B"
RB_PURPLE      = "#8B5CF6"
RB_PINK        = "#EC4899"
RB_GRAY        = "#6B7280"

# Палитра серий для multi-curve графиков (используется по индексу)
SERIES_PALETTE = [RB_BLUE, RB_ACCENT, RB_GREEN, RB_AMBER, RB_PURPLE, RB_PINK, RB_GRAY]

# Толщины линий
LINE_WIDTH_PRIMARY   = 3.0   # для одиночной главной кривой (как у x(t))
LINE_WIDTH_SECONDARY = 2.5   # для серий в multi-curve
LINE_WIDTH_DASHED    = 2.0   # для пунктирных (например, входная энергия)

# Шрифты
FONT_FAMILY_UI    = "Manrope, -apple-system, Segoe UI, Arial, sans-serif"
FONT_FAMILY_MONO  = "JetBrains Mono, Consolas, monospace"

# Параметры маркера пика
PEAK_MARKER_SIZE = 10
PEAK_MARKER_LINE_W = 2

# Параметры аннотации
ANNOT_FONT_SIZE = 12

# Параметры vline разворота
RECOIL_LINE_DASH = "dash"
RECOIL_LINE_W = 1.5


def _series_color(i: int) -> str:
    """Цвет i-й серии из палитры (циклически)."""
    return SERIES_PALETTE[i % len(SERIES_PALETTE)]


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB → rgba(r, g, b, a) для полупрозрачных линий и подписей."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _add_recoil_vline(fig: go.Figure, result, label_text: str = "разворот") -> None:
    """Вертикальная пунктирная линия в момент разворота (если он есть).

    Используется на графиках, где есть ось t.
    """
    if result.recoil_end_time is None or result.recoil_end_index is None:
        return
    idx = int(result.recoil_end_index)
    if not (0 <= idx < len(result.t)):
        return
    fig.add_vline(
        x=float(result.t[idx]),
        line=dict(color=RB_ACCENT, width=RECOIL_LINE_W, dash=RECOIL_LINE_DASH),
        annotation_text=label_text,
        annotation_position="top",
        annotation_font=dict(color=RB_ACCENT, size=11, family=FONT_FAMILY_MONO),
    )


def _add_peak_marker(
    fig: go.Figure,
    x_value: float,
    y_value: float,
    label: str,
    color: str = RB_ACCENT,
    yref: str = "y",
    label_xpos: float = 0.5,
    **kwargs,
) -> None:
    """Маркер пика: точка на (x, y) + горизонтальная пунктирная линия на уровне y
    + полупрозрачная подпись по линии.

    Линия идёт горизонтально на уровне пика (касается кривой только в одной точке),
    а подпись слабо видна на фоне графика — не перекрывает данные.

    label_xpos — позиция плашки по горизонтали в долях ширины графика (0..1).
    Для overlay-сравнения используем 0.33 / 0.66, чтобы плашки A и B не наложились.

    Любые лишние kwargs (ax, ay, x_arr, y_arr) принимаются для совместимости.
    """
    line_color = _hex_to_rgba(color, 0.45)

    # Точка на самом пике — индикация x-позиции
    fig.add_trace(
        go.Scatter(
            x=[x_value],
            y=[y_value],
            mode="markers",
            marker=dict(color=color, size=PEAK_MARKER_SIZE - 2, line=dict(color="white", width=PEAK_MARKER_LINE_W)),
            showlegend=False,
            hoverinfo="skip",
            yaxis=yref if yref != "y" else None,
        )
    )
    # Горизонтальная пунктирная линия на уровне y_value, на всю ширину графика.
    # layer="below" → линия под кривой, кривая не разрывается визуально.
    fig.add_shape(
        type="line",
        xref="paper", x0=0.0, x1=1.0,
        yref=yref, y0=y_value, y1=y_value,
        line=dict(color=line_color, width=1.5, dash="dash"),
        layer="below",
    )
    # Полупрозрачная подпись (чуть выше линии — чтобы её не перерезала).
    fig.add_annotation(
        xref="paper", x=label_xpos,
        yref=yref, y=y_value,
        text=label,
        showarrow=False,
        bgcolor="rgba(255,255,255,0.7)",
        bordercolor=line_color,
        borderwidth=1,
        font=dict(color=color, size=ANNOT_FONT_SIZE - 1, family=FONT_FAMILY_MONO),
        borderpad=4,
        yshift=14,
        opacity=0.9,
    )


def _phase_label(phase_name: str) -> str:
    return {
        "recoil": "откат",
        "return": "накат",
    }.get(phase_name, phase_name)


def _aligned_zero_ranges(y_left, y_right):
    left_min = float(min(y_left))
    left_max = float(max(y_left))
    right_min = float(min(y_right))
    right_max = float(max(y_right))

    left_min = min(left_min, 0.0)
    left_max = max(left_max, 0.0)
    right_min = min(right_min, 0.0)
    right_max = max(right_max, 0.0)

    left_neg = abs(left_min)
    left_pos = abs(left_max)
    right_neg = abs(right_min)
    right_pos = abs(right_max)

    if left_neg == 0 and left_pos == 0:
        left_neg, left_pos = 1.0, 1.0
    if right_neg == 0 and right_pos == 0:
        right_neg, right_pos = 1.0, 1.0

    neg_ratio = max(
        left_neg / (left_neg + left_pos),
        right_neg / (right_neg + right_pos),
    )
    pos_ratio = 1.0 - neg_ratio

    if neg_ratio <= 0 or pos_ratio <= 0:
        neg_ratio = 0.5
        pos_ratio = 0.5

    left_scale = max(
        left_neg / neg_ratio if left_neg > 0 else 0.0,
        left_pos / pos_ratio if left_pos > 0 else 0.0,
    )
    right_scale = max(
        right_neg / neg_ratio if right_neg > 0 else 0.0,
        right_pos / pos_ratio if right_pos > 0 else 0.0,
    )

    left_range = [-neg_ratio * left_scale, pos_ratio * left_scale]
    right_range = [-neg_ratio * right_scale, pos_ratio * right_scale]
    return left_range, right_range


def _save_fragment(fig: go.Figure, output_dir: Path, filename: str) -> str:
    path = output_dir / filename
    html = pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        default_height="720px",
        validate=True,
    )
    path.write_text(html, encoding="utf-8")
    return str(path)


def _apply_layout(fig: go.Figure, title: str, x_title: str, y_title: str) -> go.Figure:
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(family=FONT_FAMILY_UI, size=15, color="#1B2430"),
        ),
        template="plotly_white",
        hovermode="x unified",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        legend=dict(
            x=0.99,
            y=0.99,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC",
            borderwidth=1,
            font=dict(family=FONT_FAMILY_MONO, size=11),
        ),
        margin=dict(l=60, r=40, t=80, b=55),
        plot_bgcolor="white",
    )
    fig.update_xaxes(
        title=dict(text=x_title, font=dict(family=FONT_FAMILY_MONO, size=11)),
        gridcolor="#E1E5EC",
        zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )
    fig.update_yaxes(
        title=dict(text=y_title, font=dict(family=FONT_FAMILY_MONO, size=11)),
        gridcolor="#E1E5EC",
        zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )
    return fig


def _make_dual_axis_figure(x, y_left, y_right, title: str, result=None) -> go.Figure:
    """Двойная ось v(t) и a(t).

    Если передан result — добавляет маркер на v_max и вертикальную линию разворота.
    """
    left_range, right_range = _aligned_zero_ranges(y_left, y_right)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y_left, mode="lines", name="v(t)", yaxis="y1",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=x, y=y_right, mode="lines", name="a(t)", yaxis="y2",
        line=dict(color=RB_ACCENT, width=LINE_WIDTH_SECONDARY),
    ))

    fig.update_layout(
        title=dict(
            text=title,
            font=dict(family=FONT_FAMILY_UI, size=15, color="#1B2430"),
        ),
        template="plotly_white",
        hovermode="x unified",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        plot_bgcolor="white",
        yaxis=dict(
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_MONO, size=11, color=RB_BLUE)),
            range=left_range,
            zeroline=True,
            zerolinewidth=1.5,
            zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10, color=RB_BLUE),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с²", font=dict(family=FONT_FAMILY_MONO, size=11, color=RB_ACCENT)),
            overlaying="y",
            side="right",
            range=right_range,
            zeroline=True,
            zerolinewidth=1.5,
            zerolinecolor="#C5CDD8",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10, color=RB_ACCENT),
        ),
        legend=dict(
            x=0.99,
            y=0.99,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC",
            borderwidth=1,
            font=dict(family=FONT_FAMILY_MONO, size=11),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_MONO, size=11)),
        gridcolor="#E1E5EC",
        zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )

    # Маркер v_max и vline разворота — если есть полные данные о результате.
    if result is not None:
        try:
            y_arr = np.asarray(y_left, dtype=float)
            x_arr = np.asarray(x, dtype=float)
            if len(y_arr) > 0:
                peak_i = int(np.argmax(y_arr))
                _add_peak_marker(
                    fig,
                    x_value=float(x_arr[peak_i]),
                    y_value=float(y_arr[peak_i]),
                    label=f"v_max = {y_arr[peak_i]:.2f} м/с",
                    color=RB_BLUE,
                    yref="y",
                    x_arr=x_arr,
                    y_arr=y_arr,
                )
        except Exception:
            pass
        _add_recoil_vline(fig, result)

    return fig


def _save_phase_charts(
    files: dict[str, str],
    result,
    output_dir: Path,
    prefix: str,
    phase_name: str,
    mask,
) -> None:
    if mask is None or not mask.any():
        return

    phase_label = _phase_label(phase_name)

    t = result.t[mask]
    x = result.x[mask]
    v = result.v[mask]
    a = result.a[mask]
    f_ext = result.f_ext[mask]
    f_total = result.f_total[mask]
    f_angle = result.f_angle[mask]
    f_spring = result.f_spring[mask]
    f_mag_sum = result.f_magnetic[mask]
    f_each = result.f_magnetic_each[mask, :]

    n_brakes = f_each.shape[1] if f_each.ndim == 2 else 0

    # === x(t) для фазы — толстая синяя линия + заливка + маркер пика ===
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t, y=x, mode="lines", name="x(t)",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=RB_BLUE_FILL,
    ))
    # Маркер локального пика x_max в этой фазе
    if len(x) > 0:
        peak_i = int(np.argmax(np.abs(x)))
        _add_peak_marker(
            fig,
            x_value=float(t[peak_i]),
            y_value=float(x[peak_i]),
            label=f"x = {x[peak_i] * 1000:.1f} мм",
            color=RB_ACCENT,
            x_arr=t,
            y_arr=x,
        )
    files[f"chart_x_t_{phase_name}"] = _save_fragment(
        _apply_layout(fig, f"Перемещение от времени — фаза {phase_label}", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t_{phase_name}.html",
    )

    # === v · a (t) для фазы ===
    fig = _make_dual_axis_figure(
        t, v, a,
        f"Скорость и ускорение от времени — фаза {phase_label}",
        result=None,  # маркер v_max добавим вручную ниже
    )
    if len(v) > 0:
        peak_i = int(np.argmax(np.abs(v)))
        _add_peak_marker(
            fig,
            x_value=float(t[peak_i]),
            y_value=float(v[peak_i]),
            label=f"v_max = {v[peak_i]:.2f} м/с",
            color=RB_BLUE,
            yref="y",
            x_arr=t,
            y_arr=v,
        )
    files[f"chart_v_a_t_{phase_name}"] = _save_fragment(
        fig,
        output_dir,
        f"{prefix}_v_a_t_{phase_name}.html",
    )

    # === Движущая и суммарная силы (только для отката) ===
    if phase_name == "recoil":
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=t, y=f_ext, mode="lines", name="Fдв - движущая сила",
            line=dict(color=RB_BLUE, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t, y=f_total, mode="lines", name="FΣ - суммарная сила",
            line=dict(color=RB_ACCENT, width=LINE_WIDTH_SECONDARY),
        ))
        files[f"chart_forces_main_{phase_name}"] = _save_fragment(
            _apply_layout(fig, f"Движущая и суммарная силы от времени — фаза {phase_label}", "t, c", "F, Н"),
            output_dir,
            f"{prefix}_forces_main_{phase_name}.html",
        )

    # === Распределение сил по фазе ===
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t, y=f_angle, mode="lines", name="Fугла",
        line=dict(color=_series_color(0), width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=t, y=f_spring, mode="lines", name="Fпруж",
        line=dict(color=_series_color(1), width=LINE_WIDTH_SECONDARY),
    ))
    for j in range(n_brakes):
        fig.add_trace(go.Scatter(
            x=t, y=f_each[:, j], mode="lines", name=f"Fмаг{j + 1}",
            line=dict(color=_series_color(2 + j), width=LINE_WIDTH_SECONDARY),
        ))
    fig.add_trace(go.Scatter(
        x=t, y=f_mag_sum, mode="lines", name="Fмаг_сумм",
        line=dict(color=_series_color(2 + n_brakes), width=LINE_WIDTH_SECONDARY, dash="dot"),
    ))

    if phase_name == "return":
        fig.add_trace(go.Scatter(
            x=t, y=f_total, mode="lines", name="FΣ - суммарная сила",
            line=dict(color=RB_GRAY, width=LINE_WIDTH_PRIMARY),
        ))

    files[f"chart_forces_secondary_{phase_name}"] = _save_fragment(
        _apply_layout(fig, f"Распределение сил от времени — фаза {phase_label}", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary_{phase_name}.html",
    )


def _save_annotated_x_t(result, output_dir: Path, prefix: str) -> str:
    """x(t) с подсвеченным пиком x_max и затемнённой областью под кривой.

    Используется в новом дизайне result-страницы как hero-график.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=result.t, y=result.x, mode="lines", name="x(t)",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=RB_BLUE_FILL,
    ))

    # Маркер пика
    if len(result.x):
        peak_idx = int(result.x.argmax())
        _add_peak_marker(
            fig,
            x_value=float(result.t[peak_idx]),
            y_value=float(result.x[peak_idx]),
            label=f"x_max = {float(result.x[peak_idx]) * 1000:.1f} мм",
            color=RB_ACCENT,
            x_arr=result.t,
            y_arr=result.x,
        )

    # Точка разворота
    _add_recoil_vline(fig, result)

    return _save_fragment(
        _apply_layout(fig, "Перемещение откатных частей x(t)", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t_annotated.html",
    )


def _save_energy_balance(result, output_dir: Path, prefix: str) -> str:
    """График энергобаланса: E_kin, E_spring, E_brake_cum + невязка."""
    if result.energy_kinetic is None:
        return ""

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=result.t, y=result.energy_kinetic, mode="lines",
        name="E_кин = mv²/2",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=result.t, y=result.energy_spring, mode="lines",
        name="E_пруж = ∫F_пр dx",
        line=dict(color=RB_GREEN, width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=result.t, y=result.energy_brake_cum, mode="lines",
        name="E_торм (рассеяно)",
        line=dict(color=RB_ACCENT, width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=result.t, y=result.energy_input_cum, mode="lines",
        name="E_вход (выстрел+гравит.)",
        line=dict(color=RB_AMBER, width=LINE_WIDTH_DASHED, dash="dot"),
    ))

    _add_recoil_vline(fig, result)

    residual_pct = result.energy_residual_pct
    title = "Энергобаланс"
    if residual_pct is not None:
        title = f"Энергобаланс — макс. невязка {residual_pct:.2f}%"

    return _save_fragment(
        _apply_layout(fig, title, "t, c", "E, Дж"),
        output_dir,
        f"{prefix}_energy.html",
    )


def save_interactive_charts(result, output_dir: str | Path, prefix: str = "run") -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}

    recoil_mask = None
    return_mask = None

    if result.recoil_end_time is not None:
        recoil_mask = result.t <= result.recoil_end_time
        return_mask = result.t >= result.recoil_end_time

    n_brakes = result.f_magnetic_each.shape[1] if result.f_magnetic_each.ndim == 2 else 0

    # === x(t) общий — синяя линия (без аннотации, аннотированный делает _save_annotated_x_t) ===
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=result.t, y=result.x, mode="lines", name="x(t)",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=RB_BLUE_FILL,
    ))
    _add_recoil_vline(fig, result)
    files["chart_x_t"] = _save_fragment(
        _apply_layout(fig, "Перемещение от времени", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t.html",
    )

    # === v · a (t) — двойная ось, маркер на v_max, vline разворота ===
    fig = _make_dual_axis_figure(
        result.t, result.v, result.a,
        "Скорость и ускорение от времени",
        result=result,
    )
    files["chart_v_a_t"] = _save_fragment(
        fig,
        output_dir,
        f"{prefix}_v_a_t.html",
    )

    # === v(x) — фазовая плоскость, маркер на точке разворота (v ≈ 0 при x_max) ===
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=result.x, y=result.v, mode="lines", name="v(x)",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=RB_BLUE_FILL,
    ))
    # Точка разворота: где v=0 на максимуме x
    if result.recoil_end_index is not None:
        idx = int(result.recoil_end_index)
        if 0 <= idx < len(result.x):
            _add_peak_marker(
                fig,
                x_value=float(result.x[idx]),
                y_value=float(result.v[idx]),
                label=f"разворот · x = {result.x[idx] * 1000:.1f} мм",
                color=RB_ACCENT,
                x_arr=result.x,
                y_arr=result.v,
            )
    files["chart_v_x"] = _save_fragment(
        _apply_layout(fig, "Скорость от перемещения", "x, м", "v, м/с"),
        output_dir,
        f"{prefix}_v_x.html",
    )

    # === F_маг(v) — маркеры (это график-зависимость, не процесс) ===
    fig = go.Figure()
    for j in range(n_brakes):
        fig.add_trace(go.Scatter(
            x=result.v, y=result.f_magnetic_each[:, j], mode="markers",
            name=f"Fмаг{j + 1}(v)",
            marker=dict(color=_series_color(j), size=4, opacity=0.65),
        ))
    fig.add_trace(go.Scatter(
        x=result.v, y=result.f_magnetic, mode="markers",
        name="Fмаг_сумм(v)",
        marker=dict(color=RB_ACCENT, size=5, opacity=0.85),
    ))
    files["chart_fmag_v"] = _save_fragment(
        _apply_layout(fig, "Магнитные силы от скорости", "v, м/с", "F, Н"),
        output_dir,
        f"{prefix}_fmag_v.html",
    )

    # === F(t) распределение сил — несколько серий из палитры + vline разворота ===
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=result.t, y=result.f_angle, mode="lines", name="Fугла",
        line=dict(color=_series_color(0), width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=result.t, y=result.f_spring, mode="lines", name="Fпруж",
        line=dict(color=_series_color(1), width=LINE_WIDTH_SECONDARY),
    ))
    for j in range(n_brakes):
        fig.add_trace(go.Scatter(
            x=result.t, y=result.f_magnetic_each[:, j], mode="lines",
            name=f"Fмаг{j + 1}",
            line=dict(color=_series_color(2 + j), width=LINE_WIDTH_SECONDARY),
        ))
    fig.add_trace(go.Scatter(
        x=result.t, y=result.f_magnetic, mode="lines", name="Fмаг_сумм",
        line=dict(color=_series_color(2 + n_brakes), width=LINE_WIDTH_SECONDARY, dash="dot"),
    ))
    _add_recoil_vline(fig, result)
    files["chart_forces_secondary"] = _save_fragment(
        _apply_layout(fig, "Распределение сил от времени", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary.html",
    )

    _save_phase_charts(files, result, output_dir, prefix, "recoil", recoil_mask)
    _save_phase_charts(files, result, output_dir, prefix, "return", return_mask)

    # Дополнительные графики для нового дизайна страницы результата.
    # Если что-то упадёт — расчёт остаётся валидным, базовые графики уже сохранены.
    try:
        files["chart_x_t_annotated"] = _save_annotated_x_t(result, output_dir, prefix)
    except Exception:
        pass
    try:
        energy_path = _save_energy_balance(result, output_dir, prefix)
        if energy_path:
            files["chart_energy"] = energy_path
    except Exception:
        pass

    return files

# ============================================================================
# СРЕЗ 3c: график F(v) для детальной страницы тормоза в каталоге
# ============================================================================

def make_brake_curve_fragment(
    points: list[dict],
    title: str = "Характеристика F(v)",
) -> str:
    """Возвращает HTML-фрагмент Plotly-графика F(v) для inline-вставки в шаблон.

    points: list of dicts {"velocity": float, "force": float} (отсортированы по v)
    """
    if not points:
        return ""

    velocities = [p["velocity"] for p in points]
    forces = [p["force"] for p in points]

    fig = go.Figure()
    # Линия + маркеры (это табличная характеристика — точки важны)
    fig.add_trace(go.Scatter(
        x=velocities,
        y=forces,
        mode="lines+markers",
        name="F(v)",
        line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
        marker=dict(color=RB_ACCENT, size=8, line=dict(color="white", width=2)),
        fill="tozeroy",
        fillcolor=RB_BLUE_FILL,
    ))

    _apply_layout(fig, title, "v, м/с", "F, Н")

    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        default_height="500px",
        validate=True,
    )


# ============================================================================
# СРЕЗ 5: Overlay-графики для страницы сравнения
# ============================================================================

# Цвета для двух расчётов в сравнении
_CMP_COLOR_A = RB_BLUE      # синий — расчёт A
_CMP_COLOR_B = RB_ACCENT    # розовый — расчёт B
_CMP_FILL_A  = RB_BLUE_FILL
_CMP_FILL_B  = "rgba(180, 77, 122, 0.10)"


def _to_html_fragment(fig: go.Figure, height: str = "560px") -> str:
    """Plotly inline без plotly.js (он уже грузится в base_v2)."""
    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        default_height=height,
        validate=True,
    )


def _peak_index_safe(arr) -> int | None:
    """Индекс максимума по абсолютному значению; None если массив пуст."""
    try:
        a = np.asarray(arr, dtype=float)
        if len(a) == 0:
            return None
        return int(np.argmax(np.abs(a)))
    except Exception:
        return None


def _add_compare_recoil_vline(fig: go.Figure, t_recoil: float | None, label: str, color: str) -> None:
    """Вертикальная пунктирная линия на t разворота (для сравнения — каждой свой цвет)."""
    if t_recoil is None:
        return
    fig.add_vline(
        x=float(t_recoil),
        line=dict(color=color, width=RECOIL_LINE_W, dash=RECOIL_LINE_DASH),
        annotation_text=label,
        annotation_position="top",
        annotation_font=dict(color=color, size=10, family=FONT_FAMILY_MONO),
    )


def make_compare_x_t_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str,
) -> str:
    """Overlay x(t) — две кривые на одной оси с заливкой и маркерами пиков."""
    t_a = snap_a.get("t", []); x_a = snap_a.get("x", [])
    t_b = snap_b.get("t", []); x_b = snap_b.get("x", [])
    t_recoil_a = snap_a.get("t_recoil_end")
    t_recoil_b = snap_b.get("t_recoil_end")

    fig = go.Figure()

    # A — синяя с заливкой
    fig.add_trace(go.Scatter(
        x=t_a, y=x_a, mode="lines", name=f"A · {name_a}",
        line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=_CMP_FILL_A,
    ))
    # B — розовая с заливкой
    fig.add_trace(go.Scatter(
        x=t_b, y=x_b, mode="lines", name=f"B · {name_b}",
        line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy",
        fillcolor=_CMP_FILL_B,
    ))

    # Маркеры пиков (плашки разнесены по горизонтали, чтобы A и B не наложились)
    pi_a = _peak_index_safe(x_a)
    if pi_a is not None and pi_a < len(t_a):
        _add_peak_marker(
            fig,
            x_value=float(t_a[pi_a]),
            y_value=float(x_a[pi_a]),
            label=f"A: x_max = {x_a[pi_a] * 1000:.1f} мм",
            color=_CMP_COLOR_A,
            label_xpos=0.33,
        )
    pi_b = _peak_index_safe(x_b)
    if pi_b is not None and pi_b < len(t_b):
        _add_peak_marker(
            fig,
            x_value=float(t_b[pi_b]),
            y_value=float(x_b[pi_b]),
            label=f"B: x_max = {x_b[pi_b] * 1000:.1f} мм",
            color=_CMP_COLOR_B,
            label_xpos=0.66,
        )

    # Vlines разворотов разными цветами
    _add_compare_recoil_vline(fig, t_recoil_a, "разворот A", _CMP_COLOR_A)
    _add_compare_recoil_vline(fig, t_recoil_b, "разворот B", _CMP_COLOR_B)

    _apply_layout(fig, "Сравнение x(t) — перемещение откатных частей", "t, c", "x, м")
    return _to_html_fragment(fig)


def make_compare_v_a_t_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str,
) -> str:
    """Overlay v(t) и a(t) — на двух осях, для каждого расчёта свой стиль."""
    t_a = snap_a.get("t", []); v_a = snap_a.get("v", []); a_a = snap_a.get("a", [])
    t_b = snap_b.get("t", []); v_b = snap_b.get("v", []); a_b = snap_b.get("a", [])

    # Определяем общие диапазоны для left/right
    left_range, right_range = _aligned_zero_ranges(
        list(v_a) + list(v_b),
        list(a_a) + list(a_b),
    )

    fig = go.Figure()

    # v — solid
    fig.add_trace(go.Scatter(
        x=t_a, y=v_a, mode="lines", name=f"A · v: {name_a}", yaxis="y1",
        line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY),
    ))
    fig.add_trace(go.Scatter(
        x=t_b, y=v_b, mode="lines", name=f"B · v: {name_b}", yaxis="y1",
        line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY),
    ))
    # a — dashed (чтобы отличить от v на одном графике)
    fig.add_trace(go.Scatter(
        x=t_a, y=a_a, mode="lines", name=f"A · a: {name_a}", yaxis="y2",
        line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=t_b, y=a_b, mode="lines", name=f"B · a: {name_b}", yaxis="y2",
        line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY, dash="dash"),
    ))

    fig.update_layout(
        title=dict(
            text=f"Сравнение v(t) и a(t) — A: {name_a}  ·  B: {name_b}",
            font=dict(family=FONT_FAMILY_UI, size=15, color="#1B2430"),
        ),
        template="plotly_white",
        hovermode="x unified",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        plot_bgcolor="white",
        yaxis=dict(
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_MONO, size=11)),
            range=left_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с² (dash)", font=dict(family=FONT_FAMILY_MONO, size=11)),
            overlaying="y", side="right",
            range=right_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        legend=dict(
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC", borderwidth=1,
            font=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_MONO, size=11)),
        gridcolor="#E1E5EC", zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )

    # Vlines разворотов
    t_recoil_a = snap_a.get("t_recoil_end")
    t_recoil_b = snap_b.get("t_recoil_end")
    _add_compare_recoil_vline(fig, t_recoil_a, "разворот A", _CMP_COLOR_A)
    _add_compare_recoil_vline(fig, t_recoil_b, "разворот B", _CMP_COLOR_B)

    return _to_html_fragment(fig)


def make_compare_v_x_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str,
) -> str:
    """Overlay v(x) — фазовая плоскость, две кривые с заливкой."""
    x_a = snap_a.get("x", []); v_a = snap_a.get("v", [])
    x_b = snap_b.get("x", []); v_b = snap_b.get("v", [])

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x_a, y=v_a, mode="lines", name=f"A · {name_a}",
        line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy", fillcolor=_CMP_FILL_A,
    ))
    fig.add_trace(go.Scatter(
        x=x_b, y=v_b, mode="lines", name=f"B · {name_b}",
        line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_PRIMARY),
        fill="tozeroy", fillcolor=_CMP_FILL_B,
    ))

    # Маркеры точек разворота (где v=0 в максимуме x)
    idx_a = snap_a.get("recoil_end_index")
    if idx_a is not None and 0 <= int(idx_a) < len(x_a):
        ia = int(idx_a)
        _add_peak_marker(
            fig,
            x_value=float(x_a[ia]),
            y_value=float(v_a[ia]),
            label=f"A: разворот x={x_a[ia]*1000:.1f} мм",
            color=_CMP_COLOR_A,
            label_xpos=0.33,
        )
    idx_b = snap_b.get("recoil_end_index")
    if idx_b is not None and 0 <= int(idx_b) < len(x_b):
        ib = int(idx_b)
        _add_peak_marker(
            fig,
            x_value=float(x_b[ib]),
            y_value=float(v_b[ib]),
            label=f"B: разворот x={x_b[ib]*1000:.1f} мм",
            color=_CMP_COLOR_B,
            label_xpos=0.66,
        )

    _apply_layout(fig, "Сравнение v(x) — фазовая плоскость", "x, м", "v, м/с")
    return _to_html_fragment(fig)


def make_compare_fmag_v_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str,
) -> str:
    """Overlay F_маг(v) — маркерные графики."""
    v_a = snap_a.get("v", [])
    f_a = snap_a.get("f_magnetic", [])
    v_b = snap_b.get("v", [])
    f_b = snap_b.get("f_magnetic", [])

    fig = go.Figure()

    if v_a and f_a:
        fig.add_trace(go.Scatter(
            x=v_a, y=f_a, mode="markers", name=f"A · {name_a}",
            marker=dict(color=_CMP_COLOR_A, size=5, opacity=0.7),
        ))
    if v_b and f_b:
        fig.add_trace(go.Scatter(
            x=v_b, y=f_b, mode="markers", name=f"B · {name_b}",
            marker=dict(color=_CMP_COLOR_B, size=5, opacity=0.7),
        ))

    _apply_layout(fig, "Сравнение F_маг(v) — суммарные магнитные силы", "v, м/с", "F, Н")
    return _to_html_fragment(fig)


# ---------------------------------------------------------------------------
# Утилиты для фазовых срезов
# ---------------------------------------------------------------------------

def _slice_phase(snap: dict, phase: str) -> dict:
    """Возвращает копию snap с массивами, обрезанными по выбранной фазе.

    phase = "recoil" → точки 0..recoil_end_index (включительно)
    phase = "return" → точки recoil_end_index..return_end_index (или до конца)
    Если границ нет — возвращает пустые массивы.
    """
    out = {**snap}
    n = len(snap.get("t") or [])
    if n == 0:
        return out

    rec_end = snap.get("recoil_end_index")
    ret_end = snap.get("return_end_index")

    if phase == "recoil":
        if rec_end is None:
            i0, i1 = 0, n
        else:
            i0, i1 = 0, int(rec_end) + 1
    elif phase == "return":
        if rec_end is None:
            return {**snap, "t": [], "x": [], "v": [], "a": [],
                    "f_magnetic": [], "f_total": [], "f_ext": [],
                    "f_spring": [], "f_angle": [], "f_magnetic_each": []}
        i0 = int(rec_end)
        i1 = int(ret_end) + 1 if ret_end is not None else n
    else:
        return out

    i1 = min(i1, n)
    if i0 >= i1:
        return {**snap, "t": [], "x": [], "v": [], "a": [],
                "f_magnetic": [], "f_total": [], "f_ext": [],
                "f_spring": [], "f_angle": [], "f_magnetic_each": []}

    def sl(key: str):
        arr = snap.get(key) or []
        return arr[i0:i1] if arr else []

    out["t"]               = sl("t")
    out["x"]               = sl("x")
    out["v"]               = sl("v")
    out["a"]               = sl("a")
    out["f_magnetic"]      = sl("f_magnetic")
    out["f_total"]         = sl("f_total")
    out["f_ext"]           = sl("f_ext")
    out["f_spring"]        = sl("f_spring")
    out["f_angle"]         = sl("f_angle")
    me = snap.get("f_magnetic_each") or []
    out["f_magnetic_each"] = me[i0:i1] if me else []

    # На фазовых срезах vline разворота не нужен — он стоит на границе
    out["t_recoil_end"] = None
    out["recoil_end_index"] = None

    return out


def has_phase(snap: dict, phase: str) -> bool:
    """True если у расчёта есть данные для фазы."""
    sliced = _slice_phase(snap, phase)
    return bool(sliced.get("t"))


# ---------------------------------------------------------------------------
# Compare-overlay: x(t) для произвольной фазы
# ---------------------------------------------------------------------------

def make_compare_x_t_phase_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str, phase: str,
) -> str:
    """Overlay x(t) для одной фазы (recoil/return)."""
    sa = _slice_phase(snap_a, phase)
    sb = _slice_phase(snap_b, phase)
    label = _phase_label(phase)
    return _make_compare_x_t_overlay(
        sa, sb, name_a, name_b,
        title=f"Сравнение x(t) — фаза {label}",
    )


def _make_compare_x_t_overlay(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str, title: str,
) -> str:
    t_a = snap_a.get("t", []); x_a = snap_a.get("x", [])
    t_b = snap_b.get("t", []); x_b = snap_b.get("x", [])

    fig = go.Figure()
    if t_a and x_a:
        fig.add_trace(go.Scatter(
            x=t_a, y=x_a, mode="lines", name=f"A · {name_a}",
            line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_PRIMARY),
            fill="tozeroy", fillcolor=_CMP_FILL_A,
        ))
    if t_b and x_b:
        fig.add_trace(go.Scatter(
            x=t_b, y=x_b, mode="lines", name=f"B · {name_b}",
            line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_PRIMARY),
            fill="tozeroy", fillcolor=_CMP_FILL_B,
        ))

    pi_a = _peak_index_safe(x_a)
    if pi_a is not None and pi_a < len(t_a):
        _add_peak_marker(
            fig,
            x_value=float(t_a[pi_a]), y_value=float(x_a[pi_a]),
            label=f"A: x_max = {x_a[pi_a] * 1000:.1f} мм",
            color=_CMP_COLOR_A, label_xpos=0.33,
        )
    pi_b = _peak_index_safe(x_b)
    if pi_b is not None and pi_b < len(t_b):
        _add_peak_marker(
            fig,
            x_value=float(t_b[pi_b]), y_value=float(x_b[pi_b]),
            label=f"B: x_max = {x_b[pi_b] * 1000:.1f} мм",
            color=_CMP_COLOR_B, label_xpos=0.66,
        )

    _apply_layout(fig, title, "t, c", "x, м")
    return _to_html_fragment(fig)


# ---------------------------------------------------------------------------
# Compare-overlay: v · a (t) для произвольной фазы
# ---------------------------------------------------------------------------

def make_compare_v_a_t_phase_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str, phase: str,
) -> str:
    sa = _slice_phase(snap_a, phase)
    sb = _slice_phase(snap_b, phase)
    label = _phase_label(phase)
    return _make_compare_v_a_t_overlay(
        sa, sb, name_a, name_b,
        title=f"Сравнение v(t) и a(t) — фаза {label}",
    )


def _make_compare_v_a_t_overlay(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str, title: str,
) -> str:
    t_a = snap_a.get("t", []); v_a = snap_a.get("v", []); a_a = snap_a.get("a", [])
    t_b = snap_b.get("t", []); v_b = snap_b.get("v", []); a_b = snap_b.get("a", [])

    if not (t_a or t_b):
        return _to_html_fragment(go.Figure())

    left_range, right_range = _aligned_zero_ranges(
        list(v_a) + list(v_b), list(a_a) + list(a_b),
    )

    fig = go.Figure()
    if t_a:
        fig.add_trace(go.Scatter(
            x=t_a, y=v_a, mode="lines", name=f"A · v: {name_a}", yaxis="y1",
            line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t_a, y=a_a, mode="lines", name=f"A · a: {name_a}", yaxis="y2",
            line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY, dash="dash"),
        ))
    if t_b:
        fig.add_trace(go.Scatter(
            x=t_b, y=v_b, mode="lines", name=f"B · v: {name_b}", yaxis="y1",
            line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t_b, y=a_b, mode="lines", name=f"B · a: {name_b}", yaxis="y2",
            line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY, dash="dash"),
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(family=FONT_FAMILY_UI, size=15, color="#1B2430")),
        template="plotly_white", hovermode="x unified",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        plot_bgcolor="white",
        yaxis=dict(
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_MONO, size=11)),
            range=left_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с² (dash)", font=dict(family=FONT_FAMILY_MONO, size=11)),
            overlaying="y", side="right", range=right_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        legend=dict(
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC", borderwidth=1,
            font=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_MONO, size=11)),
        gridcolor="#E1E5EC", zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )

    _add_compare_recoil_vline(fig, snap_a.get("t_recoil_end"), "разворот A", _CMP_COLOR_A)
    _add_compare_recoil_vline(fig, snap_b.get("t_recoil_end"), "разворот B", _CMP_COLOR_B)
    return _to_html_fragment(fig)


# ---------------------------------------------------------------------------
# Compare-overlay: распределение сил F(t) — общий и фазовые
# ---------------------------------------------------------------------------

def make_compare_forces_secondary_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str, phase: str | None = None,
) -> str:
    """Overlay распределения сил по времени (Fугла, Fпруж, Fмаг_сумм) для двух расчётов.

    Серии каждого расчёта окрашены в свой основной цвет, чтобы различить A/B,
    но с разной плотностью линии (пунктир для пружины, точка для магнитной).
    Если phase задан — данные обрезаются по фазе.
    """
    sa = _slice_phase(snap_a, phase) if phase else snap_a
    sb = _slice_phase(snap_b, phase) if phase else snap_b
    label = _phase_label(phase) if phase else None

    t_a = sa.get("t", [])
    t_b = sb.get("t", [])

    fig = go.Figure()

    def _add_run_series(t, snap, color, prefix):
        if not t:
            return
        fig.add_trace(go.Scatter(
            x=t, y=snap.get("f_angle", []), mode="lines",
            name=f"{prefix} · Fугла",
            line=dict(color=color, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t, y=snap.get("f_spring", []), mode="lines",
            name=f"{prefix} · Fпруж",
            line=dict(color=color, width=LINE_WIDTH_SECONDARY, dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=t, y=snap.get("f_magnetic", []), mode="lines",
            name=f"{prefix} · Fмаг_сумм",
            line=dict(color=color, width=LINE_WIDTH_SECONDARY, dash="dot"),
        ))

    _add_run_series(t_a, sa, _CMP_COLOR_A, f"A · {name_a}")
    _add_run_series(t_b, sb, _CMP_COLOR_B, f"B · {name_b}")

    title = "Сравнение распределения сил от времени"
    if label:
        title += f" — фаза {label}"
    _apply_layout(fig, title, "t, c", "F, Н")

    if phase is None:
        _add_compare_recoil_vline(fig, snap_a.get("t_recoil_end"), "разворот A", _CMP_COLOR_A)
        _add_compare_recoil_vline(fig, snap_b.get("t_recoil_end"), "разворот B", _CMP_COLOR_B)

    return _to_html_fragment(fig)


# ---------------------------------------------------------------------------
# Compare-overlay: F движущая · F общая (только для отката)
# ---------------------------------------------------------------------------

def make_compare_forces_main_recoil_fragment(
    snap_a: dict, snap_b: dict, name_a: str, name_b: str,
) -> str:
    """Overlay движущей и суммарной сил по времени, обрезанных по фазе отката."""
    sa = _slice_phase(snap_a, "recoil")
    sb = _slice_phase(snap_b, "recoil")
    t_a = sa.get("t", [])
    t_b = sb.get("t", [])

    fig = go.Figure()
    if t_a:
        fig.add_trace(go.Scatter(
            x=t_a, y=sa.get("f_ext", []), mode="lines",
            name=f"A · Fдв: {name_a}",
            line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t_a, y=sa.get("f_total", []), mode="lines",
            name=f"A · FΣ: {name_a}",
            line=dict(color=_CMP_COLOR_A, width=LINE_WIDTH_SECONDARY, dash="dash"),
        ))
    if t_b:
        fig.add_trace(go.Scatter(
            x=t_b, y=sb.get("f_ext", []), mode="lines",
            name=f"B · Fдв: {name_b}",
            line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY),
        ))
        fig.add_trace(go.Scatter(
            x=t_b, y=sb.get("f_total", []), mode="lines",
            name=f"B · FΣ: {name_b}",
            line=dict(color=_CMP_COLOR_B, width=LINE_WIDTH_SECONDARY, dash="dash"),
        ))

    _apply_layout(
        fig,
        "Сравнение движущей и суммарной сил — фаза откат",
        "t, c", "F, Н",
    )
    return _to_html_fragment(fig)

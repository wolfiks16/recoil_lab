from __future__ import annotations

import math
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


# --- Этапы итерационного расчёта (Срез 12) ---------------------------------
# overlay — словарь из services/iterative/overlay.build_stage_overlay (charting о
# пакете iterative не знает): segments / x_bands / events / stage_index.

_SWITCH_COLOR = RB_AMBER
STAGE_BAND_ALPHA = 0.08
STAGE_LABEL_MIN_FRACTION = 0.03   # подпись полосы этапа — если она шире 3% окна графика

# Этапы на графиках скрыты по умолчанию (пользователь: «не читаемо») — страница
# включает их переключателем «Этапы на графиках» (static/.../js/stage_toggle.js).
# Все элементы этапов помечены: shapes/annotations — name="stage-*", трассы — meta="stage".
STAGES_VISIBLE_DEFAULT = False
STAGE_BAND_NAME = "stage-band"
STAGE_SWITCH_NAME = "stage-switch"
STAGE_LABEL_NAME = "stage-label"
STAGE_TRACE_META = "stage"


def _stage_color(stage: int) -> str:
    """Цвет этапа: этап 0 — синий (исходная), дальше по палитре серий."""
    return SERIES_PALETTE[stage % len(SERIES_PALETTE)]


def _add_stage_overlay_t(fig: go.Figure, overlay: dict | None, t_range=None, labels: bool = True) -> None:
    """Полосы этапов (k ≥ 1) по времени + линии переключений (откат — сплошные, накат — пунктир).

    t_range — окно графика (фазы): полосы обрезаются, события вне окна не рисуются,
    чтобы не растягивать ось.
    """
    if not overlay:
        return
    segments = overlay.get("segments", [])
    lo, hi = t_range if t_range is not None else (-math.inf, math.inf)
    span_lo = max(lo, segments[0]["t0"]) if segments else lo
    span_hi = min(hi, segments[-1]["t1"]) if segments else hi
    min_label_width = STAGE_LABEL_MIN_FRACTION * max(span_hi - span_lo, 0.0)
    for seg in segments:
        if seg["stage"] == 0:
            continue
        x0, x1 = max(seg["t0"], lo), min(seg["t1"], hi)
        if x1 <= x0:
            continue
        color = _stage_color(seg["stage"])
        kwargs = {}
        # Узкие полосы (частые переключения на быстром откате) без подписи — иначе подписи
        # соседних этапов налезают; этап виден по цвету и подписан на широкой полосе наката.
        if labels and x1 - x0 >= min_label_width:
            kwargs = _stage_label_kwargs(seg["stage"], color)
        fig.add_vrect(x0=x0, x1=x1, fillcolor=_hex_to_rgba(color, STAGE_BAND_ALPHA),
                      line_width=0, layer="below", name=STAGE_BAND_NAME,
                      visible=STAGES_VISIBLE_DEFAULT, **kwargs)
    for event in overlay.get("events", []):
        if not lo <= event["t"] <= hi:
            continue
        fig.add_vline(
            x=float(event["t"]),
            line=dict(color=_SWITCH_COLOR, width=1.1,
                      dash="solid" if event["direction"] == "forward" else "dot"),
            name=STAGE_SWITCH_NAME, visible=STAGES_VISIBLE_DEFAULT,
        )


def _stage_label_kwargs(stage: int, color: str) -> dict:
    return dict(
        annotation_text=f"этап {stage}", annotation_position="top left",
        annotation_font=dict(color=color, size=10, family=FONT_FAMILY_MONO),
        annotation=dict(name=STAGE_LABEL_NAME, visible=STAGES_VISIBLE_DEFAULT),
    )


def _add_stage_overlay_x(fig: go.Figure, overlay: dict | None) -> None:
    """Этапы как функция положения: полосы [x_k, x_{k+1}) + точки переключений на v(x)."""
    if not overlay:
        return
    bands = overlay.get("x_bands", [])
    x_span = abs(bands[-1]["x1"]) if bands else 0.0   # окно v(x) — от старта до x_max
    for band in bands:
        color = _stage_color(band["stage"])
        kwargs = {}
        if band["x1"] - band["x0"] >= STAGE_LABEL_MIN_FRACTION * x_span:
            kwargs = _stage_label_kwargs(band["stage"], color)
        fig.add_vrect(
            x0=band["x0"], x1=band["x1"], fillcolor=_hex_to_rgba(color, STAGE_BAND_ALPHA),
            line_width=0, layer="below", name=STAGE_BAND_NAME,
            visible=STAGES_VISIBLE_DEFAULT, **kwargs,
        )
    events = overlay.get("events", [])
    if events:
        fig.add_trace(go.Scatter(
            x=[e["x"] for e in events], y=[e["v"] for e in events],
            mode="markers", name="переключения",
            marker=dict(color=_SWITCH_COLOR, size=9, symbol="diamond", line=dict(color="white", width=1.5)),
            text=[f"этап {e['stage_from']}→{e['stage_to']}"
                  f" ({'откат' if e['direction'] == 'forward' else 'накат'})" for e in events],
            hoverinfo="text+x+y",
            meta=STAGE_TRACE_META, visible=STAGES_VISIBLE_DEFAULT,
        ))


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
            font=dict(family=FONT_FAMILY_UI, size=12),
        ),
        margin=dict(l=60, r=40, t=80, b=55),
        plot_bgcolor="white",
    )
    fig.update_xaxes(
        title=dict(text=x_title, font=dict(family=FONT_FAMILY_UI, size=12)),
        gridcolor="#E1E5EC",
        zerolinecolor="#C5CDD8",
        tickfont=dict(family=FONT_FAMILY_MONO, size=10),
    )
    fig.update_yaxes(
        title=dict(text=y_title, font=dict(family=FONT_FAMILY_UI, size=12)),
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
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_UI, size=12, color=RB_BLUE)),
            range=left_range,
            zeroline=True,
            zerolinewidth=1.5,
            zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10, color=RB_BLUE),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с²", font=dict(family=FONT_FAMILY_UI, size=12, color=RB_ACCENT)),
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
            font=dict(family=FONT_FAMILY_UI, size=12),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_UI, size=12)),
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
    overlay: dict | None = None,
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
    t_range = (float(t[0]), float(t[-1]))

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
    _add_stage_overlay_t(fig, overlay, t_range)
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
    _add_stage_overlay_t(fig, overlay, t_range)
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
        _add_stage_overlay_t(fig, overlay, t_range)
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

    _add_stage_overlay_t(fig, overlay, t_range)
    files[f"chart_forces_secondary_{phase_name}"] = _save_fragment(
        _apply_layout(fig, f"Распределение сил от времени — фаза {phase_label}", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary_{phase_name}.html",
    )


def _save_annotated_x_t(result, output_dir: Path, prefix: str, overlay: dict | None = None) -> str:
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
    _add_stage_overlay_t(fig, overlay)

    return _save_fragment(
        _apply_layout(fig, "Перемещение откатных частей x(t)", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t_annotated.html",
    )


def _save_energy_balance(result, output_dir: Path, prefix: str, overlay: dict | None = None) -> str:
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
    _add_stage_overlay_t(fig, overlay, labels=False)

    residual_pct = result.energy_residual_pct
    title = "Энергобаланс"
    if residual_pct is not None:
        title = f"Энергобаланс — макс. невязка {residual_pct:.2f}%"

    return _save_fragment(
        _apply_layout(fig, title, "t, c", "E, Дж"),
        output_dir,
        f"{prefix}_energy.html",
    )


# Цвета тормозов на |F|(|v|): не синий (сумма) и не цвета этапов 1–2, чтобы серии не путались.
_BRAKE_LINE_COLORS = (RB_GREEN, RB_AMBER, RB_PURPLE, RB_PINK, RB_GRAY)


def _masked(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Значения вне маски → NaN: Plotly рвёт линию, куски фаз/этапов не соединяются."""
    return np.where(mask, values, np.nan)


def _save_fmag_v(result, output_dir: Path, prefix: str, stage_overlay: dict | None,
                 fv_reference: dict | None) -> str:
    """Сила торможения от скорости |F|(|v|) — комбинированный график.

    Толстые линии — ПОСЧИТАННОЕ (шаги интегрирования): сплошная — откат, пунктир —
    накат. Тонкие пунктирные — характеристика конфигурации тормозов из модели
    (справка: какую кривую давал тормоз/этап). У обычного расчёта — сумма + каждый
    тормоз; у итерационного — сумма цветом этапа. Если расчёт отходит от
    характеристики > 1 % — пометка и точки ×.
    """
    v = np.abs(np.asarray(result.v, dtype=float))
    total = np.abs(np.asarray(result.f_magnetic, dtype=float)) / 1e3
    n = len(v)
    each = result.f_magnetic_each if result.f_magnetic_each.ndim == 2 else np.zeros((n, 0))

    if result.recoil_end_time is not None:
        # (маска, стиль линии): откат — сплошная, накат — пунктир.
        phases = [(result.t <= result.recoil_end_time, "solid"),
                  (result.t >= result.recoil_end_time, "dash")]
    else:
        phases = [(np.ones(n, dtype=bool), "solid")]

    stage_index = None
    if stage_overlay is not None and len(stage_overlay.get("stage_index", [])) == n:
        stage_index = np.asarray(stage_overlay["stage_index"], dtype=int)
    hover = "|v| = %{x:.4g} м/с<br>|F| = %{y:.4g} кН<extra>%{fullData.name}</extra>"

    fig = go.Figure()

    # Фон: характеристики (модель).
    for curve in (fv_reference or {}).get("curves", []):
        staged = stage_index is not None
        color = _stage_color(curve["stage"]) if staged else RB_BLUE
        fig.add_trace(go.Scatter(
            x=curve["v"], y=np.asarray(curve["f"]) / 1e3, mode="lines",
            name=(f"характеристика этапа {curve['stage']} (модель)" if staged
                  else "характеристика Σ (модель)"),
            line=dict(color=_hex_to_rgba(color, 0.6), width=1.4, dash="dot"),
            hovertemplate=hover,
        ))

    # Главное: посчитанное.
    if stage_index is not None:
        for stage in sorted(set(stage_index.tolist())):
            color = _stage_color(stage)
            in_legend = False   # в легенде — один элемент на этап (обе фазы в одной группе)
            for mask, dash in phases:
                sel = mask & (stage_index == stage)
                if not sel.any():
                    continue
                fig.add_trace(go.Scatter(
                    x=_masked(v, sel), y=_masked(total, sel), mode="lines",
                    name=f"Σ тормозов · этап {stage}", legendgroup=f"stage{stage}",
                    showlegend=not in_legend,
                    line=dict(color=color, width=LINE_WIDTH_PRIMARY, dash=dash),
                    hovertemplate=hover,
                ))
                in_legend = True
    else:
        if each.shape[1] > 1:
            for j in range(each.shape[1]):
                color = _BRAKE_LINE_COLORS[j % len(_BRAKE_LINE_COLORS)]
                force = np.abs(each[:, j]) / 1e3
                for i, (mask, dash) in enumerate(phases):
                    fig.add_trace(go.Scatter(
                        x=_masked(v, mask), y=_masked(force, mask), mode="lines",
                        name=f"тормоз {j + 1}", legendgroup=f"brake{j}", showlegend=i == 0,
                        line=dict(color=color, width=LINE_WIDTH_DASHED, dash=dash),
                        hovertemplate=hover,
                    ))
        for i, (mask, dash) in enumerate(phases):
            fig.add_trace(go.Scatter(
                x=_masked(v, mask), y=_masked(total, mask), mode="lines",
                name="Σ тормозов", legendgroup="total", showlegend=i == 0,
                line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY, dash=dash),
                hovertemplate=hover,
            ))

    title = "Сила торможения от скорости |F|(|v|)"
    deviation = (fv_reference or {}).get("deviation") or {}
    rows = [r for r in deviation.get("rows", []) if 0 <= r < n]
    if deviation.get("max_rel", 0.0) > 0.01 and rows:
        fig.add_trace(go.Scatter(
            x=v[rows], y=total[rows], mode="markers", name="расчёт ≠ характеристика (> 1 %)",
            marker=dict(color=RB_ACCENT, size=7, symbol="x"),
            hovertemplate=hover,
        ))
        title += f" · ⚠ расчёт отходит от характеристики до {deviation['max_rel'] * 100:.1f} %"

    _apply_layout(fig, title, "|v|, м/с", "|F|, кН")
    style_note = ("толстые — расчёт (сплошная — откат, пунктир — накат) · "
                  "тонкий пунктир — характеристика тормоза по модели")
    if len(phases) == 1:
        style_note = "толстая — расчёт · тонкий пунктир — характеристика тормоза по модели"
    # Пояснение — внутри поля справа внизу: кривые растут вверх, угол пуст (над полем — заголовок).
    fig.add_annotation(xref="paper", yref="paper", x=0.99, y=0.05, xanchor="right", yanchor="bottom",
                       text=style_note, showarrow=False, bgcolor="rgba(255,255,255,0.85)",
                       font=dict(color="#5A6A7F", size=11, family=FONT_FAMILY_UI))
    # Кривые растут в правый верхний угол — легенду в левый верхний.
    fig.update_layout(legend=dict(x=0.01, xanchor="left", y=0.99, yanchor="top"))
    return _save_fragment(fig, output_dir, f"{prefix}_fmag_v.html")


def save_interactive_charts(
    result,
    output_dir: str | Path,
    prefix: str = "run",
    stage_overlay: dict | None = None,
    fv_reference: dict | None = None,
) -> dict[str, str]:
    """Все графики страницы результата (HTML-фрагменты). `stage_overlay` — этапы
    итерационного расчёта: полосы и линии переключений на графиках по времени,
    полосы по x на v(x), сумма F(v) по этапам. `fv_reference` — характеристики
    тормозов и расхождение с ними (`services/fv_reference.build_fv_reference`)
    для графика «Сила торможения от скорости»."""
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
    _add_stage_overlay_t(fig, stage_overlay)
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
    _add_stage_overlay_t(fig, stage_overlay)
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
    _add_stage_overlay_x(fig, stage_overlay)
    files["chart_v_x"] = _save_fragment(
        _apply_layout(fig, "Скорость от перемещения", "x, м", "v, м/с"),
        output_dir,
        f"{prefix}_v_x.html",
    )

    # === Сила торможения от скорости: посчитанное + характеристика тормозов (модель) ===
    files["chart_fmag_v"] = _save_fmag_v(result, output_dir, prefix, stage_overlay, fv_reference)

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
    _add_stage_overlay_t(fig, stage_overlay)
    files["chart_forces_secondary"] = _save_fragment(
        _apply_layout(fig, "Распределение сил от времени", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary.html",
    )

    _save_phase_charts(files, result, output_dir, prefix, "recoil", recoil_mask, stage_overlay)
    _save_phase_charts(files, result, output_dir, prefix, "return", return_mask, stage_overlay)

    # Дополнительные графики для нового дизайна страницы результата.
    # Если что-то упадёт — расчёт остаётся валидным, базовые графики уже сохранены.
    try:
        files["chart_x_t_annotated"] = _save_annotated_x_t(result, output_dir, prefix, stage_overlay)
    except Exception:
        pass
    try:
        energy_path = _save_energy_balance(result, output_dir, prefix, stage_overlay)
        if energy_path:
            files["chart_energy"] = energy_path
    except Exception:
        pass

    return files

# ============================================================================
# СРЕЗ 3c: график F(v) для детальной страницы тормоза в каталоге
# ============================================================================

def make_design_fv_fragment(
    ideal_v, ideal_f,
    actual_v=None, actual_f=None,
    sigma_f_max: float | None = None,
    title: str = "Характеристика F(v): цель и реальный тормоз",
) -> str:
    """Синтезированная (идеальная) F(v) + РЕАЛЬНАЯ F(v) подобранного тормоза.

    Идеал (цель синтеза) — плоская полка до ΣF_max для минимума отката; реальный
    вихретоковый тормоз так не может (сила растёт с v и плавно насыщается), поэтому
    показываем и цель (пунктир), и что реально даёт подобранный тормоз (сплошная).
    """
    fig = go.Figure()

    if actual_v is not None and actual_f is not None and len(actual_v):
        fig.add_trace(go.Scatter(
            x=list(actual_v), y=list(actual_f), mode="lines",
            name="реальный тормоз F(v)",
            line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY),
            fill="tozeroy", fillcolor=RB_BLUE_FILL,
        ))

    if ideal_v and ideal_f:
        fig.add_trace(go.Scatter(
            x=list(ideal_v), y=list(ideal_f), mode="lines+markers",
            name="идеал (цель синтеза)",
            line=dict(color=RB_GRAY, width=2.0, dash="dash"),
            marker=dict(color=RB_GRAY, size=6),
        ))

    if sigma_f_max:
        fig.add_hline(
            y=float(sigma_f_max),
            line=dict(color=RB_ACCENT, width=1.2, dash="dot"),
            annotation_text="ΣF_max", annotation_position="top left",
            annotation_font=dict(color=RB_ACCENT, size=10, family=FONT_FAMILY_MONO),
        )

    _apply_layout(fig, title, "v, м/с", "F, Н")
    return _to_html_fragment(fig, height="480px")


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


def make_pareto_fragment(
    candidates: list[dict],
    title: str = "Кандидаты: откат ↔ робастность",
) -> str:
    """Парето-плоскость кандидатов мультистарта обратного проектирования.

    Ось X — достигнутый откат x_max, м (минимизируем → меньше = лучше).
    Ось Y — R (робастность, меньше = устойчивее к разбросу параметров).
    Оба «меньше — лучше», поэтому Парето-фронт — левый-нижний угол.
    Размер маркера — запас до ΣF_max в σ (крупнее = безопаснее). Цвет: под всеми
    пределами — синие, с превышением — серые-полые, выбранный — акцентная звезда.

    candidates: list of dicts {label, feasible, R, x_max, overshoot, sigma_f_margin, is_best}.
    """
    pts = [c for c in (candidates or [])
           if c.get("R") is not None and c.get("x_max") is not None
           and math.isfinite(c["R"]) and math.isfinite(c["x_max"])]
    if len(pts) < 2:
        return ""

    def _size(margin) -> float:
        if margin is None or not math.isfinite(margin):
            return 20.0  # ∞ запас — самый крупный
        return float(min(22.0, max(8.0, 8.0 + 1.4 * margin)))

    def _hover(c) -> str:
        m = c.get("sigma_f_margin")
        m_s = "∞" if (m is None or not math.isfinite(m)) else f"{m:.1f}σ"
        ov = c.get("overshoot")
        ov_s = "0%" if (ov is None or ov <= 0) else f"+{ov * 100:.1f}%"
        return (f"<b>{c['label']}</b><br>откат x_max = {c['x_max']:.4g} м"
                f"<br>R = {c['R']:.4g}"
                f"<br>превышение пределов = {ov_s}"
                f"<br>запас ΣF = {m_s}"
                f"<br>{'под пределами' if c.get('feasible') else 'превышает предел'}")

    feasible = [c for c in pts if c.get("feasible") and not c.get("is_best")]
    infeasible = [c for c in pts if not c.get("feasible") and not c.get("is_best")]
    best = next((c for c in pts if c.get("is_best")), None)

    fig = go.Figure()

    if infeasible:
        fig.add_trace(go.Scatter(
            x=[c["x_max"] for c in infeasible], y=[c["R"] for c in infeasible],
            mode="markers", name="превышает предел",
            marker=dict(color=RB_GRAY, size=10, symbol="circle-open", line=dict(width=2)),
            text=[_hover(c) for c in infeasible], hoverinfo="text",
        ))

    if feasible:
        fig.add_trace(go.Scatter(
            x=[c["x_max"] for c in feasible], y=[c["R"] for c in feasible],
            mode="markers", name="под пределами",
            marker=dict(color=RB_BLUE, size=[_size(c.get("sigma_f_margin")) for c in feasible],
                        opacity=0.8, line=dict(color="white", width=1.5)),
            text=[_hover(c) for c in feasible], hoverinfo="text",
        ))

    if best is not None:
        fig.add_trace(go.Scatter(
            x=[best["x_max"]], y=[best["R"]],
            mode="markers+text", name="выбран (min R)",
            marker=dict(color=RB_ACCENT, size=_size(best.get("sigma_f_margin")) + 6,
                        symbol="star", line=dict(color="white", width=1.5)),
            text=[f"  {best['label']}"], textposition="middle right",
            textfont=dict(color=RB_ACCENT, size=12, family=FONT_FAMILY_MONO),
            hovertext=[_hover(best)], hoverinfo="text",
        ))

    _apply_layout(fig, title, "откат x_max, м (меньше = лучше)", "R — робастность (меньше = лучше)")
    return _to_html_fragment(fig, height="440px")


# ============================================================================
# Итерационный расчёт: графики «на текущий момент» (Срез 12)
# ============================================================================

def _preview_indices(n: int, keep: list[int], max_points: int) -> np.ndarray:
    """Прореживание до max_points с обязательными узлами (переключения, последняя точка)."""
    if n <= max_points:
        return np.arange(n)
    base = np.linspace(0, n - 1, max_points).round().astype(int)
    extra = np.array([i for i in keep if 0 <= i < n], dtype=int)
    return np.unique(np.concatenate([base, extra, [n - 1]]))


def make_iterative_preview_figures(
    result,
    overlay: dict | None,
    max_points: int = 3000,
) -> dict[str, dict]:
    """Графики итерационного расчёта до текущего узла — JSON фигур Plotly.

    Страница обновляет их после каждого действия без перезагрузки
    (`Plotly.react`), поэтому возвращаются фигуры, а не HTML-фрагменты.
    x(t), v(t), F_торм(t) (сумма + по тормозам), v(x); этапы — те же полосы и
    линии переключений, что на странице итогового расчёта. Прореживание до
    `max_points` с сохранением узлов переключений и последней точки; текущий
    узел — акцентная точка.
    """
    import json

    n = len(result.t)
    events = (overlay or {}).get("events", [])
    keep = [r for e in events if e.get("row") is not None for r in (e["row"] - 1, e["row"])]
    idx = _preview_indices(n, keep, max_points)
    t = result.t[idx]
    x = result.x[idx]
    v = result.v[idx]

    def _current(fig: go.Figure, xv: float, yv: float) -> None:
        fig.add_trace(go.Scatter(
            x=[xv], y=[yv], mode="markers", name="текущий узел", showlegend=False,
            marker=dict(color=RB_ACCENT, size=10, line=dict(color="white", width=2)),
            hoverinfo="skip",
        ))

    def _finish(fig: go.Figure, title: str, x_title: str, y_title: str, hovermode: str,
                legend: bool = False) -> dict:
        _apply_layout(fig, title, x_title, y_title)
        # Легенда — только где несколько серий (F(t) по тормозам): у одиночной кривой
        # она закрывает подписи этапов и текущий узел в правом верхнем углу.
        fig.update_layout(height=320, margin=dict(l=60, r=24, t=48, b=48), hovermode=hovermode,
                          uirevision="iterative", showlegend=legend)
        return json.loads(fig.to_json())

    figures: dict[str, dict] = {}

    fig = go.Figure(go.Scatter(x=t, y=x, mode="lines", name="x(t)",
                               line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY)))
    _current(fig, float(result.t[-1]), float(result.x[-1]))
    _add_stage_overlay_t(fig, overlay)
    _add_recoil_vline(fig, result)
    figures["x_t"] = _finish(fig, "Перемещение x(t)", "t, с", "x, м", "x unified")

    fig = go.Figure(go.Scatter(x=t, y=v, mode="lines", name="v(t)",
                               line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY)))
    _current(fig, float(result.t[-1]), float(result.v[-1]))
    _add_stage_overlay_t(fig, overlay, labels=False)
    _add_recoil_vline(fig, result)
    figures["v_t"] = _finish(fig, "Скорость v(t)", "t, с", "v, м/с", "x unified")

    fig = go.Figure()
    each = result.f_magnetic_each[idx]
    several = each.ndim == 2 and each.shape[1] > 1
    if several:
        for k in range(each.shape[1]):
            fig.add_trace(go.Scatter(
                x=t, y=each[:, k], mode="lines", name=f"тормоз {k + 1}",
                line=dict(color=_series_color(k + 1), width=LINE_WIDTH_DASHED),
            ))
    fig.add_trace(go.Scatter(x=t, y=result.f_magnetic[idx], mode="lines", name="Σ тормозов",
                             line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY)))
    _current(fig, float(result.t[-1]), float(result.f_magnetic[-1]))
    _add_stage_overlay_t(fig, overlay, labels=False)
    figures["f_t"] = _finish(fig, "Сила торможения F(t)", "t, с", "F, Н", "x unified", legend=several)

    fig = go.Figure(go.Scatter(x=x, y=v, mode="lines", name="v(x)",
                               line=dict(color=RB_BLUE, width=LINE_WIDTH_PRIMARY)))
    _add_stage_overlay_x(fig, overlay)
    _current(fig, float(result.x[-1]), float(result.v[-1]))
    figures["v_x"] = _finish(fig, "Фазовая траектория v(x)", "x, м", "v, м/с", "closest")

    return figures


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
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_UI, size=12)),
            range=left_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с² (dash)", font=dict(family=FONT_FAMILY_UI, size=12)),
            overlaying="y", side="right",
            range=right_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        legend=dict(
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC", borderwidth=1,
            font=dict(family=FONT_FAMILY_UI, size=11),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_UI, size=12)),
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
            title=dict(text="v, м/с", font=dict(family=FONT_FAMILY_UI, size=12)),
            range=left_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            gridcolor="#E1E5EC",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        yaxis2=dict(
            title=dict(text="a, м/с² (dash)", font=dict(family=FONT_FAMILY_UI, size=12)),
            overlaying="y", side="right", range=right_range,
            zeroline=True, zerolinewidth=1.5, zerolinecolor="#C5CDD8",
            tickfont=dict(family=FONT_FAMILY_MONO, size=10),
        ),
        legend=dict(
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#E1E5EC", borderwidth=1,
            font=dict(family=FONT_FAMILY_UI, size=11),
        ),
        margin=dict(l=60, r=60, t=80, b=55),
    )
    fig.update_xaxes(
        title=dict(text="t, c", font=dict(family=FONT_FAMILY_UI, size=12)),
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


# ============================================================================
# СРЕЗ 8a: 3D-визуализация геометрии параметрического тормоза
#
# Цилиндрическая компоновка: внутри — медная шина-труба (неподвижна), снаружи
# — кольцевые магниты, движутся вдоль оси отката. Параметрическая модель
# Тулупова исходно плоская, мы её визуализируем как цилиндр: ym трактуется как
# дуговая длина магнита-кольца, отсюда радиус шины R = ym / (2π).
# ============================================================================

# Медный цвет шины (PMS-подобный медный, нейтральный к синей/розовой палитре).
_BUS_COPPER_COLOR = "#B87333"

# Цвета магнитов — чередуем для наглядности (полярность для модели не важна:
# в формуле сила пропорциональна B², знак не входит).
_MAGNET_COLORS = (RB_BLUE, RB_ACCENT)

# Число сегментов окружности при триангуляции трубы. 48 — компромисс между
# гладкостью и весом HTML-фрагмента.
_CYL_SEGMENTS = 48


def _cylinder_mesh3d(
    x0: float, x1: float,
    r_inner: float, r_outer: float,
    color: str, opacity: float, name: str,
    n_segments: int = _CYL_SEGMENTS,
) -> go.Mesh3d:
    """Полая труба вдоль оси X как Mesh3d (4 поверхности: внешн., внутр., 2 торца).

    Если r_inner ≤ 0 — превращается в сплошной цилиндр без отверстия (торцы
    схлопываются, но Mesh3d остаётся валидным).
    """
    n = max(int(n_segments), 6)

    cos = [math.cos(2 * math.pi * idx / n) for idx in range(n)]
    sin = [math.sin(2 * math.pi * idx / n) for idx in range(n)]

    # Точки (4 кольца по n штук = 4n всего):
    #   0..n-1       : back  · outer  (x=x0, r=r_outer)
    #   n..2n-1      : front · outer  (x=x1, r=r_outer)
    #   2n..3n-1     : back  · inner  (x=x0, r=r_inner)
    #   3n..4n-1     : front · inner  (x=x1, r=r_inner)
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    for x_val, r in ((x0, r_outer), (x1, r_outer), (x0, r_inner), (x1, r_inner)):
        for idx in range(n):
            xs.append(x_val)
            ys.append(r * cos[idx])
            zs.append(r * sin[idx])

    i_idx: list[int] = []
    j_idx: list[int] = []
    k_idx: list[int] = []

    # Внешняя поверхность: пары точек (i, next) на back/front
    for idx in range(n):
        nxt = (idx + 1) % n
        # Треугольник 1: back[i], front[i], front[next]
        i_idx.append(idx);           j_idx.append(idx + n);      k_idx.append(nxt + n)
        # Треугольник 2: back[i], front[next], back[next]
        i_idx.append(idx);           j_idx.append(nxt + n);      k_idx.append(nxt)

    # Внутренняя поверхность — обратная ориентация (нормаль внутрь трубы)
    for idx in range(n):
        nxt = (idx + 1) % n
        i_idx.append(2 * n + idx);   j_idx.append(3 * n + nxt);  k_idx.append(3 * n + idx)
        i_idx.append(2 * n + idx);   j_idx.append(2 * n + nxt);  k_idx.append(3 * n + nxt)

    # Передний торец (x=x1): кольцо между front · outer и front · inner
    for idx in range(n):
        nxt = (idx + 1) % n
        i_idx.append(idx + n);       j_idx.append(idx + 3 * n);  k_idx.append(nxt + n)
        i_idx.append(nxt + n);       j_idx.append(idx + 3 * n);  k_idx.append(nxt + 3 * n)

    # Задний торец (x=x0): обратная ориентация
    for idx in range(n):
        nxt = (idx + 1) % n
        i_idx.append(idx);           j_idx.append(nxt);          k_idx.append(idx + 2 * n)
        i_idx.append(nxt);           j_idx.append(nxt + 2 * n);  k_idx.append(idx + 2 * n)

    return go.Mesh3d(
        x=xs, y=ys, z=zs,
        i=i_idx, j=j_idx, k=k_idx,
        color=color, opacity=opacity,
        name=name,
        flatshading=True,
        hoverinfo="name",
    )


def build_brake_geometry_3d(brake) -> str | None:
    """3D-визуализация цилиндрической геометрии параметрического тормоза.

    Принимает `MagneticBrakeConfig` или `BrakeCatalog`.

    Возвращает HTML-фрагмент Plotly (без plotly.js) либо None, если тормоз
    curve-типа или не заполнены нужные размеры.

    Координаты сцены:
      X — ось отката (длина тормоза);
      Y, Z — плоскость сечения (магниты — кольца вокруг шины).
    """
    if getattr(brake, "model_type", None) != "parametric":
        return None

    required = ("n", "xm", "ym", "dh1", "dh2", "dm")
    raw = {key: getattr(brake, key, None) for key in required}
    if any(v is None for v in raw.values()):
        return None

    try:
        n = int(raw["n"])
        xm = float(raw["xm"])
        ym = float(raw["ym"])
        dh1 = float(raw["dh1"])
        dh2 = float(raw["dh2"])
        dm = float(raw["dm"])
    except (TypeError, ValueError):
        return None

    if n < 1 or xm <= 0 or ym <= 0:
        return None

    # --- Радиальные размеры ---
    # ym — дуговая длина кольцевого магнита (периметр окружности),
    # отсюда срединный радиус шины R = ym / (2π).
    r_bus_mid = ym / (2.0 * math.pi)

    # Толщина стенки шины — визуальный дефолт (в модели нет). Пропорционально
    # радиусу: ~10%, но не меньше 2 мм.
    t_bus = max(r_bus_mid * 0.10, 0.002)
    r_bus_inner = max(r_bus_mid - t_bus / 2.0, t_bus * 0.1)
    r_bus_outer = r_bus_mid + t_bus / 2.0

    # Зазор шина — магнит. Визуальный дефолт.
    gap = max(r_bus_mid * 0.04, 0.0005)

    # Толщина магнита (радиальная) — визуальный дефолт. Берём такую, чтобы
    # магнит выглядел заметно толще шины, но не громоздко.
    t_magnet = max(r_bus_mid * 0.25, 0.003)

    r_magnet_inner = r_bus_outer + gap
    r_magnet_outer = r_magnet_inner + t_magnet

    # --- Продольные размеры ---
    # Общая длина блока магнитов = n·xm + (n-1)·dm.
    l_magnets = n * xm + max(n - 1, 0) * dm

    # Шина выступает за крайние магниты на dh1 (с начала) и dh2 (с конца).
    x_bus_0 = -max(dh1, 0.0)
    x_bus_1 = l_magnets + max(dh2, 0.0)

    traces: list[go.Mesh3d] = []

    # Шина (медь) — внутренний цилиндр
    traces.append(_cylinder_mesh3d(
        x_bus_0, x_bus_1,
        r_bus_inner, r_bus_outer,
        color=_BUS_COPPER_COLOR, opacity=0.95,
        name="Шина (медь)",
    ))

    # n магнитов-колец, чередующимся цветом для наглядности
    for idx in range(n):
        x0 = idx * (xm + dm)
        x1 = x0 + xm
        traces.append(_cylinder_mesh3d(
            x0, x1,
            r_magnet_inner, r_magnet_outer,
            color=_MAGNET_COLORS[idx % len(_MAGNET_COLORS)],
            opacity=0.92,
            name=f"Магнит {idx + 1}",
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(
            text=(
                f"Геометрия тормоза · магнитов: {n} · "
                f"L_магн={l_magnets * 1000:.0f} мм · R_шины={r_bus_mid * 1000:.1f} мм"
            ),
            font=dict(family=FONT_FAMILY_UI, size=14, color="#1B2430"),
        ),
        template="plotly_white",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        margin=dict(l=0, r=0, t=50, b=0),
        scene=dict(
            xaxis=dict(
                title=dict(text="X · ось отката, м",
                           font=dict(family=FONT_FAMILY_UI, size=12)),
                tickfont=dict(family=FONT_FAMILY_MONO, size=10),
                backgroundcolor="rgba(245, 247, 250, 1)",
                gridcolor="#E1E5EC",
                zerolinecolor="#C5CDD8",
            ),
            yaxis=dict(
                title=dict(text="Y, м",
                           font=dict(family=FONT_FAMILY_UI, size=12)),
                tickfont=dict(family=FONT_FAMILY_MONO, size=10),
                backgroundcolor="rgba(245, 247, 250, 1)",
                gridcolor="#E1E5EC",
                zerolinecolor="#C5CDD8",
            ),
            zaxis=dict(
                title=dict(text="Z, м",
                           font=dict(family=FONT_FAMILY_UI, size=12)),
                tickfont=dict(family=FONT_FAMILY_MONO, size=10),
                backgroundcolor="rgba(245, 247, 250, 1)",
                gridcolor="#E1E5EC",
                zerolinecolor="#C5CDD8",
            ),
            aspectmode="data",
            camera=dict(eye=dict(x=1.9, y=1.1, z=0.9)),
        ),
        showlegend=False,
    )

    return pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        default_width="100%",
        default_height="520px",
        validate=True,
    )


# ---------------------------------------------------------------------------
# Осциллограмма страницы результата (редизайн «протокол + осциллограмма»)
# ---------------------------------------------------------------------------

# Цвет = физическая величина (на той же палитре): (линия, подпись оси — темнее, для контраста).
QUANTITY_COLORS = {
    "x": (RB_BLUE, "#2C5FD0"),
    "v": (RB_GREEN, "#047857"),
    "a": (RB_ACCENT, "#9A3F68"),
    "f": (RB_AMBER, "#B45309"),
}
OSC_GRID = "#EEF1F4"
OSC_ZERO = "#D3D9DF"
OSC_MARKER = "#56606B"


def make_oscillogram_figure(data: dict, *, free_fall: bool = False) -> go.Figure:
    """Синхронная осциллограмма: x, v, a, |F| на общей оси t + лента этапов.

    data — `services.result_page.build_oscillogram_data`. Все каналы на ОДНОЙ оси x
    (разные y-домены), hoversubplots='axis' — курсор показывает все каналы в один
    момент времени. Участки цикла (откат/накат) — это диапазон общей оси, а не
    отдельные наборы графиков. Этапы — одна лента под осью, а не полосы на каждом канале.
    """
    rows = [
        ("x_mm", "x, мм", "x", "мм", ".1f"),
        ("v", "v, м/с", "v", "м/с", ".3f"),
        ("a_g", "a, g", "a", "g", ".1f"),
        ("f", f"|F| торм., {data.get('f_unit', 'кН')}", "f", data.get("f_unit", "кН"), ".1f"),
    ]
    has_ribbon = bool(data.get("segments")) and len(data["segments"]) > 1
    heights = [0.235] * 4 + ([0.06] if has_ribbon else [])
    total = sum(heights)
    heights = [h / total for h in heights]
    gap = 0.014
    domains, edge = [], 1.0
    for h in heights:
        domains.append([max(edge - h + gap / 2, 0.0), edge - gap / 2])
        edge -= h

    tick_font = dict(family=FONT_FAMILY_MONO, size=10, color="#5A6A7F")
    fig = go.Figure()
    for i, (key, name, q, unit, fmt) in enumerate(rows):
        line_color, text_color = QUANTITY_COLORS[q]
        fig.add_trace(go.Scatter(
            x=data["t"], y=data[key], mode="lines", name=name,
            xaxis="x", yaxis="y" if i == 0 else f"y{i + 1}",
            line=dict(color=line_color, width=2),
            hovertemplate=f"%{{y:{fmt}}} {unit}<extra></extra>",
        ))
        axis = "yaxis" if i == 0 else f"yaxis{i + 1}"
        fig.update_layout({axis: dict(
            domain=domains[i],
            title=dict(text=name, font=dict(family=FONT_FAMILY_UI, size=12, color=text_color)),
            tickfont=tick_font, gridcolor=OSC_GRID, zerolinecolor=OSC_ZERO, fixedrange=True,
        )})

    shapes, annotations = [], []
    anchor = "y4"
    if has_ribbon:
        anchor = "y5"
        fig.update_layout(yaxis5=dict(domain=domains[4], range=[0, 1], visible=False, fixedrange=True))
        span = max(data["t_end"] - data["t0"], 1e-12)
        for seg in data["segments"]:
            color = _stage_color(seg["stage"])
            shapes.append(dict(type="rect", xref="x", yref="y5", x0=seg["t0"], x1=seg["t1"], y0=0, y1=1,
                               fillcolor=_hex_to_rgba(color, 0.22 if seg["stage"] == 0 else 0.45),
                               line=dict(width=0), layer="below"))
            if seg["t1"] - seg["t0"] >= 0.05 * span:
                annotations.append(dict(xref="x", yref="y5", x=(seg["t0"] + seg["t1"]) / 2, y=0.5,
                                        text=f"этап {seg['stage']}", showarrow=False,
                                        font=dict(family=FONT_FAMILY_UI, size=11, color="#1B2430")))

    if data.get("t_turn") is not None and not free_fall:
        shapes.append(dict(type="line", xref="x", yref="paper", x0=data["t_turn"], x1=data["t_turn"],
                           y0=0, y1=1, line=dict(color=OSC_MARKER, width=1, dash="dot")))
        annotations.append(dict(xref="x", yref="paper", x=data["t_turn"], y=1, yanchor="bottom",
                                text="разворот", showarrow=False,
                                font=dict(family=FONT_FAMILY_UI, size=11, color=OSC_MARKER)))

    fig.update_layout(
        template="plotly_white",
        font=dict(family=FONT_FAMILY_UI, size=12, color="#1B2430"),
        margin=dict(l=64, r=16, t=24, b=40),
        showlegend=False,
        paper_bgcolor="white", plot_bgcolor="white",
        hovermode="x", hoversubplots="axis", dragmode="zoom",
        hoverlabel=dict(font=dict(family=FONT_FAMILY_MONO, size=11)),
        xaxis=dict(
            anchor=anchor, title=dict(text="t, с", font=dict(family=FONT_FAMILY_UI, size=12)),
            tickfont=tick_font, gridcolor=OSC_GRID, zeroline=False,
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikecolor="#1B2430", spikedash="solid",
            range=[data["t0"], data["t_end"]],
        ),
        shapes=shapes, annotations=annotations,
        height=640 if has_ribbon else 600,
    )
    return fig

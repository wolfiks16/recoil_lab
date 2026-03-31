from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio


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
        title=title,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            x=0.99,
            y=0.5,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="rgba(0,0,0,0.12)",
            borderwidth=1,
        ),
        margin=dict(l=60, r=60, t=70, b=60),
    )
    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text=y_title)
    return fig


def _make_dual_axis_figure(x, y_left, y_right, title: str) -> go.Figure:
    left_range, right_range = _aligned_zero_ranges(y_left, y_right)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y_left, mode="lines", name="v(t)", yaxis="y1"))
    fig.add_trace(go.Scatter(x=x, y=y_right, mode="lines", name="a(t)", yaxis="y2"))

    fig.update_layout(
        title=title,
        template="plotly_white",
        hovermode="x unified",
        yaxis=dict(
            title="v, м/с",
            range=left_range,
            zeroline=True,
            zerolinewidth=1.5,
        ),
        yaxis2=dict(
            title="a, м/с²",
            overlaying="y",
            side="right",
            range=right_range,
            zeroline=True,
            zerolinewidth=1.5,
        ),
        legend=dict(
            x=0.99,
            y=0.99,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="rgba(0,0,0,0.12)",
            borderwidth=1,
        ),
        margin=dict(l=60, r=60, t=70, b=60),
    )
    fig.update_xaxes(title_text="t, c")
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

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t, y=x, mode="lines", name="x(t)"))
    files[f"chart_x_t_{phase_name}"] = _save_fragment(
        _apply_layout(fig, f"Перемещение от времени — фаза {phase_label}", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t_{phase_name}.html",
    )

    fig = _make_dual_axis_figure(
        t,
        v,
        a,
        f"Скорость и ускорение от времени — фаза {phase_label}",
    )
    files[f"chart_v_a_t_{phase_name}"] = _save_fragment(
        fig,
        output_dir,
        f"{prefix}_v_a_t_{phase_name}.html",
    )

    if phase_name == "recoil":
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=t, y=f_ext, mode="lines", name="Fдв - движущая сила"))
        fig.add_trace(go.Scatter(x=t, y=f_total, mode="lines", name="FΣ - суммарная сила"))
        files[f"chart_forces_main_{phase_name}"] = _save_fragment(
            _apply_layout(fig, f"Движущая и суммарная силы от времени — фаза {phase_label}", "t, c", "F, Н"),
            output_dir,
            f"{prefix}_forces_main_{phase_name}.html",
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t, y=f_angle, mode="lines", name="Fугла"))
    fig.add_trace(go.Scatter(x=t, y=f_spring, mode="lines", name="Fпруж"))
    for j in range(n_brakes):
        fig.add_trace(go.Scatter(x=t, y=f_each[:, j], mode="lines", name=f"Fмаг{j + 1}"))
    fig.add_trace(go.Scatter(x=t, y=f_mag_sum, mode="lines", name="Fмаг_сумм"))

    if phase_name == "return":
        fig.add_trace(go.Scatter(x=t, y=f_total, mode="lines", name="FΣ - суммарная сила"))

    files[f"chart_forces_secondary_{phase_name}"] = _save_fragment(
        _apply_layout(fig, f"Распределение сил от времени — фаза {phase_label}", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary_{phase_name}.html",
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

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.t, y=result.x, mode="lines", name="x(t)"))
    files["chart_x_t"] = _save_fragment(
        _apply_layout(fig, "Перемещение от времени", "t, c", "x, м"),
        output_dir,
        f"{prefix}_x_t.html",
    )

    fig = _make_dual_axis_figure(result.t, result.v, result.a, "Скорость и ускорение от времени")
    files["chart_v_a_t"] = _save_fragment(
        fig,
        output_dir,
        f"{prefix}_v_a_t.html",
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.x, y=result.v, mode="lines", name="v(x)"))
    files["chart_v_x"] = _save_fragment(
        _apply_layout(fig, "Скорость от перемещения", "x, м", "v, м/с"),
        output_dir,
        f"{prefix}_v_x.html",
    )

    fig = go.Figure()
    for j in range(n_brakes):
        fig.add_trace(
            go.Scatter(
                x=result.v,
                y=result.f_magnetic_each[:, j],
                mode="markers",
                name=f"Fмаг{j + 1}(v)",
            )
        )
    fig.add_trace(go.Scatter(x=result.v, y=result.f_magnetic, mode="markers", name="Fмаг_сумм(v)"))
    files["chart_fmag_v"] = _save_fragment(
        _apply_layout(fig, "Магнитные силы от скорости", "v, м/с", "F, Н"),
        output_dir,
        f"{prefix}_fmag_v.html",
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.t, y=result.f_angle, mode="lines", name="Fугла"))
    fig.add_trace(go.Scatter(x=result.t, y=result.f_spring, mode="lines", name="Fпруж"))
    for j in range(n_brakes):
        fig.add_trace(
            go.Scatter(
                x=result.t,
                y=result.f_magnetic_each[:, j],
                mode="lines",
                name=f"Fмаг{j + 1}",
            )
        )
    fig.add_trace(go.Scatter(x=result.t, y=result.f_magnetic, mode="lines", name="Fмаг_сумм"))
    files["chart_forces_secondary"] = _save_fragment(
        _apply_layout(fig, "Распределение сил от времени", "t, c", "F, Н"),
        output_dir,
        f"{prefix}_forces_secondary.html",
    )

    _save_phase_charts(files, result, output_dir, prefix, "recoil", recoil_mask)
    _save_phase_charts(files, result, output_dir, prefix, "return", return_mask)

    return files
"""KPI-карточки для страницы результата расчёта (`run_detail_v2`).

Группированные карточки + парные min/max + диапазонное форматирование.
"""

from __future__ import annotations

from ..models import CalculationRun


def build_kpi_groups(run: CalculationRun, snapshot_parts: dict) -> list[dict]:
    """Группированные KPI-карточки для страницы результата.

    Каждая группа: {key, label, cards}
    Каждая карточка: {label, value, unit, hint, status, accent, mono?}
        status: 'ok' | 'warn' | 'danger' | 'neutral'
        accent: 'blue' | 'red' | 'green' | 'amber' | 'purple' | 'gray'
    """
    eng = snapshot_parts.get("engineering_metrics") or {}
    chars = snapshot_parts.get("characteristic_points") or {}
    phase_recoil = (snapshot_parts.get("phase_analysis") or {}).get("recoil") or {}
    phase_return = (snapshot_parts.get("phase_analysis") or {}).get("return") or {}

    groups: list[dict] = []

    # === ГРУППА 1: ОБЗОР ===
    overview: list[dict] = []

    if run.x_max is not None:
        time_hint = ""
        if chars.get("x_max"):
            time_hint = f"t = {chars['x_max'].get('time', 0):.3f} с"
        overview.append({
            "label": "Макс. откат",
            "value": f"{run.x_max * 1000:.1f}",
            "unit": "мм",
            "hint": time_hint,
            "status": "ok",
            "accent": "blue",
        })

    a_abs_max = (eng.get("a_range") or {}).get("abs_max")
    if a_abs_max is not None:
        overview.append({
            "label": "Пик ускор.",
            "value": f"{a_abs_max / 9.81:.1f}",
            "unit": "g",
            "hint": f"{a_abs_max:.0f} м/с²",
            "status": "ok",
            "accent": "amber",
        })

    v_abs_max = (eng.get("v_range") or {}).get("abs_max")
    if v_abs_max is not None:
        time_hint = ""
        if chars.get("v_max"):
            time_hint = f"t = {chars['v_max'].get('time', 0):.3f} с"
        overview.append({
            "label": "Макс. скорость",
            "value": f"{v_abs_max:.2f}",
            "unit": "м/с",
            "hint": time_hint,
            "status": "neutral",
            "accent": "green",
        })

    if run.return_end_time is not None:
        overview.append({
            "label": "Время цикла",
            "value": f"{run.return_end_time:.3f}",
            "unit": "с",
            "hint": "откат + накат",
            "status": "ok",
            "accent": "purple",
        })
    elif run.recoil_end_time is not None:
        overview.append({
            "label": "Время отката",
            "value": f"{run.recoil_end_time:.3f}",
            "unit": "с",
            "hint": "до пика",
            "status": "neutral",
            "accent": "purple",
        })

    if phase_recoil.get("available") and phase_recoil.get("duration") is not None:
        overview.append({
            "label": "Длит. отката",
            "value": f"{phase_recoil['duration']:.3f}",
            "unit": "с",
            "hint": "",
            "status": "neutral",
            "accent": "blue",
        })

    if phase_return.get("available") and phase_return.get("duration") is not None:
        overview.append({
            "label": "Длит. наката",
            "value": f"{phase_return['duration']:.3f}",
            "unit": "с",
            "hint": "",
            "status": "neutral",
            "accent": "blue",
        })

    if overview:
        groups.append({"key": "overview", "label": "Обзор", "cards": overview})

    # === ГРУППА 2: ЭНЕРГОБАЛАНС ===
    energy: list[dict] = []

    if run.energy_input_total is not None:
        energy.append({
            "label": "Подведено",
            "value": f"{run.energy_input_total / 1000:.2f}",
            "unit": "кДж",
            "hint": "выстрел + гравитация",
            "status": "neutral",
            "accent": "amber",
        })

    if run.energy_brake_total is not None:
        ratio_text = ""
        if run.energy_input_total and abs(run.energy_input_total) > 1e-6:
            ratio = run.energy_brake_total / abs(run.energy_input_total) * 100.0
            ratio_text = f"{ratio:.1f}% от входа"
        energy.append({
            "label": "Рассеяно тормозами",
            "value": f"{run.energy_brake_total / 1000:.2f}",
            "unit": "кДж",
            "hint": ratio_text,
            "status": "ok",
            "accent": "red",
        })

    if run.energy_residual_pct is not None:
        if run.energy_residual_pct < 1.0:
            status = "ok"
        elif run.energy_residual_pct < 3.0:
            status = "warn"
        else:
            status = "danger"
        energy.append({
            "label": "Невязка энерг.",
            "value": f"{run.energy_residual_pct:.2f}",
            "unit": "%",
            "hint": "норма < 1%",
            "status": status,
            "accent": "red" if status == "danger" else "amber" if status == "warn" else "green",
        })

    if energy:
        groups.append({"key": "energy", "label": "Энергобаланс", "cards": energy})

    # === ГРУППА 3: ФАЗА ОТКАТА ===
    if phase_recoil.get("available"):
        recoil_cards = [
            _range_card("X_РАЗМАХ", phase_recoil.get("x_min"), phase_recoil.get("x_max"), "м",   "blue"),
            _range_card("V_РАЗМАХ", phase_recoil.get("v_min"), phase_recoil.get("v_max"), "м/с", "green"),
            _range_card("A_РАЗМАХ", phase_recoil.get("a_min"), phase_recoil.get("a_max"), "м/с²","amber"),
        ]
        recoil_cards = [c for c in recoil_cards if c is not None]
        if recoil_cards:
            groups.append({"key": "phase-recoil", "label": "Фаза отката", "cards": recoil_cards})

    # === ГРУППА 4: ФАЗА НАКАТА ===
    if phase_return.get("available"):
        return_cards = [
            _range_card("X_РАЗМАХ", phase_return.get("x_min"), phase_return.get("x_max"), "м",   "blue"),
            _range_card("V_РАЗМАХ", phase_return.get("v_min"), phase_return.get("v_max"), "м/с", "green"),
            _range_card("A_РАЗМАХ", phase_return.get("a_min"), phase_return.get("a_max"), "м/с²","amber"),
        ]
        return_cards = [c for c in return_cards if c is not None]
        if return_cards:
            groups.append({"key": "phase-return", "label": "Фаза наката", "cards": return_cards})

    # === ГРУППА 5: КОНЕЧНОЕ СОСТОЯНИЕ ===
    final: list[dict] = []
    if run.x_final is not None:
        final.append({
            "label": "x конечное",
            "value": kpi_format(run.x_final),
            "unit": "м",
            "hint": "",
            "status": "neutral",
            "accent": "gray",
        })
    if run.v_final is not None:
        final.append({
            "label": "v конечное",
            "value": kpi_format(run.v_final),
            "unit": "м/с",
            "hint": "",
            "status": "neutral",
            "accent": "gray",
        })
    if run.a_final is not None:
        final.append({
            "label": "a конечное",
            "value": kpi_format(run.a_final),
            "unit": "м/с²",
            "hint": "",
            "status": "neutral",
            "accent": "gray",
        })

    if final:
        groups.append({"key": "final-state", "label": "Конечное состояние", "cards": final})

    return groups


def _range_card(label: str, vmin, vmax, unit: str, accent: str) -> dict | None:
    """Карточка с диапазоном min..max (для парных значений X / V / A в фазах).

    Структура:
        label = "X_РАЗМАХ"
        value = main число (max — оно обычно «главное»)
        subvalues = [{label: "min", value: ...}, {label: "max", value: ...}]

    None — если оба значения отсутствуют.
    """
    if vmin is None and vmax is None:
        return None
    return {
        "label": label,
        "value": kpi_format(vmax if vmax is not None else vmin),
        "unit": unit,
        "hint": "",
        "status": "neutral",
        "accent": accent,
        "subvalues": [
            {"label": "min", "value": kpi_format(vmin) if vmin is not None else "—", "unit": unit},
            {"label": "max", "value": kpi_format(vmax) if vmax is not None else "—", "unit": unit},
        ],
    }


def kpi_format(value) -> str:
    """Форматирование числа для KPI-карточки.

    Диапазонная точность (4/3/1/0 знаков) — отличается от templatetag `smart_num`,
    который использует %g. Не путать.
    """
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    av = abs(v)
    if av == 0.0:
        return "0"
    if av < 0.001:
        return f"{v:.2e}"
    if av < 1.0:
        return f"{v:.4f}"
    if av < 100.0:
        return f"{v:.3f}"
    if av < 10000.0:
        return f"{v:.1f}"
    return f"{v:.0f}"

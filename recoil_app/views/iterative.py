"""Итерационный расчёт (rail «Итерационный расчёт», Срез 12).

Список сессий, старт (режим + параметры + тормоза C₀), страница сессии с
управлением (Шаг / N шагов / До точки через Δx / Изменить конфигурацию /
Досчитать до конца / Остановить и построить графики) и удаление.
Действия — AJAX (`iterative_action_view`): ответ JSON с обновлёнными
панелями (HTML-фрагменты) и графиками (фигуры Plotly). Вся логика —
`services/iterative/` (store/editor/view_state); здесь только HTTP.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..forms import IterativeCalcForm, IterativeSlotFormSet
from ..models import CalculationRun, IterativeCalc
from ..services.dynamics import RecoilParams
from ..services.iterative import store
from ..services.iterative.editor import (
    slots_from_formset,
    slots_initial_from_run,
    slots_initial_from_session,
)
from ..services.iterative.view_state import build_view_state, report_message
from ..services.permissions import (
    can_edit_iterative,
    can_run_calc,
    can_view_iterative,
    can_view_run,
    iterative_visible_to,
    visible_run,
)
from ..services.run_pipeline import build_initial_from_run
from .run import _build_catalog_items

SLOTS_PREFIX = "slots"
_MAX_STEPS_PER_REQUEST = 10_000_000


def _login_redirect(request):
    return redirect(f"/login/?next={request.path}")


def iterative_list_view(request):
    calcs = list(
        iterative_visible_to(request.user)
        .select_related("owner", "result_run", "source_run")
        .order_by("-updated_at")[:100]
    )
    return render(request, "recoil_app/iterative_list.html", {
        "calcs": calcs,
        "can_create": can_run_calc(request.user),
    })


def iterative_new_view(request):
    if not can_run_calc(request.user):
        messages.warning(request, "Для запуска расчёта войдите или зарегистрируйтесь.")
        return _login_redirect(request)

    source_run = None
    if request.method == "POST":
        form = IterativeCalcForm(request.POST, request.FILES)
        slot_formset = IterativeSlotFormSet(request.POST, request.FILES, prefix=SLOTS_PREFIX)
        if form.is_valid() and slot_formset.is_valid() and form.cleaned_data.get("source_run") is not None                 and not can_view_run(request.user, form.cleaned_data["source_run"]):
            form.add_error("input_file", "Для отката загрузите файл характеристик F(t), F(x).")
        if form.is_valid() and slot_formset.is_valid():
            cd = form.cleaned_data
            try:
                config = slots_from_formset(slot_formset)
                input_file = None
                if cd["mode"] == CalculationRun.MODE_RECOIL:
                    input_file = cd.get("input_file") or store.input_file_from_run(cd["source_run"])
                calc = store.create_calc(
                    name=cd["name"],
                    mode=cd["mode"],
                    recoil=RecoilParams(mass=cd["mass"], angle_deg=cd["angle_deg"], v0=cd["v0"],
                                        x0=cd["x0"], t_max=cd["t_max"], dt=cd["dt"]),
                    config=config,
                    owner=request.user,
                    input_file=input_file,
                    source_run=cd.get("source_run"),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("iterative_detail", calc_id=calc.id)
        source_run = visible_run(request.user, request.POST.get("source_run_id"))
    else:
        initial, slots_initial = {}, [{"kind": "parametric", "lya": 2.5, "wn0": 1.0}]
        source_run = visible_run(request.user, request.GET.get("from_run"))
        if source_run is not None:
            initial, _ = build_initial_from_run(source_run.id)
            initial["mode"] = source_run.mode
            if not source_run.input_file:
                initial.pop("source_run_id", None)
            slots_initial = slots_initial_from_run(source_run) or slots_initial
        form = IterativeCalcForm(initial=initial)
        slot_formset = IterativeSlotFormSet(initial=slots_initial, prefix=SLOTS_PREFIX)

    return render(request, "recoil_app/iterative_new.html", {
        "form": form,
        "slot_formset": slot_formset,
        "source_run": source_run,
        **_catalog_context(),
    })


def iterative_detail_view(request, calc_id: int):
    calc = get_object_or_404(IterativeCalc.objects.select_related("result_run", "source_run", "owner"),
                             pk=calc_id)
    if not can_view_iterative(request.user, calc):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        return HttpResponseForbidden("Нет доступа к этому итерационному расчёту.")

    can_edit = can_edit_iterative(request.user, calc)
    state, load_error, slot_formset = None, "", None
    try:
        session = store.load_session(calc)
        state = build_view_state(session)
        if can_edit and calc.is_active:
            slot_formset = _editor_formset(session)
    except Exception as exc:  # noqa: BLE001 — показать страницу с ошибкой, а не 500
        load_error = f"{type(exc).__name__}: {exc}"

    return render(request, "recoil_app/iterative_detail.html", {
        "calc": calc,
        "state": state,
        "load_error": load_error,
        "slot_formset": slot_formset,
        "can_edit": can_edit,
        "can_clone": can_run_calc(request.user),
        "clone_name": store.suggest_clone_name(calc),
        **_catalog_context(),
    })


@require_POST
def iterative_action_view(request, calc_id: int):
    calc = get_object_or_404(IterativeCalc, pk=calc_id)
    if not can_edit_iterative(request.user, calc):
        return JsonResponse({"ok": False, "error": "Нет прав на этот итерационный расчёт."}, status=403)

    action = request.POST.get("action", "")
    try:
        if action in ("to_end", "stop"):
            run = store.finish_auto(calc, stop_now=(action == "stop"),
                                    name=(request.POST.get("result_name") or "").strip() or None)
            if run is None:   # долгий досчёт ушёл в фоновый поток — страница опрашивает статус
                return JsonResponse({"ok": True, "background": True,
                                     "status_url": reverse("iterative_status", args=[calc.id])})
            return JsonResponse({"ok": True, "redirect": reverse("run_detail_v2", args=[run.id])})

        if action == "undo":
            removed, session = store.perform(calc, lambda s: s.undo_last_change())
            message = (f"Изменение этапа {removed.index} отменено — вернулись в узел x = {removed.x:.6g} м, "
                       f"действует этап {session.active_stage}; всё посчитанное после него отброшено.")
        elif action == "configure":
            formset = IterativeSlotFormSet(request.POST, request.FILES, prefix=SLOTS_PREFIX)
            if not formset.is_valid():
                return JsonResponse({"ok": False, "error": _formset_errors(formset)}, status=400)
            changed, session = store.perform(
                calc, lambda s: s.reconfigure(slots_from_formset(formset, s.config)))
            message = (f"Конфигурация изменена — действует этап {session.active_stage}."
                       if changed else "Конфигурация не изменилась.")
        else:
            report, session = store.perform(calc, _advance_action(action, request.POST))
            message = report_message(report)
    except store.StaleCalcError as exc:
        return JsonResponse({"ok": False, "error": str(exc), "stale": True}, status=409)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    state = build_view_state(session)
    context = {"calc": calc, "state": state, "can_edit": True, **_catalog_context()}
    html = {
        "state": render_to_string("recoil_app/includes/iterative_state.html", context, request),
        "stages": render_to_string("recoil_app/includes/iterative_stages.html", context, request),
    }
    if state["can_reconfigure"]:
        context["slot_formset"] = _editor_formset(session)
        context["editor_mode"] = "reconfigure"
        html["editor"] = render_to_string(
            "recoil_app/includes/iterative_slot_editor.html", context, request)
    return JsonResponse({
        "ok": True,
        "message": message,
        "warnings": state["warnings"],
        "html": html,
        "charts": state["charts"],
        "flags": {
            "finished": state["finished"],
            "can_reconfigure": state["can_reconfigure"],
            "can_undo": state["can_undo"],
            "undo_hint": state["undo_hint"],
            "phase": state["phase"],
        },
    })


def iterative_status_view(request, calc_id: int):
    """Статус для опроса во время фонового «Досчитать до конца»."""
    calc = get_object_or_404(IterativeCalc.objects.select_related("result_run"), pk=calc_id)
    if not can_view_iterative(request.user, calc):
        return JsonResponse({"ok": False, "error": "Нет доступа."}, status=403)
    payload = {"ok": True, "status": calc.status, "error": calc.error_text}
    if calc.result_run_id:
        payload["redirect"] = reverse("run_detail_v2", args=[calc.result_run_id])
    return JsonResponse(payload)


@require_POST
def iterative_reset_view(request, calc_id: int):
    """Вернуть в «идёт» сессию, чей фоновый досчёт завис (перезапуск сервера)."""
    calc = get_object_or_404(IterativeCalc, pk=calc_id)
    if not can_edit_iterative(request.user, calc):
        return HttpResponseForbidden("Нет прав на этот итерационный расчёт.")
    if store.reset_stuck_finishing(calc):
        messages.warning(request, "Фоновый досчёт сброшен — сессию можно продолжить.")
    else:
        messages.info(request, "Досчёт ещё идёт — сбросить можно, если он висит дольше 10 минут.")
    return redirect("iterative_detail", calc_id=calc.id)


@require_POST
def iterative_clone_view(request, calc_id: int):
    """Клон сессии в текущем состоянии под новым именем (автор — текущий пользователь)."""
    source = get_object_or_404(IterativeCalc, pk=calc_id)
    if not (can_view_iterative(request.user, source) and can_run_calc(request.user)):
        return HttpResponseForbidden("Нет прав клонировать этот итерационный расчёт.")
    try:
        clone = store.clone_calc(source, name=request.POST.get("name", ""), owner=request.user)
    except ValueError as exc:
        messages.error(request, f"Не удалось клонировать: {exc}")
        return redirect("iterative_detail", calc_id=source.id)
    messages.success(request, f"Создан клон «{clone.name}» — можно отменять изменения и считать иначе; "
                              f"оригинал «{source.name}» не изменён.")
    return redirect("iterative_detail", calc_id=clone.id)


@require_POST
def iterative_delete_view(request, calc_id: int):
    calc = get_object_or_404(IterativeCalc, pk=calc_id)
    if not can_edit_iterative(request.user, calc):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        return HttpResponseForbidden("Удалять можно только свой итерационный расчёт.")
    name = calc.name
    store.delete_calc(calc)
    messages.success(request, f"Итерационный расчёт «{name}» удалён (итоговый расчёт, если был, сохранён).")
    return redirect("iterative_list")


# ------------------------------------------------------------------ helpers

def _advance_action(action: str, data):
    """Продвижение из POST: step / steps (n) / distance (dx, м)."""
    if action == "step":
        return lambda s: s.step(1)
    if action == "steps":
        try:
            n = int(data.get("n", ""))
        except ValueError:
            raise ValueError("Число шагов N должно быть целым.") from None
        if not 1 <= n <= _MAX_STEPS_PER_REQUEST:
            raise ValueError(f"Число шагов N — от 1 до {_MAX_STEPS_PER_REQUEST:,}.".replace(",", " "))
        return lambda s: s.step(n)
    if action == "distance":
        try:
            dx = float(str(data.get("dx", "")).replace(",", "."))
        except ValueError:
            raise ValueError("Путь Δx должен быть числом, м.") from None
        if not dx > 0:
            raise ValueError("Путь Δx должен быть > 0.")
        return lambda s: s.advance_distance(dx)
    raise ValueError(f"Неизвестное действие: {action!r}")


def _editor_formset(session):
    return IterativeSlotFormSet(initial=slots_initial_from_session(session), prefix=SLOTS_PREFIX)


def _formset_errors(formset) -> str:
    lines = [str(e) for e in formset.non_form_errors()]
    for position, form in enumerate(formset.forms, 1):
        for field, errors in form.errors.items():
            label = f"{form.fields[field].label}: " if field in form.fields else ""   # __all__ — без подписи
            lines.extend(f"Тормоз {position}: {label}{e}" for e in errors)
    return " ".join(lines) or "Проверьте конфигурацию тормозов."


def _catalog_context() -> dict:
    items = _build_catalog_items()
    return {"catalog_items": items, "catalog_count": len(items)}

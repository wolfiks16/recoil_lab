"""Каталог тормозов (`/catalog/`) — список, CRUD, AJAX-сохранение из формы расчёта."""

from pathlib import Path

from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import BrakeCatalogForm
from ..models import BrakeCatalog, MagneticBrakeConfig
from ..services.charting import make_brake_curve_fragment
from ..services.curve_parser import parse_force_curve_sheet


def catalog_list_view(request):
    """Список всех тормозов в каталоге с поиском и сортировкой."""
    qs = BrakeCatalog.objects.all()

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    flt = request.GET.get("filter") or "all"
    if flt == "parametric":
        qs = qs.filter(model_type=BrakeCatalog.MODEL_TYPE_PARAMETRIC)
    elif flt == "curve":
        qs = qs.filter(model_type=BrakeCatalog.MODEL_TYPE_CURVE)

    sort = request.GET.get("sort") or "name"
    allowed = {
        "name": "name",
        "-name": "-name",
        "-created_at": "-created_at",
        "created_at": "created_at",
        "-updated_at": "-updated_at",
    }
    qs = qs.order_by(allowed.get(sort, "name"))

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page") or 1)

    qs_keep_parts: list[str] = []
    for key in ("q", "filter", "sort"):
        v = request.GET.get(key)
        if v:
            qs_keep_parts.append(f"{key}={v}")
    qs_keep_str = "&".join(qs_keep_parts)

    return render(
        request,
        "recoil_app/catalog_list.html",
        {
            "page": page,
            "paginator": paginator,
            "items": page.object_list,
            "q": q,
            "filter_value": flt,
            "sort_value": sort,
            "qs_keep_str": qs_keep_str,
            "total_count": BrakeCatalog.objects.count(),
            "parametric_count": BrakeCatalog.objects.filter(model_type=BrakeCatalog.MODEL_TYPE_PARAMETRIC).count(),
            "curve_count": BrakeCatalog.objects.filter(model_type=BrakeCatalog.MODEL_TYPE_CURVE).count(),
        },
    )


def catalog_new_view(request):
    """Создание нового тормоза в каталоге."""
    if request.method == "POST":
        form = BrakeCatalogForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Тормоз «{obj.name}» добавлен в каталог.")
            return redirect("catalog_list")
    else:
        form = BrakeCatalogForm()

    return render(
        request,
        "recoil_app/catalog_form.html",
        {
            "form": form,
            "is_edit": False,
            "object": None,
        },
    )


def catalog_detail_view(request, pk):
    """Детальная страница тормоза в каталоге.

    Показывает:
    - Hero с именем, описанием, бейджем типа
    - Для параметрических: KPI-карточки с физическими параметрами + формула
    - Для табличных: график F(v), статистика по точкам, таблица первых N точек
    - Кнопки: редактировать, удалить, назад к списку
    """
    obj = get_object_or_404(BrakeCatalog, pk=pk)

    parametric_cards: list[dict] = []
    if obj.is_parametric:
        param_specs = [
            # (model_attr, label, symbol, unit, accent, group)
            ("gamma", "Удельная проводимость",        "γ",            "(Ом·м)⁻¹", "blue",   "material"),
            ("delta", "Толщина шины",                  "δ",            "м",     "blue",   "material"),
            ("mu",    "Магнитная проницаемость шины",  "μ",            "Гн/м",  "blue",   "material"),
            ("bz",    "Индукция в рабочем зазоре",     "B̄₃",           "Тл",    "amber",  "material"),
            ("n",     "Количество блоков",             "N",            "",      "purple", "geometry"),
            ("xm",    "Размер магнита по оси X",       "x_m",          "м",     "green",  "geometry"),
            ("ym",    "Размер магнита по оси Y",       "y_m",          "м",     "green",  "geometry"),
            ("dh1",   "Выступ 1-го края шины",         "Δh₁",          "м",     "green",  "geometry"),
            ("dh2",   "Выступ 2-го края шины",         "Δh₂",          "м",     "green",  "geometry"),
            ("dm",    "Промежутки между магнитами",    "d_m",          "м",     "green",  "geometry"),
            ("lya",   "Параметр λa",                   "λa",           "",      "red",    "extra"),
            ("wn0",   "Начальное состояние wn",        "w_n0",         "",      "red",    "extra"),
        ]

        for attr, label, symbol, unit, accent, group in param_specs:
            value = getattr(obj, attr)
            parametric_cards.append({
                "label":  label,
                "symbol": symbol,
                "value":  value,
                "unit":   unit,
                "accent": accent,
                "group":  group,
            })

    curve_html = ""
    curve_points: list[dict] = []
    curve_stats = None
    curve_error = None

    if obj.is_curve and obj.curve_file:
        try:
            obj.curve_file.open("rb")
            try:
                from openpyxl import load_workbook
                workbook = load_workbook(obj.curve_file, read_only=True, data_only=True)
                try:
                    curve_points = parse_force_curve_sheet(workbook.active)
                finally:
                    workbook.close()
            finally:
                obj.curve_file.close()

            if curve_points:
                curve_html = make_brake_curve_fragment(
                    curve_points,
                    title=f"F(v) — {obj.name}",
                )
                vs = [p["velocity"] for p in curve_points]
                fs = [p["force"] for p in curve_points]
                curve_stats = {
                    "n_points": len(curve_points),
                    "v_min": min(vs),
                    "v_max": max(vs),
                    "f_min": min(fs),
                    "f_max": max(fs),
                }
        except Exception as exc:  # noqa: BLE001
            curve_error = f"Не удалось прочитать файл F(v): {type(exc).__name__}: {exc}"

    # Тормоз в каталоге не связан напрямую с MagneticBrakeConfig (copy-on-use),
    # но мы можем показать сколько раз он был использован — по совпадению имени.
    usage_count = MagneticBrakeConfig.objects.filter(name=obj.name).count()

    return render(
        request,
        "recoil_app/catalog_detail.html",
        {
            "object": obj,
            "parametric_cards": parametric_cards,
            "curve_points": curve_points,
            "curve_html": curve_html,
            "curve_stats": curve_stats,
            "curve_error": curve_error,
            "usage_count": usage_count,
        },
    )


def catalog_edit_view(request, pk):
    """Редактирование существующей записи каталога."""
    obj = get_object_or_404(BrakeCatalog, pk=pk)

    if request.method == "POST":
        form = BrakeCatalogForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Тормоз «{obj.name}» обновлён.")
            return redirect("catalog_list")
    else:
        form = BrakeCatalogForm(instance=obj)

    return render(
        request,
        "recoil_app/catalog_form.html",
        {
            "form": form,
            "is_edit": True,
            "object": obj,
        },
    )


@require_POST
def catalog_delete_view(request, pk):
    """Удаление тормоза из каталога."""
    obj = get_object_or_404(BrakeCatalog, pk=pk)
    name = obj.name
    if obj.curve_file:
        try:
            obj.curve_file.delete(save=False)
        except Exception:
            pass
    obj.delete()
    messages.success(request, f"Тормоз «{name}» удалён из каталога.")
    return redirect("catalog_list")


@require_POST
def catalog_save_from_brake_form_view(request):
    """AJAX-эндпоинт для сохранения тормоза из формы расчёта в каталог.

    Принимает form-encoded данные с параметрами тормоза.
    Возвращает JSON: {"ok": true, "id": N, "name": "..."} или {"ok": false, "error": "..."}.
    """

    def _f(key):
        v = (request.POST.get(key) or "").strip()
        if not v:
            return None
        try:
            return float(v.replace(",", "."))
        except (ValueError, TypeError):
            return None

    def _i(key):
        v = _f(key)
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    name = (request.POST.get("name") or "").strip()
    description = (request.POST.get("description") or "").strip()
    model_type = (request.POST.get("model_type") or "").strip()

    if not name:
        return JsonResponse({"ok": False, "error": "Имя тормоза обязательно."}, status=400)

    if model_type not in (BrakeCatalog.MODEL_TYPE_PARAMETRIC, BrakeCatalog.MODEL_TYPE_CURVE):
        return JsonResponse({"ok": False, "error": "Некорректный тип модели."}, status=400)

    if BrakeCatalog.objects.filter(name=name).exists():
        return JsonResponse(
            {"ok": False, "error": f"Тормоз с именем «{name}» уже есть в каталоге."},
            status=400,
        )

    if model_type == BrakeCatalog.MODEL_TYPE_PARAMETRIC:
        params = {
            "gamma": _f("gamma"),
            "delta": _f("delta"),
            "n":     _i("n"),
            "xm":    _f("xm"),
            "ym":    _f("ym"),
            "dh1":   _f("dh1"),
            "dh2":   _f("dh2"),
            "dm":    _f("dm"),
            "mu":    _f("mu"),
            "bz":    _f("bz"),
            "lya":   _f("lya"),
            "wn0":   _f("wn0"),
        }
        missing = [k for k, v in params.items() if v is None]
        if missing:
            return JsonResponse(
                {"ok": False, "error": f"Не заполнены параметры: {', '.join(missing)}"},
                status=400,
            )
        obj = BrakeCatalog.objects.create(
            name=name,
            description=description,
            model_type=model_type,
            **params,
        )
    else:
        # Для табличной — нужен файл F(v).
        # При сохранении из формы расчёта файл может быть только что загружен в форму
        # (в multipart-запросе) — либо его уже нет (файл из catalog_source_id).
        curve_file = request.FILES.get("curve_file")
        catalog_source_id = (request.POST.get("catalog_source_id") or "").strip()

        if not curve_file and not catalog_source_id:
            return JsonResponse(
                {"ok": False, "error": "Для табличной модели нужен файл F(v) или ссылка на каталог."},
                status=400,
            )

        if curve_file:
            obj = BrakeCatalog.objects.create(
                name=name,
                description=description,
                model_type=model_type,
                curve_file=curve_file,
            )
        else:
            try:
                source = BrakeCatalog.objects.get(pk=int(catalog_source_id))
            except (ValueError, BrakeCatalog.DoesNotExist):
                return JsonResponse(
                    {"ok": False, "error": "Источник в каталоге не найден."},
                    status=400,
                )
            obj = BrakeCatalog.objects.create(
                name=name,
                description=description,
                model_type=model_type,
            )
            if source.curve_file:
                source.curve_file.open("rb")
                try:
                    content = source.curve_file.read()
                finally:
                    source.curve_file.close()
                original_name = Path(source.curve_file.name).name or "curve.xlsx"
                obj.curve_file.save(original_name, ContentFile(content), save=True)

    return JsonResponse({
        "ok": True,
        "id": obj.pk,
        "name": obj.name,
        "model_type": obj.model_type,
    })

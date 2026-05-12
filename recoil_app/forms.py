from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.forms import BaseFormSet, formset_factory

from .models import CalculationRun, MagneticBrakeConfig, UserProfile
from .services.curve_parser import parse_force_curve_file


class CalculationForm(forms.Form):
    name = forms.CharField(
        required=True,
        label="Название расчёта",
        widget=forms.TextInput(attrs={
            "pattern": "[A-Za-z0-9_-]+",
            "title": "Только английские буквы, цифры, дефис и подчёркивание",
        }),
    )
    input_file = forms.FileField(label="Файл характеристик Excel")

    mass = forms.FloatField(
        label="Масса",
        validators=[MinValueValidator(1e-6, "Масса должна быть положительной.")],
        widget=forms.NumberInput(attrs={"min": "0.000001", "step": "any"}),
    )
    angle_deg = forms.FloatField(
        initial=70.0,
        label="Угол, град",
        validators=[
            MinValueValidator(0.0, "Угол должен быть неотрицательным."),
            MaxValueValidator(90.0, "Угол не должен превышать 90°."),
        ],
        widget=forms.NumberInput(attrs={"min": "0", "max": "90", "step": "any"}),
    )
    v0 = forms.FloatField(
        initial=0.0,
        label="Начальная скорость",
        validators=[MinValueValidator(0.0, "Начальная скорость должна быть ≥ 0.")],
        widget=forms.NumberInput(attrs={"min": "0", "step": "any"}),
    )
    x0 = forms.FloatField(
        initial=0.0,
        label="Начальное перемещение",
        validators=[MinValueValidator(0.0, "Начальное перемещение должно быть ≥ 0.")],
        widget=forms.NumberInput(attrs={"min": "0", "step": "any"}),
    )
    t_max = forms.FloatField(
        initial=0.15,
        label="Время расчёта",
        validators=[
            MinValueValidator(1e-6, "Время расчёта должно быть положительным."),
            MaxValueValidator(10.0, "Время расчёта не должно превышать 10 с."),
        ],
        widget=forms.NumberInput(attrs={"min": "0.000001", "max": "10", "step": "any"}),
    )
    dt = forms.FloatField(initial=1e-4, label="Шаг dt")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise forms.ValidationError(
                "Название должно содержать только английские буквы, цифры, дефис и подчёркивание."
            )

        if CalculationRun.objects.filter(name=name).exists():
            raise forms.ValidationError("Расчёт с таким названием уже существует.")

        return name


class MagneticBrakeForm(forms.Form):
    model_type = forms.ChoiceField(
        label="Тип задания тормоза",
        choices=MagneticBrakeConfig.MODEL_TYPE_CHOICES,
        initial=MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC,
    )
    name = forms.CharField(label="Имя тормоза", max_length=255, required=False)

    # Параметрическая модель
    gamma = forms.FloatField(label="gamma", required=False)
    delta = forms.FloatField(label="delta", required=False)
    xm = forms.FloatField(label="xm", required=False)
    ym = forms.FloatField(label="ym", required=False)
    dh1 = forms.FloatField(label="dh1", required=False)
    dh2 = forms.FloatField(label="dh2", required=False)
    dm = forms.FloatField(label="dm", required=False)
    n = forms.IntegerField(
        label="n",
        required=False,
        widget=forms.NumberInput(attrs={"min": "1", "step": "1"}),
    )
    mu = forms.FloatField(label="mu", required=False)
    bz = forms.FloatField(label="bz", required=False)
    lya = forms.FloatField(initial=2.5, label="lya", required=False)
    wn0 = forms.FloatField(initial=1.0, label="wn0", required=False)

    # Табличная модель через Excel
    force_curve_file = forms.FileField(
        label="Excel-файл характеристики F(v)",
        required=False,
        help_text=(
            "Первый лист: колонка A — скорость, колонка B — сила. "
            "Первая строка может быть заголовком."
        ),
    )

    # Для сценария 'Подставить в новый расчёт' — reuse уже сохранённой curve-характеристики
    curve_source_brake_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    # Срез 3b: ID выбранного тормоза из каталога (если пользователь выбрал «Из каталога»).
    # Параметры всё равно копируются из формы (юзер мог их откорректировать),
    # но для curve — copy-on-use файла F(v) из каталога идёт через этот ID в view'хе.
    catalog_source_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean(self):
        cleaned_data = super().clean()
        model_type = cleaned_data.get("model_type")

        if model_type == MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC:
            required_param_fields = [
                "gamma",
                "delta",
                "xm",
                "ym",
                "dh1",
                "dh2",
                "dm",
                "n",
                "mu",
                "bz",
                "lya",
                "wn0",
            ]

            missing = [
                field_name
                for field_name in required_param_fields
                if cleaned_data.get(field_name) in (None, "")
            ]
            if missing:
                raise ValidationError(
                    "Для параметрического тормоза должны быть заполнены все коэффициенты."
                )

            cleaned_data["parsed_force_curve_points"] = []
            cleaned_data["curve_file_provided"] = False
            cleaned_data["curve_source_brake_id"] = ""

        elif model_type == MagneticBrakeConfig.MODEL_TYPE_CURVE:
            uploaded_file = cleaned_data.get("force_curve_file")
            source_brake_id = (cleaned_data.get("curve_source_brake_id") or "").strip()
            catalog_source_id = cleaned_data.get("catalog_source_id")

            if uploaded_file:
                # Файл загружен прямо в форму
                parsed_points = parse_force_curve_file(uploaded_file)
                cleaned_data["parsed_force_curve_points"] = parsed_points
                cleaned_data["curve_file_provided"] = True
                cleaned_data["curve_source_brake_id"] = ""
            elif source_brake_id:
                # Reuse характеристики из ранее запущенного расчёта
                try:
                    int(source_brake_id)
                except ValueError as exc:
                    raise ValidationError(
                        "Некорректный идентификатор исходной характеристики тормоза."
                    ) from exc

                cleaned_data["parsed_force_curve_points"] = None
                cleaned_data["curve_file_provided"] = False
                cleaned_data["curve_source_brake_id"] = source_brake_id
            elif catalog_source_id:
                # Будет copy-on-use из каталога — фактическое чтение файла в view.
                # Здесь просто разрешаем сохранение без uploaded_file.
                cleaned_data["parsed_force_curve_points"] = None
                cleaned_data["curve_file_provided"] = False
                cleaned_data["curve_source_brake_id"] = ""
            else:
                raise ValidationError(
                    "Для тормоза, заданного графиком, необходимо загрузить Excel-файл "
                    "характеристики F(v) или выбрать тормоз из каталога."
                )

        return cleaned_data


class BaseMagneticBrakeFormSet(BaseFormSet):
    def clean(self):
        super().clean()

        if any(self.errors):
            return

        active_forms = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if not form.cleaned_data:
                continue
            active_forms += 1

        if active_forms < 1:
            raise ValidationError("Необходимо задать минимум один тормоз.")


MagneticBrakeFormSet = formset_factory(
    MagneticBrakeForm,
    formset=BaseMagneticBrakeFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)


class CompareRunsForm(forms.Form):
    run_a = forms.ModelChoiceField(
        queryset=CalculationRun.objects.order_by("-created_at"),
        label="Расчёт A",
    )
    run_b = forms.ModelChoiceField(
        queryset=CalculationRun.objects.order_by("-created_at"),
        label="Расчёт B",
    )

    def clean(self):
        cleaned_data = super().clean()
        run_a = cleaned_data.get("run_a")
        run_b = cleaned_data.get("run_b")

        if run_a and run_b and run_a.pk == run_b.pk:
            raise ValidationError("Для сравнения нужно выбрать два разных расчёта.")

        return cleaned_data

# ============================================================================
# СРЕЗ 3a: Каталог тормозов
# ============================================================================

from .models import BrakeCatalog  # noqa: E402  (импорт здесь, чтобы не ломать сверху)


class BrakeCatalogForm(forms.ModelForm):
    """Форма создания/редактирования записи в каталоге тормозов."""

    class Meta:
        model = BrakeCatalog
        fields = [
            "name",
            "description",
            "model_type",
            "gamma", "delta", "n",
            "curve_file",
            # доп. параметры
            "xm", "ym", "dh1", "dh2", "dm", "mu", "bz", "lya", "wn0",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        model_type = cleaned.get("model_type")

        if model_type == BrakeCatalog.MODEL_TYPE_PARAMETRIC:
            # Для параметрической модели все параметры обязательные.
            required_fields = [
                "gamma", "delta", "n",
                "xm", "ym", "dh1", "dh2", "dm",
                "mu", "bz", "lya", "wn0",
            ]
            missing: list[str] = []
            for field_name in required_fields:
                value = cleaned.get(field_name)
                if value is None or value == "":
                    missing.append(field_name)
                    # Отметим конкретное поле, чтобы рамка ошибки появилась рядом
                    self.add_error(
                        field_name,
                        "Обязательное поле для параметрической модели."
                    )
            if missing:
                # Общее сообщение наверх формы — какие поля не заполнены
                raise ValidationError(
                    "Для параметрической модели заполните все параметры. "
                    f"Не заполнены: {', '.join(missing)}."
                )

        elif model_type == BrakeCatalog.MODEL_TYPE_CURVE:
            # Для табличной модели нужен только файл F(v).
            curve_file = cleaned.get("curve_file")
            instance = getattr(self, "instance", None)
            already_has_file = bool(instance and instance.pk and instance.curve_file)
            if not curve_file and not already_has_file:
                self.add_error(
                    "curve_file",
                    "Обязательно загрузите файл F(v) для табличной модели."
                )
                raise ValidationError(
                    "Для табличной модели загрузите файл F(v)."
                )

        return cleaned

    def clean_name(self):
        """Имя должно быть уникальным (с учётом редактирования существующей записи)."""
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError("Имя обязательно.")

        qs = BrakeCatalog.objects.filter(name=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Запись с таким именем уже существует в каталоге.")
        return name


# ============================================================================
# Тепловой модуль: формы для ThermalRun
# ============================================================================

from .models import ThermalRun  # noqa: E402
from .services.thermal.materials import (  # noqa: E402
    BUS_MATERIAL_CHOICES,
    NONMAG_ROD_MATERIAL_CHOICES,
    material_choices_for_form,
)


def _positive_float(label: str, *, initial=None, required=True, help_text="") -> forms.FloatField:
    return forms.FloatField(
        label=label,
        required=required,
        initial=initial,
        help_text=help_text,
        validators=[MinValueValidator(0.0, "Значение должно быть ≥ 0.")],
        widget=forms.NumberInput(attrs={"min": "0", "step": "any"}),
    )


def _strict_positive_float(label: str, *, initial=None, required=True, help_text="") -> forms.FloatField:
    return forms.FloatField(
        label=label,
        required=required,
        initial=initial,
        help_text=help_text,
        validators=[MinValueValidator(1e-9, "Значение должно быть положительным.")],
        widget=forms.NumberInput(attrs={"min": "0.000000001", "step": "any"}),
    )


class ThermalRunForm(forms.Form):
    """Главная форма теплового сценария — цикл и параметры сборки."""

    name = forms.CharField(
        label="Название сценария",
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "Очередь 5 выстрелов",
        }),
    )

    network_preset = forms.ChoiceField(
        label="Тепловая сеть",
        choices=ThermalRun.PRESET_CHOICES,
        initial=ThermalRun.PRESET_NINE_NODE,
    )

    repetitions = forms.IntegerField(
        label="Число повторений",
        initial=1,
        validators=[
            MinValueValidator(1, "Повторений должно быть не меньше 1."),
            MaxValueValidator(100, "Повторений не больше 100."),
        ],
        widget=forms.NumberInput(attrs={"min": "1", "max": "100", "step": "1"}),
    )
    pause_s = forms.FloatField(
        label="Пауза между повторениями, с",
        initial=10.0,
        validators=[MinValueValidator(0.0, "Пауза не может быть отрицательной.")],
        widget=forms.NumberInput(attrs={"min": "0", "step": "any"}),
    )

    # --- Геометрия сборки (только для 9-узловой сети) ---
    D_casing_outer = _strict_positive_float("Обечайка: внешний Ø, м", initial=0.450, required=False)
    delta_casing = _strict_positive_float("Обечайка: толщина стенки, м", initial=0.015, required=False)
    L_casing = _strict_positive_float("Обечайка: длина, м", initial=0.85, required=False)

    D_nonmag_outer = _strict_positive_float("Шток немагн.: внешний Ø, м", initial=0.322, required=False)
    D_nonmag_inner = _strict_positive_float("Шток немагн.: внутренний Ø, м", initial=0.282, required=False)
    L_nonmag = _strict_positive_float("Шток немагн.: длина, м", initial=0.85, required=False)
    nonmag_rod_material = forms.ChoiceField(
        label="Материал штока немагнитного",
        choices=material_choices_for_form(NONMAG_ROD_MATERIAL_CHOICES),
        initial="stainless",
        required=False,
    )

    D_rod_steel_outer = _strict_positive_float("Шток сталь: внешний Ø, м", initial=0.202, required=False)
    D_rod_steel_inner = _positive_float("Шток сталь: внутренний Ø (0 = сплошной), м", initial=0.172, required=False)
    L_rod_steel = _strict_positive_float("Шток сталь: длина, м", initial=0.85, required=False)

    delta_gap_casing_to_outer_bus = _strict_positive_float(
        "Зазор обечайка↔шина внеш., м", initial=1e-3, required=False,
    )
    delta_gap_inner_bus_to_rod = _strict_positive_float(
        "Зазор шина внутр.↔шток сталь, м", initial=1e-3, required=False,
    )
    h_contact_magnet_rod = _strict_positive_float(
        "h контакта магнит↔шток, Вт/(м²·К)", initial=1000.0, required=False,
    )

    h_ambient_outer = _strict_positive_float(
        "h наружного воздуха, Вт/(м²·К)", initial=10.0, required=False,
    )
    T_ambient_outer = forms.FloatField(
        label="T наружного воздуха, °C",
        initial=20.0,
        required=False,
        widget=forms.NumberInput(attrs={"step": "any"}),
    )
    h_ambient_rod_cavity = _positive_float(
        "h воздуха внутри штока, Вт/(м²·К)", initial=4.0, required=False,
    )
    T_ambient_rod_cavity = forms.FloatField(
        label="T воздуха внутри штока, °C",
        initial=25.0,
        required=False,
        widget=forms.NumberInput(attrs={"step": "any"}),
    )

    def __init__(self, *args, run=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._run = run

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError("Название обязательно.")
        if self._run is not None:
            qs = ThermalRun.objects.filter(run=self._run, name=name)
            if qs.exists():
                raise ValidationError(
                    "Сценарий с таким названием уже есть для этого расчёта."
                )
        return name

    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("network_preset")
        if preset == ThermalRun.PRESET_NINE_NODE:
            required_fields = [
                "D_casing_outer", "delta_casing", "L_casing",
                "D_nonmag_outer", "D_nonmag_inner", "L_nonmag", "nonmag_rod_material",
                "D_rod_steel_outer", "L_rod_steel",
                "delta_gap_casing_to_outer_bus", "delta_gap_inner_bus_to_rod",
                "h_contact_magnet_rod",
                "h_ambient_outer", "T_ambient_outer",
            ]
            missing = [f for f in required_fields if cleaned.get(f) in (None, "")]
            if missing:
                for f in missing:
                    self.add_error(f, "Обязательное поле для 9-узловой сети.")
                raise ValidationError(
                    "Для 9-узловой сети заполните геометрию сборки полностью."
                )

            # Sanity-check: D_outer > D_inner у пар.
            pairs = [
                ("D_nonmag_outer", "D_nonmag_inner"),
                ("D_rod_steel_outer", "D_rod_steel_inner"),
            ]
            for d_out, d_in in pairs:
                v_out = cleaned.get(d_out)
                v_in = cleaned.get(d_in)
                if v_out is not None and v_in is not None and v_in > 0 and v_in >= v_out:
                    self.add_error(d_in, "Внутренний Ø должен быть меньше внешнего.")
        return cleaned


class ThermalBrakeForm(forms.Form):
    """Форма геометрии одного тормоза для тепловой сети."""

    bus_material = forms.ChoiceField(
        label="Материал шины",
        choices=material_choices_for_form(BUS_MATERIAL_CHOICES),
        initial="aluminum",
    )

    D_bus_outer = _strict_positive_float("Шина: внешний Ø, м", initial=0.4)
    D_bus_inner = _strict_positive_float("Шина: внутренний Ø, м", initial=0.385)
    L_active = _strict_positive_float("Активная длина, м", initial=0.80)

    D_pole_outer = _strict_positive_float("Полюсник: внешний Ø, м", initial=0.382, required=False)
    D_pole_inner = _strict_positive_float("Полюсник: внутренний Ø, м", initial=0.352, required=False)
    L_pole = _strict_positive_float("Полюсник: длина, м", initial=0.80, required=False)

    D_magnet_outer = _strict_positive_float("Магниты: внешний Ø, м", initial=0.352, required=False)
    D_magnet_inner = _strict_positive_float("Магниты: внутренний Ø, м", initial=0.322, required=False)
    L_magnet = _strict_positive_float("Магниты: длина, м", initial=0.78, required=False)

    delta_gap_working = _strict_positive_float(
        "Толщина рабочего магнитного зазора, м", initial=1.5e-3, required=False,
    )
    h_contact_pole_magnet = _strict_positive_float(
        "h контакта полюсник↔магнит, Вт/(м²·К)", initial=1000.0, required=False,
    )

    def __init__(self, *args, network_preset=None, brake_meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._network_preset = network_preset
        # brake_meta: {'index': int, 'display_name': str, 'magnetic_params': dict|None}
        # Используется в шаблоне для подписи и в JS-кнопке "подставить из brake params".
        self._brake_meta = brake_meta or {}

    def clean(self):
        cleaned = super().clean()

        # Проверка, что внутр. Ø < внешн. Ø по парам
        pairs = [
            ("D_bus_outer", "D_bus_inner"),
            ("D_pole_outer", "D_pole_inner"),
            ("D_magnet_outer", "D_magnet_inner"),
        ]
        for d_out, d_in in pairs:
            v_out = cleaned.get(d_out)
            v_in = cleaned.get(d_in)
            if v_out is not None and v_in is not None and v_in >= v_out:
                self.add_error(d_in, "Внутренний Ø должен быть меньше внешнего.")

        # Для 9-узловой все поля обязательные.
        if self._network_preset == ThermalRun.PRESET_NINE_NODE:
            nine_node_required = [
                "D_pole_outer", "D_pole_inner", "L_pole",
                "D_magnet_outer", "D_magnet_inner", "L_magnet",
                "delta_gap_working", "h_contact_pole_magnet",
            ]
            for f in nine_node_required:
                if cleaned.get(f) in (None, ""):
                    self.add_error(f, "Обязательное поле для 9-узловой сети.")
        return cleaned


class BaseThermalBrakeFormSet(BaseFormSet):
    """Formset, в котором каждой форме можно прокинуть network_preset и brake_meta."""

    def __init__(self, *args, network_preset=None, brake_meta_list=None, **kwargs):
        self._network_preset = network_preset
        self._brake_meta_list = brake_meta_list or []
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["network_preset"] = self._network_preset
        if 0 <= index < len(self._brake_meta_list):
            kwargs["brake_meta"] = self._brake_meta_list[index]
        return kwargs


ThermalBrakeFormSet = formset_factory(
    ThermalBrakeForm,
    formset=BaseThermalBrakeFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)


# ============================================================================
# Упрощённая тепловая постановка с ручным вводом (PRESET_USER_SIMPLE)
# ============================================================================
#
# Топология одного контура:
#   [ВОЗДУХ_in]──G_air_in──[ШИНА+МАГНИТОПРОВОД]──G_air_out──[ВОЗДУХ_out]
#                                ▲
#                                │ Q = F_brake(t)·v(t)
#
# Шина и магнитопровод объединены в один узел: плотный контакт металл-металл
# даёт τ ≈ 1 с — выравнивание происходит быстрее одного цикла откат-накат.
# На контур: m_ш, cp_ш, m_маг, cp_маг, G_air_in, G_air_out, T₀  — 7 полей.
# Общие: T_ambient, repetitions, pause.
#
# G в форме — итоговая проводимость [Вт/К]. Рядом UI-калькулятор h·A → G.

class ThermalUserSimpleRunForm(forms.Form):
    """Общие параметры упрощённого теплового сценария."""

    name = forms.CharField(
        label="Название сценария",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Очередь 5 выстрелов"}),
    )

    repetitions = forms.IntegerField(
        label="Число повторений",
        initial=1,
        validators=[
            MinValueValidator(1, "Повторений должно быть не меньше 1."),
            MaxValueValidator(100, "Повторений не больше 100."),
        ],
        widget=forms.NumberInput(attrs={"min": "1", "max": "100", "step": "1"}),
    )
    pause_s = forms.FloatField(
        label="Пауза между повторениями, с",
        initial=10.0,
        validators=[MinValueValidator(0.0, "Пауза не может быть отрицательной.")],
        widget=forms.NumberInput(attrs={"min": "0", "step": "any"}),
    )

    T_ambient = forms.FloatField(
        label="Температура воздуха, °C",
        initial=20.0,
        widget=forms.NumberInput(attrs={"step": "any"}),
        help_text="Одна общая T для внутренней и внешней стороны коаксиальной трубы.",
    )

    def __init__(self, *args, run=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._run = run

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise ValidationError("Название обязательно.")
        if self._run is not None:
            qs = ThermalRun.objects.filter(run=self._run, name=name)
            if qs.exists():
                raise ValidationError(
                    "Сценарий с таким названием уже есть для этого расчёта."
                )
        return name


class ThermalUserSimpleBrakeForm(forms.Form):
    """Параметры одного контура (шина+магнитопровод, плотный контакт)."""

    # --- Шина ---
    bus_mass_kg = _strict_positive_float(
        "Масса шины, кг",
        initial=5.0,
        help_text="Масса той части шины, что участвует в тепловой задаче.",
    )
    bus_cp = _strict_positive_float(
        "Теплоёмкость шины cp, Дж/(кг·К)",
        initial=900.0,
        help_text="Алюминий ≈ 900, медь ≈ 385, сталь ≈ 460.",
    )

    # --- Магнитопровод (плотный контакт с шиной) ---
    yoke_mass_kg = _strict_positive_float(
        "Масса магнитопровода, кг",
        initial=10.0,
        help_text="Магнитопровод плотно прижат к шине, тепло проходит через G_pole.",
    )
    yoke_cp = _strict_positive_float(
        "Теплоёмкость магнитопровода cp, Дж/(кг·К)",
        initial=460.0,
        help_text="Сталь магнитная (Ст10, Ст3 и т.п.) ≈ 460.",
    )

    # --- Контакт шина↔магнитопровод ---
    g_pole = _strict_positive_float(
        "G шина↔магнитопровод, Вт/К",
        initial=2000.0,
        help_text=(
            "Плотный металл-металл контакт обычно 1000…3000 Вт/К. "
            "Чем выше, тем быстрее температуры выравниваются."
        ),
    )

    # --- Теплоотдача в воздух с двух сторон коаксиальной трубы ---
    g_air_inner = _strict_positive_float(
        "G шина→внутренний воздух, Вт/К",
        initial=3.0,
        help_text="Сторона шины, обращённая внутрь трубы. Можно посчитать как h·A.",
    )
    g_air_outer = _strict_positive_float(
        "G магнитопровод→внешний воздух, Вт/К",
        initial=5.0,
        help_text="Сторона магнитопровода, обращённая наружу (часто обдув → большее G).",
    )

    # --- Начальная температура контура ---
    temp0_c = forms.FloatField(
        label="Начальная температура, °C",
        initial=20.0,
        widget=forms.NumberInput(attrs={"step": "any"}),
    )

    def __init__(self, *args, brake_meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._brake_meta = brake_meta or {}


class BaseThermalUserSimpleBrakeFormSet(BaseFormSet):
    """Formset: позволяет прокинуть brake_meta_list (по тормозу на форму)."""

    def __init__(self, *args, brake_meta_list=None, **kwargs):
        self._brake_meta_list = brake_meta_list or []
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        if 0 <= index < len(self._brake_meta_list):
            kwargs["brake_meta"] = self._brake_meta_list[index]
        return kwargs


ThermalUserSimpleBrakeFormSet = formset_factory(
    ThermalUserSimpleBrakeForm,
    formset=BaseThermalUserSimpleBrakeFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)


class UserRegistrationForm(UserCreationForm):
    """Расширенная регистрация: + имя, фамилия, дата рождения.

    UserCreationForm даёт username + password1 + password2; добавляем личные
    данные. first_name/last_name пишутся на User, birth_date — на UserProfile
    (профиль создаёт сигнал post_save). save() здесь возвращает User, как ждёт
    стандартный flow `auth_login(request, user)`.
    """

    first_name = forms.CharField(
        required=True,
        max_length=150,
        label="Имя",
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        required=True,
        max_length=150,
        label="Фамилия",
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    birth_date = forms.DateField(
        required=True,
        label="Дата рождения",
        widget=forms.DateInput(attrs={"type": "date", "autocomplete": "bday"}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "birth_date")

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            # Сигнал post_save уже создал UserProfile с ролью engineer.
            # Дописываем туда дату рождения.
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.birth_date = self.cleaned_data.get("birth_date")
            profile.save(update_fields=["birth_date", "updated_at"])
        return user


class UserProfileEditForm(forms.Form):
    """Редактирование персональных данных и аватара. Роль сюда не входит —
    её меняет только admin через `/users/`. Поля имени/фамилии живут на User,
    дата рождения и аватар — на UserProfile, сохранение оба фиксирует."""

    first_name = forms.CharField(
        required=False,
        max_length=150,
        label="Имя",
        widget=forms.TextInput(attrs={"placeholder": "Например, Сергей"}),
    )
    last_name = forms.CharField(
        required=False,
        max_length=150,
        label="Фамилия",
        widget=forms.TextInput(attrs={"placeholder": "Например, Рубцов"}),
    )
    birth_date = forms.DateField(
        required=False,
        label="Дата рождения",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    avatar_key = forms.ChoiceField(
        required=True,
        choices=UserProfile.AVATAR_CHOICES,
        label="Аватар",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        initial = kwargs.pop("initial", None) or {}
        if user is not None:
            profile = getattr(user, "profile", None)
            initial.setdefault("first_name", user.first_name)
            initial.setdefault("last_name", user.last_name)
            if profile is not None:
                initial.setdefault("birth_date", profile.birth_date)
                initial.setdefault("avatar_key", profile.avatar_key)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def save(self) -> None:
        if self._user is None:
            raise RuntimeError("UserProfileEditForm.save вызван без user.")
        user = self._user
        cd = self.cleaned_data
        user.first_name = cd.get("first_name", "") or ""
        user.last_name = cd.get("last_name", "") or ""
        user.save(update_fields=["first_name", "last_name"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.birth_date = cd.get("birth_date") or None
        profile.avatar_key = cd.get("avatar_key") or "fox"
        profile.save(update_fields=["birth_date", "avatar_key", "updated_at"])


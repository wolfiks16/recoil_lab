from __future__ import annotations

import re
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from openpyxl import load_workbook

from .models import CalculationRun, MagneticBrakeConfig


class CalculationForm(forms.Form):
    name = forms.CharField(required=True, label="Название расчёта")
    input_file = forms.FileField(label="Файл характеристик Excel")

    mass = forms.FloatField(label="Масса")
    angle_deg = forms.FloatField(initial=70.0, label="Угол, град")
    v0 = forms.FloatField(initial=0.0, label="Начальная скорость")
    x0 = forms.FloatField(initial=0.0, label="Начальное перемещение")
    t_max = forms.FloatField(initial=0.15, label="Время расчёта")
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
    n = forms.IntegerField(label="n", required=False)
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

            if uploaded_file:
                parsed_points = self._parse_force_curve_file(uploaded_file)
                cleaned_data["parsed_force_curve_points"] = parsed_points
                cleaned_data["curve_file_provided"] = True
                cleaned_data["curve_source_brake_id"] = ""
            elif source_brake_id:
                try:
                    int(source_brake_id)
                except ValueError as exc:
                    raise ValidationError(
                        "Некорректный идентификатор исходной характеристики тормоза."
                    ) from exc

                cleaned_data["parsed_force_curve_points"] = None
                cleaned_data["curve_file_provided"] = False
                cleaned_data["curve_source_brake_id"] = source_brake_id
            else:
                raise ValidationError(
                    "Для тормоза, заданного графиком, необходимо загрузить Excel-файл характеристики F(v)."
                )

        return cleaned_data

    def _parse_force_curve_file(self, uploaded_file) -> list[dict]:
        self._validate_excel_extension(uploaded_file.name)

        try:
            uploaded_file.seek(0)
        except Exception:
            pass

        try:
            workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
        except Exception as exc:
            raise ValidationError(
                "Не удалось прочитать Excel-файл характеристики тормоза."
            ) from exc
        finally:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass

        try:
            sheet = workbook.active
            parsed_points = self._parse_force_curve_sheet(sheet)
        finally:
            workbook.close()

        return parsed_points

    def _validate_excel_extension(self, filename: str) -> None:
        suffix = Path(filename).suffix.lower()
        allowed = {".xlsx", ".xlsm", ".xltx", ".xltm"}
        if suffix not in allowed:
            raise ValidationError(
                "Поддерживаются только Excel-файлы форматов .xlsx, .xlsm, .xltx, .xltm."
            )

    def _parse_force_curve_sheet(self, sheet) -> list[dict]:
        parsed_points: list[dict] = []
        header_skipped = False

        for row_no, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            velocity_raw = row[0] if len(row) > 0 else None
            force_raw = row[1] if len(row) > 1 else None

            if self._is_empty_cell(velocity_raw) and self._is_empty_cell(force_raw):
                continue

            if self._is_empty_cell(velocity_raw) or self._is_empty_cell(force_raw):
                raise ValidationError(
                    f"Строка {row_no}: должны быть заполнены и скорость, и сила."
                )

            velocity = self._coerce_excel_number(velocity_raw)
            force = self._coerce_excel_number(force_raw)

            # Допускаем одну строку заголовков в начале файла
            if velocity is None or force is None:
                if not header_skipped and not parsed_points:
                    header_skipped = True
                    continue
                raise ValidationError(
                    f"Строка {row_no}: значения скорости и силы должны быть числами."
                )

            if velocity < 0:
                raise ValidationError(
                    f"Строка {row_no}: скорость не может быть отрицательной."
                )

            if force < 0:
                raise ValidationError(
                    f"Строка {row_no}: сила торможения не может быть отрицательной."
                )

            parsed_points.append(
                {
                    "order": len(parsed_points) + 1,
                    "velocity": velocity,
                    "force": force,
                }
            )

        if len(parsed_points) < 2:
            raise ValidationError(
                "Для графического тормоза необходимо минимум 2 точки."
            )

        velocities = [point["velocity"] for point in parsed_points]

        if len(set(velocities)) != len(velocities):
            raise ValidationError(
                "Скорости в характеристике тормоза не должны повторяться."
            )

        if velocities != sorted(velocities):
            raise ValidationError(
                "Скорости в характеристике тормоза должны быть строго возрастающими."
            )

        return parsed_points

    @staticmethod
    def _is_empty_cell(value) -> bool:
        return value is None or (isinstance(value, str) and value.strip() == "")

    @staticmethod
    def _coerce_excel_number(value) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            normalized = value.strip().replace(",", ".")
            if not normalized:
                return None
            try:
                return float(normalized)
            except ValueError:
                return None

        return None


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
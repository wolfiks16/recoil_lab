import re
from django import forms

from .models import CalculationRun


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
    gamma = forms.FloatField(label="gamma")
    delta = forms.FloatField(label="delta")
    xm = forms.FloatField(label="xm")
    ym = forms.FloatField(label="ym")
    dh1 = forms.FloatField(label="dh1")
    dh2 = forms.FloatField(label="dh2")
    dm = forms.FloatField(label="dm")
    n = forms.IntegerField(label="n")
    mu = forms.FloatField(label="mu")
    bz = forms.FloatField(label="bz")
    lya = forms.FloatField(initial=2.5, label="lya")
    wn0 = forms.FloatField(initial=1.0, label="wn0")


MagneticBrakeFormSet = forms.formset_factory(
    MagneticBrakeForm,
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
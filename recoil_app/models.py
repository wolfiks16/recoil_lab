from pathlib import Path

from django.db import models


def brake_curve_upload_to(instance, filename: str) -> str:
    run_part = f"run_{instance.run_id or 'unknown'}"
    brake_part = f"brake_{instance.index or 'x'}"

    original = Path(filename)
    stem = original.stem or "curve"
    suffix = original.suffix or ".xlsx"

    return f"brake_curves/{run_part}/{brake_part}/{stem}{suffix}"


class CalculationRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=200, unique=True, blank=False)
    input_file = models.FileField(upload_to="uploads/")

    mass = models.FloatField()
    angle_deg = models.FloatField(default=70.0)
    v0 = models.FloatField(default=0.0)
    x0 = models.FloatField(default=0.0)
    t_max = models.FloatField(default=0.15)
    dt = models.FloatField(default=1e-4)

    x_max = models.FloatField(null=True, blank=True)
    v_max = models.FloatField(null=True, blank=True)
    x_final = models.FloatField(null=True, blank=True)
    v_final = models.FloatField(null=True, blank=True)
    a_final = models.FloatField(null=True, blank=True)

    recoil_end_time = models.FloatField(null=True, blank=True)
    return_end_time = models.FloatField(null=True, blank=True)

    termination_reason = models.CharField(max_length=50, null=True, blank=True)
    spring_out_of_range = models.BooleanField(default=False)
    warnings_text = models.TextField(blank=True, default="")

    report_file = models.FileField(upload_to="reports/", null=True, blank=True)

    chart_x_t = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_a_t = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_x = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_fmag_v = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_secondary = models.FileField(upload_to="reports/", null=True, blank=True)

    chart_x_t_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_a_t_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_main_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_secondary_recoil = models.FileField(upload_to="reports/", null=True, blank=True)

    chart_x_t_return = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_a_t_return = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_secondary_return = models.FileField(upload_to="reports/", null=True, blank=True)

    class Meta:
        verbose_name = "Запуск расчёта"
        verbose_name_plural = "Запуски расчёта"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Расчёт #{self.pk}"


class CalculationSnapshot(models.Model):
    run = models.OneToOneField(
        CalculationRun,
        on_delete=models.CASCADE,
        related_name="snapshot",
    )
    model_version = models.CharField(max_length=32, default="2.0")
    input_snapshot = models.JSONField(default=dict, blank=True)
    result_snapshot = models.JSONField(default=dict, blank=True)
    analysis_snapshot = models.JSONField(default=dict, blank=True)
    thermal_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Снимок расчёта"
        verbose_name_plural = "Снимки расчётов"

    def __str__(self):
        return f"Снимок расчёта {self.run_id} (v{self.model_version})"


class MagneticBrakeConfig(models.Model):
    MODEL_TYPE_PARAMETRIC = "parametric"
    MODEL_TYPE_CURVE = "curve"

    MODEL_TYPE_CHOICES = [
        (MODEL_TYPE_PARAMETRIC, "Параметрический"),
        (MODEL_TYPE_CURVE, "По графику F(v)"),
    ]

    run = models.ForeignKey(
        CalculationRun,
        on_delete=models.CASCADE,
        related_name="brakes",
    )
    index = models.PositiveIntegerField()

    model_type = models.CharField(
        max_length=16,
        choices=MODEL_TYPE_CHOICES,
        default=MODEL_TYPE_PARAMETRIC,
    )
    name = models.CharField(max_length=255, blank=True, default="")
    curve_file = models.FileField(
        upload_to=brake_curve_upload_to,
        null=True,
        blank=True,
    )

    gamma = models.FloatField(null=True, blank=True)
    delta = models.FloatField(null=True, blank=True)
    xm = models.FloatField(null=True, blank=True)
    ym = models.FloatField(null=True, blank=True)
    dh1 = models.FloatField(null=True, blank=True)
    dh2 = models.FloatField(null=True, blank=True)
    dm = models.FloatField(null=True, blank=True)
    n = models.IntegerField(null=True, blank=True)
    mu = models.FloatField(null=True, blank=True)
    bz = models.FloatField(null=True, blank=True)

    lya = models.FloatField(default=2.5, null=True, blank=True)
    wn0 = models.FloatField(default=1.0, null=True, blank=True)

    class Meta:
        verbose_name = "Магнитный тормоз"
        verbose_name_plural = "Магнитные тормоза"
        ordering = ["run", "index"]
        unique_together = [("run", "index")]

    def __str__(self):
        return f"{self.display_name} для расчёта {self.run_id}"

    @property
    def display_name(self) -> str:
        return self.name or f"Тормоз {self.index}"


class BrakeForcePoint(models.Model):
    brake = models.ForeignKey(
        MagneticBrakeConfig,
        on_delete=models.CASCADE,
        related_name="force_points",
    )
    order = models.PositiveIntegerField(default=1)
    velocity = models.FloatField()
    force = models.FloatField()

    class Meta:
        verbose_name = "Точка характеристики тормоза"
        verbose_name_plural = "Точки характеристики тормоза"
        ordering = ["brake", "order", "id"]
        unique_together = [("brake", "order")]

    def __str__(self):
        return f"{self.brake.display_name}: v={self.velocity}, F={self.force}"
from django.db import models


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

    # Общие графики
    chart_x_t = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_a_t = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_x = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_fmag_v = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_secondary = models.FileField(upload_to="reports/", null=True, blank=True)

    # Фаза отката
    chart_x_t_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_v_a_t_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_main_recoil = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_forces_secondary_recoil = models.FileField(upload_to="reports/", null=True, blank=True)

    # Фаза наката
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
    run = models.ForeignKey(
        CalculationRun,
        on_delete=models.CASCADE,
        related_name="brakes",
    )
    index = models.PositiveIntegerField()

    gamma = models.FloatField()
    delta = models.FloatField()
    xm = models.FloatField()
    ym = models.FloatField()
    dh1 = models.FloatField()
    dh2 = models.FloatField()
    dm = models.FloatField()
    n = models.IntegerField()
    mu = models.FloatField()
    bz = models.FloatField()
    lya = models.FloatField(default=2.5)
    wn0 = models.FloatField(default=1.0)

    class Meta:
        verbose_name = "Параметры магнитного тормоза"
        verbose_name_plural = "Параметры магнитных тормозов"
        ordering = ["run", "index"]

    def __str__(self):
        return f"Тормоз {self.index} для расчёта {self.run_id}"
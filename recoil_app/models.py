from pathlib import Path

from django.conf import settings
from django.db import models


# ============================================================================
# Auth / роли пользователей
# ============================================================================


class UserProfile(models.Model):
    """Дополнительная информация о пользователе: роль в системе.

    Создаётся автоматически сигналом `post_save` на `auth.User`:
    - if user.is_superuser → role = admin
    - иначе → role = engineer (минимальные права)

    Роли:
        admin    — владелец платформы: видит и удаляет всё, раздаёт роли,
                   полный CRUD по каталогу.
        analyst  — инженер-аналитик: видит все расчёты, удаляет только свои,
                   копирует чужие, полный CRUD по каталогу. Прав на роли НЕТ.
        engineer — обычный инженер: видит и удаляет ТОЛЬКО свои расчёты;
                   в каталоге может использовать ВСЕ записи, но создавать
                   и редактировать ТОЛЬКО свои.
    """

    ROLE_ADMIN = "admin"
    ROLE_ANALYST = "analyst"
    ROLE_ENGINEER = "engineer"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Администратор"),
        (ROLE_ANALYST, "Инженер-аналитик"),
        (ROLE_ENGINEER, "Инженер"),
    ]

    # Аватары — мультяшные морды животных через Unicode emoji.
    # Ключ хранится в БД, эмодзи рендерится фронтом через словарь AVATAR_EMOJI.
    AVATAR_CHOICES = [
        ("fox",     "🦊 Лиса"),
        ("cat",     "🐱 Кот"),
        ("bear",    "🐻 Медведь"),
        ("rabbit",  "🐰 Кролик"),
        ("dog",     "🐶 Собака"),
        ("panda",   "🐼 Панда"),
        ("raccoon", "🦝 Енот"),
        ("wolf",    "🐺 Волк"),
        ("tiger",   "🐯 Тигр"),
        ("lion",    "🦁 Лев"),
        ("mouse",   "🐭 Мышь"),
        ("frog",    "🐸 Лягушка"),
    ]
    AVATAR_EMOJI = {
        "fox":     "🦊",
        "cat":     "🐱",
        "bear":    "🐻",
        "rabbit":  "🐰",
        "dog":     "🐶",
        "panda":   "🐼",
        "raccoon": "🦝",
        "wolf":    "🐺",
        "tiger":   "🐯",
        "lion":    "🦁",
        "mouse":   "🐭",
        "frog":    "🐸",
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=16,
        choices=ROLE_CHOICES,
        default=ROLE_ENGINEER,
    )
    avatar_key = models.CharField(
        max_length=16,
        choices=AVATAR_CHOICES,
        default="fox",
        help_text="Мультяшный аватар пользователя (мордочка животного).",
    )
    birth_date = models.DateField(
        null=True, blank=True,
        help_text="Дата рождения. Опциональное поле.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self) -> str:
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_analyst(self) -> bool:
        return self.role == self.ROLE_ANALYST

    @property
    def is_engineer(self) -> bool:
        return self.role == self.ROLE_ENGINEER

    @property
    def avatar_emoji(self) -> str:
        """Возвращает эмодзи-аватар по ключу (с фоллбэком на 🦊)."""
        return self.AVATAR_EMOJI.get(self.avatar_key, "🦊")


class BrakeParametersMixin(models.Model):
    """12 параметрических полей вихретокового тормоза.

    Используется обоими: `MagneticBrakeConfig` (тормоз конкретного расчёта)
    и `BrakeCatalog` (запись глобального каталога, copy-on-use).
    """

    gamma = models.FloatField(null=True, blank=True, help_text="Линейный коэффициент γ")
    delta = models.FloatField(null=True, blank=True, help_text="Квадратичный коэффициент δ")
    n = models.IntegerField(null=True, blank=True, help_text="Число секций")
    xm = models.FloatField(null=True, blank=True)
    ym = models.FloatField(null=True, blank=True)
    dh1 = models.FloatField(null=True, blank=True)
    dh2 = models.FloatField(null=True, blank=True)
    dm = models.FloatField(null=True, blank=True)
    mu = models.FloatField(null=True, blank=True)
    bz = models.FloatField(null=True, blank=True)
    lya = models.FloatField(default=2.5, null=True, blank=True)
    wn0 = models.FloatField(default=1.0, null=True, blank=True)

    class Meta:
        abstract = True


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
    # Владелец расчёта. Null допустим для legacy-расчётов (до введения auth),
    # но миграция назначает их первому суперпользователю; после миграции у новых
    # расчётов owner всегда заполнен (view ставит request.user).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calculation_runs",
    )

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

    # --- v2: новые графики для современного дизайна страницы результата ---
    chart_x_t_annotated = models.FileField(upload_to="reports/", null=True, blank=True)
    chart_energy = models.FileField(upload_to="reports/", null=True, blank=True)

    # --- v2: метрики энергобаланса (вытаскиваем из result для отображения в UI) ---
    energy_residual_pct = models.FloatField(null=True, blank=True)
    energy_input_total = models.FloatField(null=True, blank=True, help_text="Полная подведённая энергия, Дж")
    energy_brake_total = models.FloatField(null=True, blank=True, help_text="Полная рассеянная тормозами энергия, Дж")

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


class MagneticBrakeConfig(BrakeParametersMixin):
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


# ============================================================================
# СРЕЗ 3: Каталог тормозов
# ============================================================================

def catalog_curve_upload_to(instance, filename: str) -> str:
    """Путь для CSV/XLSX файла тормоза в каталоге."""
    safe = Path(filename)
    stem = safe.stem or "curve"
    suffix = safe.suffix or ".xlsx"
    return f"brake_catalog/curves/cat_{instance.pk or 'new'}/{stem}{suffix}"


class BrakeCatalog(BrakeParametersMixin):
    """Глобальная библиотека тормозов.

    Каждая запись — самостоятельная единица в каталоге, независимая от расчётов.
    При использовании в расчёте параметры КОПИРУЮТСЯ в MagneticBrakeConfig
    (copy-on-use), чтобы расчёт оставался воспроизводимым даже после редактирования
    исходной записи каталога.
    """

    MODEL_TYPE_PARAMETRIC = "parametric"
    MODEL_TYPE_CURVE = "curve"

    MODEL_TYPE_CHOICES = [
        (MODEL_TYPE_PARAMETRIC, "Параметрический"),
        (MODEL_TYPE_CURVE, "По графику F(v)"),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, default="")
    # Владелец записи каталога. admin/analyst могут редактировать любые,
    # engineer — только свои. Null для legacy записей (до auth).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="brake_catalog_entries",
    )

    model_type = models.CharField(
        max_length=16,
        choices=MODEL_TYPE_CHOICES,
        default=MODEL_TYPE_PARAMETRIC,
    )

    # Кривая F(v) — файл с табличной характеристикой
    curve_file = models.FileField(
        upload_to=catalog_curve_upload_to,
        null=True,
        blank=True,
        help_text="CSV/XLSX с двумя колонками: v, F",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Тормоз в каталоге"
        verbose_name_plural = "Каталог тормозов"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_parametric(self) -> bool:
        return self.model_type == self.MODEL_TYPE_PARAMETRIC

    @property
    def is_curve(self) -> bool:
        return self.model_type == self.MODEL_TYPE_CURVE

    @property
    def short_summary(self) -> str:
        """Короткое описание для отображения в списках."""
        if self.is_parametric:
            parts = []
            if self.gamma is not None:
                parts.append(f"γ={self.gamma:g}")
            if self.delta is not None:
                parts.append(f"δ={self.delta:g}")
            if self.n is not None:
                parts.append(f"n={self.n}")
            return " · ".join(parts) if parts else "параметрический"
        return "F(v) — табличная характеристика"


# ============================================================================
# Тепловой модуль: тепловой расчёт по готовому CalculationRun
# ============================================================================

def thermal_report_upload_to(instance, filename: str) -> str:
    """Папка для HTML-фрагментов и доп. артефактов теплового сценария."""
    folder = f"thermal_reports/run_{instance.run_id or 'x'}_thermal_{instance.pk or 'new'}"
    return f"{folder}/{filename}"


class ThermalRun(models.Model):
    """Один тепловой сценарий поверх готового CalculationRun.

    Тепловой расчёт не пересчитывает кинематику — он берёт готовые ряды t/v/F_brake
    из `CalculationSnapshot.result_snapshot` и интегрирует тепловую сеть.
    На один CalculationRun допускается несколько ThermalRun: разные материалы,
    режимы стрельбы, упрощённая или детальная сеть.
    """

    PRESET_NINE_NODE = "nine_node"
    PRESET_SINGLE_NODE = "single_node"
    PRESET_USER_SIMPLE = "user_simple"
    PRESET_CHOICES = [
        (PRESET_USER_SIMPLE, "Упрощённая (шина+магнитопровод, ручной ввод)"),
        (PRESET_NINE_NODE, "9-узловая сеть"),
        (PRESET_SINGLE_NODE, "Упрощённая (1 узел/тормоз)"),
    ]

    run = models.ForeignKey(
        CalculationRun,
        on_delete=models.CASCADE,
        related_name="thermal_runs",
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    network_preset = models.CharField(
        max_length=16,
        choices=PRESET_CHOICES,
        default=PRESET_NINE_NODE,
    )
    repetitions = models.PositiveIntegerField(default=1)
    pause_s = models.FloatField(default=0.0)

    # Денормализованные пики — нужны для списков, фильтрации и KPI на странице.
    max_temp_c = models.FloatField(null=True, blank=True)
    max_temp_node_name = models.CharField(max_length=120, blank=True, default="")
    total_heat_j = models.FloatField(null=True, blank=True)

    # Полные данные.
    config_snapshot = models.JSONField(default=dict, blank=True)
    result_snapshot = models.JSONField(default=dict, blank=True)
    warnings_text = models.TextField(blank=True, default="")

    # HTML-фрагменты Plotly, генерируемые в services.thermal.charting.
    chart_temperatures = models.FileField(upload_to=thermal_report_upload_to, null=True, blank=True)
    chart_power_brakes = models.FileField(upload_to=thermal_report_upload_to, null=True, blank=True)
    chart_heat_brakes = models.FileField(upload_to=thermal_report_upload_to, null=True, blank=True)
    chart_cycle_envelope = models.FileField(upload_to=thermal_report_upload_to, null=True, blank=True)

    class Meta:
        verbose_name = "Тепловой сценарий"
        verbose_name_plural = "Тепловые сценарии"
        ordering = ["-created_at"]
        unique_together = [("run", "name")]

    def __str__(self) -> str:
        return f"{self.name} ({self.run_id})"

    @property
    def report_folder(self) -> str:
        return f"thermal_reports/run_{self.run_id}_thermal_{self.pk}"
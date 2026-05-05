from django.contrib import admin

from .models import BrakeForcePoint, CalculationRun, CalculationSnapshot, MagneticBrakeConfig


class BrakeForcePointInline(admin.TabularInline):
    model = BrakeForcePoint
    extra = 0
    fields = ("order", "velocity", "force")
    ordering = ("order",)


class MagneticBrakeConfigInline(admin.StackedInline):
    model = MagneticBrakeConfig
    extra = 0
    ordering = ("index",)
    show_change_link = True
    fields = (
        ("index", "name", "model_type"),
        "curve_file",
        ("gamma", "delta"),
        ("xm", "ym"),
        ("dh1", "dh2"),
        ("dm", "n"),
        ("mu", "bz"),
        ("lya", "wn0"),
    )


class CalculationSnapshotInline(admin.StackedInline):
    model = CalculationSnapshot
    extra = 0
    can_delete = False
    readonly_fields = (
        "model_version",
        "input_snapshot",
        "result_snapshot",
        "analysis_snapshot",
        "thermal_snapshot",
        "created_at",
        "updated_at",
    )


@admin.register(CalculationRun)
class CalculationRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "created_at",
        "mass",
        "angle_deg",
        "x_max",
        "v_max",
        "recoil_end_time",
        "return_end_time",
        "termination_reason",
        "spring_out_of_range",
    )
    list_filter = (
        "created_at",
        "termination_reason",
        "spring_out_of_range",
    )
    search_fields = ("name",)
    ordering = ("-created_at",)
    inlines = [MagneticBrakeConfigInline, CalculationSnapshotInline]

    fieldsets = (
        (
            "Основные данные",
            {
                "fields": (
                    "name",
                    "created_at",
                    "input_file",
                )
            },
        ),
        (
            "Параметры расчёта",
            {
                "fields": (
                    "mass",
                    "angle_deg",
                    "v0",
                    "x0",
                    "t_max",
                    "dt",
                )
            },
        ),
        (
            "Результаты",
            {
                "fields": (
                    "x_max",
                    "v_max",
                    "x_final",
                    "v_final",
                    "a_final",
                    "recoil_end_time",
                    "return_end_time",
                )
            },
        ),
        (
            "Статус расчёта",
            {
                "fields": (
                    "termination_reason",
                    "spring_out_of_range",
                    "warnings_text",
                )
            },
        ),
        (
            "Отчёт",
            {
                "fields": (
                    "report_file",
                )
            },
        ),
        (
            "Общие графики",
            {
                "fields": (
                    "chart_x_t",
                    "chart_v_a_t",
                    "chart_v_x",
                    "chart_fmag_v",
                    "chart_forces_secondary",
                )
            },
        ),
        (
            "Графики фазы отката",
            {
                "fields": (
                    "chart_x_t_recoil",
                    "chart_v_a_t_recoil",
                    "chart_forces_main_recoil",
                    "chart_forces_secondary_recoil",
                )
            },
        ),
        (
            "Графики фазы наката",
            {
                "fields": (
                    "chart_x_t_return",
                    "chart_v_a_t_return",
                    "chart_forces_secondary_return",
                )
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "x_max",
        "v_max",
        "x_final",
        "v_final",
        "a_final",
        "recoil_end_time",
        "return_end_time",
        "termination_reason",
        "spring_out_of_range",
        "warnings_text",
        "report_file",
        "chart_x_t",
        "chart_v_a_t",
        "chart_v_x",
        "chart_fmag_v",
        "chart_forces_secondary",
        "chart_x_t_recoil",
        "chart_v_a_t_recoil",
        "chart_forces_main_recoil",
        "chart_forces_secondary_recoil",
        "chart_x_t_return",
        "chart_v_a_t_return",
        "chart_forces_secondary_return",
    )


@admin.register(CalculationSnapshot)
class CalculationSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run",
        "model_version",
        "created_at",
        "updated_at",
    )
    search_fields = ("run__name",)
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(MagneticBrakeConfig)
class MagneticBrakeConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run",
        "index",
        "display_name",
        "model_type",
        "curve_file",
        "gamma",
        "delta",
        "xm",
        "ym",
        "bz",
        "wn0",
    )
    list_filter = ("model_type", "index")
    search_fields = ("run__name", "name")
    ordering = ("run", "index")
    inlines = [BrakeForcePointInline]

    fieldsets = (
        (
            "Основные данные",
            {
                "fields": (
                    "run",
                    "index",
                    "name",
                    "model_type",
                    "curve_file",
                )
            },
        ),
        (
            "Параметрическая модель",
            {
                "fields": (
                    ("gamma", "delta"),
                    ("xm", "ym"),
                    ("dh1", "dh2"),
                    ("dm", "n"),
                    ("mu", "bz"),
                    ("lya", "wn0"),
                )
            },
        ),
    )


@admin.register(BrakeForcePoint)
class BrakeForcePointAdmin(admin.ModelAdmin):
    list_display = ("id", "brake", "order", "velocity", "force")
    list_filter = ("brake__model_type",)
    search_fields = ("brake__run__name", "brake__name")
    ordering = ("brake", "order")

from .models import BrakeCatalog  # noqa: E402


@admin.register(BrakeCatalog)
class BrakeCatalogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "model_type",
        "gamma",
        "delta",
        "n",
        "updated_at",
    )
    list_filter = ("model_type",)
    search_fields = ("name", "description")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Общее", {"fields": ("name", "description", "model_type")}),
        ("Параметрическая модель", {"fields": (("gamma", "delta", "n"),)}),
        ("Табличная модель", {"fields": ("curve_file",)}),
        (
            "Дополнительные параметры",
            {
                "classes": ("collapse",),
                "fields": (
                    ("xm", "ym"),
                    ("dh1", "dh2"),
                    ("dm", "mu", "bz"),
                    ("lya", "wn0"),
                ),
            },
        ),
        ("Метаданные", {"fields": ("created_at", "updated_at")}),
    )

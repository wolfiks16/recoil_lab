from django.contrib import admin

from .models import CalculationRun, MagneticBrakeConfig


class MagneticBrakeConfigInline(admin.TabularInline):
    model = MagneticBrakeConfig
    extra = 0
    ordering = ("index",)


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
    inlines = [MagneticBrakeConfigInline]

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


@admin.register(MagneticBrakeConfig)
class MagneticBrakeConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run",
        "index",
        "gamma",
        "delta",
        "xm",
        "ym",
        "bz",
        "wn0",
    )
    list_filter = ("index",)
    ordering = ("run", "index")
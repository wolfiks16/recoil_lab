# Generated for v2 design (energy balance + annotated x(t) chart)
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0016_magneticbrakeconfig_curve_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="calculationrun",
            name="chart_x_t_annotated",
            field=models.FileField(blank=True, null=True, upload_to="reports/"),
        ),
        migrations.AddField(
            model_name="calculationrun",
            name="chart_energy",
            field=models.FileField(blank=True, null=True, upload_to="reports/"),
        ),
        migrations.AddField(
            model_name="calculationrun",
            name="energy_residual_pct",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="calculationrun",
            name="energy_input_total",
            field=models.FloatField(
                blank=True,
                help_text="Полная подведённая энергия, Дж",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="calculationrun",
            name="energy_brake_total",
            field=models.FloatField(
                blank=True,
                help_text="Полная рассеянная тормозами энергия, Дж",
                null=True,
            ),
        ),
    ]

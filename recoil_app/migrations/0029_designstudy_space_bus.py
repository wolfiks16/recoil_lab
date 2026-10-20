from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0028_iterativecalc_finishing"),
    ]

    operations = [
        migrations.AddField(
            model_name="designstudy",
            name="param_space",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="designstudy",
            name="bus_length",
            field=models.FloatField(
                blank=True,
                help_text="Длина шины, м (у каждого тормоза своя); пусто — не ограничивать",
                null=True,
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0027_iterative_calc"),
    ]

    operations = [
        migrations.AlterField(
            model_name="iterativecalc",
            name="status",
            field=models.CharField(
                choices=[("active", "Идёт"), ("finishing", "Досчитывается"), ("finished", "Завершён")],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="iterativecalc",
            name="error_text",
            field=models.TextField(blank=True, default=""),
        ),
    ]

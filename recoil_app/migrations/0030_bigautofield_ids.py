"""id трёх моделей → BigAutoField (как у остальных) после явного DEFAULT_AUTO_FIELD.

Миграции 0026/0027 были написаны с AutoField. Пока DEFAULT_AUTO_FIELD не был задан,
makemigrations на Django 5 и Django 6 (где умолчание сменилось на BigAutoField)
предлагал разные «изменения id». Теперь тип задан явно, и все модели едины.
На SQLite оба типа — integer, данные не затрагиваются.
"""

from django.db import migrations, models


def _big_id():
    return models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0029_designstudy_space_bus"),
    ]

    operations = [
        migrations.AlterField(model_name="brakestage", name="id", field=_big_id()),
        migrations.AlterField(model_name="designstudy", name="id", field=_big_id()),
        migrations.AlterField(model_name="iterativecalc", name="id", field=_big_id()),
    ]

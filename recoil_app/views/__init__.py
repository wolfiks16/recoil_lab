"""Пакет views для recoil_app.

Разделён на модули по областям:
- `run`     — создание расчёта, страница результата, удаление
- `dashboard` — главный экран
- `compare` — страница сравнения
- `catalog` — каталог тормозов (5 страниц + AJAX)

Re-export сохраняет совместимость с `urls.py`, который ссылается на `views.<name>_view`.
"""

from .catalog import (  # noqa: F401
    catalog_delete_view,
    catalog_detail_view,
    catalog_edit_view,
    catalog_list_view,
    catalog_new_view,
    catalog_save_from_brake_form_view,
)
from .compare import compare_view  # noqa: F401
from .dashboard import dashboard_view  # noqa: F401
from .results import results_view  # noqa: F401
from .run import delete_run_view, index_view, run_detail_v2_view  # noqa: F401
from .thermal import (  # noqa: F401
    thermal_delete_view,
    thermal_detail_view,
    thermal_list_view,
    thermal_new_view,
)

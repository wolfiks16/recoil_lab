"""Пакет views для recoil_app.

Разделён на модули по областям:
- `run`     — создание расчёта, страница результата, удаление
- `dashboard` — главный экран
- `compare` — страница сравнения
- `catalog` — каталог тормозов (5 страниц + AJAX)

Re-export сохраняет совместимость с `urls.py`, который ссылается на `views.<name>_view`.
"""

from .auth import (  # noqa: F401
    profile_view,
    register_view,
    users_list_view,
    users_set_role_view,
)
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
from .iterative import (  # noqa: F401
    iterative_action_view,
    iterative_clone_view,
    iterative_delete_view,
    iterative_detail_view,
    iterative_list_view,
    iterative_new_view,
    iterative_reset_view,
    iterative_status_view,
)
from .optimize import (  # noqa: F401
    optimize_delete_view,
    optimize_detail_view,
    optimize_list_view,
    optimize_new_view,
    optimize_spawn_view,
    optimize_status_view,
)
from .results import results_view  # noqa: F401
from .run import (  # noqa: F401
    delete_run_view,
    free_fall_new_view,
    index_view,
    run_detail_v2_view,
)
from .thermal import (  # noqa: F401
    thermal_copy_view,
    thermal_delete_view,
    thermal_detail_view,
    thermal_export_view,
    thermal_list_view,
    thermal_new_view,
)

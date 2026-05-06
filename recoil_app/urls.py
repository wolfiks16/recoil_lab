from django.urls import path
from . import views

urlpatterns = [
    # Главная — новый дашборд (Срез 2)
    path("", views.dashboard_view, name="dashboard"),
    # Форма создания нового расчёта (раньше была главной).
    # Имя `index` сохраняется ради обратной совместимости с многочисленными {% url 'index' %}
    # в шаблонах (включая редиректы после создания и кнопки «Скопировать»).
    path("new/", views.index_view, name="index"),
    # Каталог расчётов (список с поиском/фильтрами/пагинацией) — раньше жил на дашборде.
    path("results/", views.results_view, name="results"),
    # Детали расчёта
    path("run/<int:run_id>/", views.run_detail_v2_view, name="run_detail_v2"),
    path("run/<int:run_id>/delete/", views.delete_run_view, name="delete_run"),
    # Сравнение
    path("compare/", views.compare_view, name="compare"),

    # Каталог тормозов (Срез 3a + 3c)
    path("catalog/", views.catalog_list_view, name="catalog_list"),
    path("catalog/new/", views.catalog_new_view, name="catalog_new"),
    path("catalog/<int:pk>/", views.catalog_detail_view, name="catalog_detail"),
    path("catalog/<int:pk>/edit/", views.catalog_edit_view, name="catalog_edit"),
    path("catalog/<int:pk>/delete/", views.catalog_delete_view, name="catalog_delete"),

    # AJAX: сохранить тормоз из формы расчёта в каталог (Срез 4)
    path("catalog/save-from-form/", views.catalog_save_from_brake_form_view, name="catalog_save_from_form"),

    # Тепловой модуль
    path("run/<int:run_id>/thermal/", views.thermal_list_view, name="thermal_list"),
    path("run/<int:run_id>/thermal/new/", views.thermal_new_view, name="thermal_new"),
    path("run/<int:run_id>/thermal/<int:thermal_id>/", views.thermal_detail_view, name="thermal_detail"),
    path("run/<int:run_id>/thermal/<int:thermal_id>/delete/", views.thermal_delete_view, name="thermal_delete"),
]

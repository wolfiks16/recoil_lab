from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views

urlpatterns = [
    # --- Аутентификация ---
    path(
        "login/",
        LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path("users/", views.users_list_view, name="users_list"),
    path("users/<int:user_id>/role/", views.users_set_role_view, name="users_set_role"),

    # Главная — рабочий стол
    path("", views.dashboard_view, name="dashboard"),
    # AJAX: фоновые задачи пользователя (индикатор в верхней строке)
    path("tasks/status/", views.background_tasks_view, name="background_tasks"),
    # Форма создания нового расчёта (раньше была главной).
    # Имя `index` сохраняется ради обратной совместимости с многочисленными {% url 'index' %}
    # в шаблонах (включая редиректы после создания и кнопки «Скопировать»).
    path("new/", views.index_view, name="index"),
    # Свободное падение — отдельная вкладка (без входного файла, время не ограничено).
    path("free-fall/new/", views.free_fall_new_view, name="free_fall_new"),
    # Каталог расчётов (список с поиском/фильтрами/пагинацией) — раньше жил на дашборде.
    path("results/", views.results_view, name="results"),
    # Детали расчёта
    path("run/<int:run_id>/", views.run_detail_v2_view, name="run_detail_v2"),
    path("run/<int:run_id>/delete/", views.delete_run_view, name="delete_run"),
    # Вторичные графики страницы результата — догружаются по мере прокрутки
    path("run/<int:run_id>/chart/<str:key>/", views.run_chart_view, name="run_chart"),
    # Сравнение
    path("compare/", views.compare_view, name="compare"),

    # Оптимизация / обратное проектирование (DesignStudy)
    path("optimize/", views.optimize_list_view, name="optimize_list"),
    path("optimize/new/", views.optimize_new_view, name="optimize_new"),
    path("optimize/<int:study_id>/", views.optimize_detail_view, name="optimize_detail"),
    path("optimize/<int:study_id>/status/", views.optimize_status_view, name="optimize_status"),
    path("optimize/<int:study_id>/spawn/", views.optimize_spawn_view, name="optimize_spawn"),
    path("optimize/<int:study_id>/delete/", views.optimize_delete_view, name="optimize_delete"),

    # Итерационный расчёт с перестройкой тормозов (Срез 12)
    path("iterative/", views.iterative_list_view, name="iterative_list"),
    path("iterative/new/", views.iterative_new_view, name="iterative_new"),
    path("iterative/<int:calc_id>/", views.iterative_detail_view, name="iterative_detail"),
    path("iterative/<int:calc_id>/action/", views.iterative_action_view, name="iterative_action"),
    path("iterative/<int:calc_id>/status/", views.iterative_status_view, name="iterative_status"),
    path("iterative/<int:calc_id>/reset/", views.iterative_reset_view, name="iterative_reset"),
    path("iterative/<int:calc_id>/clone/", views.iterative_clone_view, name="iterative_clone"),
    path("iterative/<int:calc_id>/delete/", views.iterative_delete_view, name="iterative_delete"),

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
    path("run/<int:run_id>/thermal/<int:thermal_id>/export.xlsx", views.thermal_export_view, name="thermal_export"),
    path("run/<int:run_id>/thermal/<int:thermal_id>/copy/", views.thermal_copy_view, name="thermal_copy"),
    path("run/<int:run_id>/thermal/<int:thermal_id>/delete/", views.thermal_delete_view, name="thermal_delete"),
]

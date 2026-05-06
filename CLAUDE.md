# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RecoilLab — Django 6.0.3 приложение для инженерного расчёта откатной системы орудия с одним или несколькими вихретоковыми (магнитными) тормозами. Соавтор: Васильченко С.В.

Стек: Python 3.11+, Django 6.0.3, SQLite, NumPy 2.4, SciPy 1.17, Plotly 6.6, OpenPyXL 3.1, pandas 3.0.

## Commands

Запуск (Windows, bash через Claude Code — пути в Unix-стиле):

```bash
# По умолчанию manage.py использует settings.dev — обычные команды работают как раньше:
python manage.py runserver
python manage.py migrate
python manage.py makemigrations
python manage.py makemigrations --dry-run        # проверка без записи
python manage.py check                           # проверка проекта
python manage.py createsuperuser
python manage.py collectstatic                   # для prod (отдаётся nginx'ом)
python manage.py test                            # Django test runner (tests.py пока пуст)
python manage.py test recoil_app.tests.SomeTest.test_method   # один тест

# Проверка production-настроек (на Windows только check, runserver не нужен):
DJANGO_SETTINGS_MODULE=recoil_project.settings.prod python manage.py check --deploy
```

**Обязательно после любого изменения моделей или views**: `python manage.py check` и `python manage.py makemigrations --dry-run`.

## Architecture

### Поток создания расчёта

`index_view` (POST на `/new/`, реализован в `views/run.py`) выполняет всё синхронно внутри одной `transaction.atomic()`:

1. Валидация `CalculationForm` + `MagneticBrakeFormSet` (formset, prefix=`brakes`).
2. `services.run_pipeline.resolve_curve_sources(brake_formset)` — для curve-тормозов разрешает источник F(v): загруженный файл, копия из ранее сохранённого `MagneticBrakeConfig`, или копия из `BrakeCatalog` (copy-on-use).
3. `services.run_pipeline.create_brake_objects_and_runtime_models` создаёт `MagneticBrakeConfig` + `BrakeForcePoint` и параллельно собирает runtime-модели для симулятора (`MagneticParams` или `CurveBrakeParams`).
4. `simulate_recoil(input_file_path, RecoilParams, runtime_brakes)` — RK4-интегрирование `(x, v)` с шагом `dt`, обнаружение момента разворота через линейную интерполяцию `v=0` и завершения цикла через интерполяцию `x=0`. Внутри вызывается `compute_energy_balance` (трапециевидное интегрирование E_кин, E_пруж, E_торм_накоп, E_вход_накоп, относительная невязка в %).
5. `save_interactive_charts(result, run_reports_dir, prefix)` — все Plotly-графики как HTML-фрагменты (`include_plotlyjs=False`) в `media/reports/<safe_name>_<id>/`.
6. `export_results_to_excel(result, report_path)` — XLSX-отчёт.
7. `build_calculation_model` + `enrich_with_basic_analysis` → `CalculationSnapshot.update_or_create` (input/result/analysis snapshots в JSON).
8. Редирект на `run_detail_v2` (`/run/<id>/`).

### Layout

Только один дизайн — все шаблоны наследуют `base_v2.html`. Старый `base.html` / `run_detail.html` / `style.css` / 7 includes/* удалены при рефакторинге (Pass 2). URL `index` сохранён ради обратной совместимости с многочисленными `{% url 'index' %}` и теперь указывает на `/new/`.

### URL'ы (`recoil_app/urls.py`)

```
/                       → dashboard_view (имя 'dashboard')
/new/                   → index_view (имя 'index' — backward-compat для шаблонов)
/run/<id>/              → run_detail_v2_view (имя 'run_detail_v2')
/run/<id>/delete/       → delete_run_view (POST)
/compare/               → compare_view
/catalog/               → catalog_list_view
/catalog/new/           → catalog_new_view
/catalog/<pk>/          → catalog_detail_view
/catalog/<pk>/edit/     → catalog_edit_view
/catalog/<pk>/delete/   → catalog_delete_view (POST)
/catalog/save-from-form/ → catalog_save_from_brake_form_view (AJAX POST)
```

### Пакет views (`recoil_app/views/`)

Раздроблен на тематические модули; `__init__.py` re-export'ит всё, чтобы `urls.py` ссылался на `views.<name>_view` без изменений.

- `views/run.py` — `index_view`, `run_detail_v2_view`, `delete_run_view`. + private `_read_chart_fragment`.
- `views/dashboard.py` — `dashboard_view` (stat-карточки, фильтр, поиск, пагинация).
- `views/compare.py` — `compare_view` (тонкий, всё в `services/compare_data.py`).
- `views/catalog.py` — 5 catalog views + AJAX `catalog_save_from_brake_form_view`.

### Слой services (`recoil_app/services/`)

**Доменные:**
- `dynamics.py` — `RecoilParams`, `SimulationResult` (с energy fields), `simulate_recoil`, `compute_energy_balance`. Симулятор синхронный, чистый NumPy.
- `magnetic.py` — `MagneticParams` (parametric), `CurveBrakeParams` + `ForceCurvePoint` (табличный F(v)), `evaluate_brake_force_si`, `initial_brake_state`. Формула параметрической модели: `F_T = (B̄₃·k̄_B·Ȳ_a)² · V · [2θ_κ/R_κ + 4(2N-1)θ_y/R_y]`.
- `io_utils.py` — `load_recoil_characteristics(xlsx_path)`. Входной файл расчёта — Excel с двумя обязательными листами:
  - `сила от времени` — колонки `t (с)`, `F (кН)` (умножается на 1000)
  - `сила от перемещения` — колонки `X (м)`, `F (кН)` (берётся `abs`, умножается на 1000)
- `interpolation.py` — `LinearTailPchip`, `prepare_monotonic_nodes`.
- `analysis.py` — `enrich_with_basic_analysis` → `phase_analysis`, `characteristic_points`, `engineering_metrics`.
- `modeling.py` — `build_calculation_model` + dataclass'ы для snapshot'ов (`MODEL_VERSION = "2.0"`).
- `reporting.py` — `export_results_to_excel`.
- `charting.py` — все Plotly-графики (см. ниже).

**Вспомогательные (выделены при рефакторинге, Pass 3-4):**
- `curve_parser.py` — `parse_force_curve_file(uploaded)` / `parse_force_curve_sheet(sheet)`. Раньше жил методом на `MagneticBrakeForm`. Используется и в `forms.clean()`, и во `views/catalog.py` (детальная страница), и в `run_pipeline` (copy-on-use из каталога).
- `run_pipeline.py` — бизнес-логика создания расчёта: `build_initial_from_run`, `resolve_curve_sources`, `create_brake_objects_and_runtime_models` + private хелперы.
- `kpi.py` — `build_kpi_groups(run, snapshot_parts)` для страницы результата + `kpi_format(value)` (диапазонное форматирование, отличается от templatetag `smart_num` — не путать).
- `snapshot.py` — `extract_snapshot_parts(run)` (для KPI/сравнения) и `extract_overlay_data(run)` (для overlay-графиков).
- `compare_data.py` — `build_compare_overlay_charts(run_a, run_b)` (4 фрагмента Plotly) + `build_compare_metrics_table(...)` (дельта-таблица 12 метрик).

### Модели (`recoil_app/models.py`)

- **`BrakeParametersMixin`** — abstract base model с 12 параметрическими полями вихретокового тормоза (`gamma`, `delta`, `n`, `xm`, `ym`, `dh1`, `dh2`, `dm`, `mu`, `bz`, `lya`, `wn0`). Наследуется и `MagneticBrakeConfig`, и `BrakeCatalog` — одно место правды для параметров. Введён в Pass 5 (миграция `0019`).
- **`CalculationRun`** — главный объект. ~15 FileField'ов под HTML-фрагменты графиков (общие, фаза отката `_recoil`, фаза наката `_return`, v2-специфичные `_annotated`/`_energy`). Поля энергобаланса: `energy_residual_pct`, `energy_input_total`, `energy_brake_total`. Имя расчёта валидируется regex `[A-Za-z0-9_-]+` и должно быть уникально.
- **`CalculationSnapshot`** (One-to-One) — `input_snapshot`/`result_snapshot`/`analysis_snapshot`/`thermal_snapshot` как JSONField. Хранит `timeline.t/x/v/a`, `forces.magnetic_sum`, `phases.recoil/return.end_time/end_index` — это и есть источник данных для overlay-графиков сравнения.
- **`MagneticBrakeConfig`** (наследует `BrakeParametersMixin`) — параметры тормоза для конкретного `CalculationRun` (`unique_together = (run, index)`). Тип `parametric` или `curve`.
- **`BrakeForcePoint`** — точки кривой F(v) для curve-тормоза.
- **`BrakeCatalog`** (наследует `BrakeParametersMixin`) — глобальный каталог тормозов. **Copy-on-use**: при использовании в расчёте параметры/файл копируются в `MagneticBrakeConfig`, чтобы расчёт оставался воспроизводимым после редактирования каталога.
- **`ThermalRun`** (FK→`CalculationRun`, `unique_together=(run, name)`) — отдельный тепловой сценарий поверх готового расчёта. Хранит `network_preset` (`nine_node`/`single_node`), `repetitions`, `pause_s`, два JSON-снапшота (`config_snapshot` с полной сетью + геометрией + материалами, `result_snapshot` с decimated timeline + cycle table + peaks) и 4 FileField'а под HTML-фрагменты Plotly. Денормализованные `max_temp_c`/`max_temp_node_name`/`total_heat_j` — для KPI и фильтрации списка. Каскадно удаляется с `CalculationRun`; файлы и папка `media/thermal_reports/run_<rid>_thermal_<tid>/` чистятся через `post_delete` сигнал в [signals.py](recoil_app/signals.py).

### Тепловой модуль (`services/thermal/`, страницы `/run/<id>/thermal/`)

Кинематика **не пересчитывается** — берётся `t/v/f_magnetic_each` из `CalculationSnapshot.result_snapshot.timeline/forces`. Это значит: для тепла нужен расчёт со snapshot'ом (новые расчёты — ок, архивные могут не иметь — view вернёт ошибку).

- [services/thermal/materials.py](recoil_app/services/thermal/materials.py) — справочник из 7 материалов (ρ/cp/ε). Степень черноты в форму НЕ выводится — берётся по материалу.
- [services/thermal/network.py](recoil_app/services/thermal/network.py) — `ThermalNode`/`ThermalLink`/`ThermalSource`/`ThermalNetwork` (dataclass'ы с валидацией). `linearized_radiation_h(T, T_amb, ε)` — для подмешивания излучения в G_amb на каждом шаге.
- [services/thermal/geometry.py](recoil_app/services/thermal/geometry.py) — `BrakeGeometry`/`AssemblyGeometry`. Backend получает все размеры явно (без fallback'ов «если 0 — взять из brake params» — это задача UI через кнопку «↓ Подставить»). Два пресета сети: `build_nine_node_network` (требует ровно 2 тормоза) и `build_single_node_network` (любое количество).
- [services/thermal/integrator.py](recoil_app/services/thermal/integrator.py) — **неявный Эйлер** с линеаризованным излучением. `solve_active_phase` интегрирует по готовой сетке (источник Q явно, T неявно — IMEX). `solve_cooling` для пауз с **адаптивным шагом** `dt = clamp(0.1·τ_min, 1ms, 0.5s)`. Численно проверено: сходимость 1-го порядка по dt, сохранение энергии до машинной точности.
- [services/thermal/cycles.py](recoil_app/services/thermal/cycles.py) — `simulate_repeated_cycles` реплицирует базовую фазу N раз с паузами. Последний цикл идёт без паузы (как в teplo v3). Возвращает `CombinedCycleResult` с глобальным timeline и `CycleSummary` по каждому циклу.
- [services/thermal/decimation.py](recoil_app/services/thermal/decimation.py) — урезание до ~100 Гц по сегментам, с обязательным сохранением точек пиков и границ цикл/пауза.
- [services/thermal/snapshot.py](recoil_app/services/thermal/snapshot.py) — упаковка в JSON для `ThermalRun`. После decimation result_snapshot ~ 500 КБ для 10 циклов.
- [services/thermal/charting.py](recoil_app/services/thermal/charting.py) — 4 Plotly-фрагмента: T(t) узлов, P_brake(t), Q_накопл(t), огибающая по циклам. Использует общие хелперы `_apply_layout` + расширенная палитра `NODE_PALETTE` для 9 узлов. **Не плодить свои палитры.**

### Срезы редизайна (история)

Реализовано последовательно, нарушать архитектуру нельзя:
1. Result Page v2 (`/run/<id>/v2/`) + энергобаланс
2. Дашборд на `/`, форма расчёта переехала на `/new/`
3. Каталог тормозов (`/catalog/`)
4. CAD-форма расчёта (3-панельная), AJAX «Сохранить в каталог»
5. Страница сравнения (`/compare/`) с overlay и дельта-таблицей
6. UX-полировка формы: HTML5-валидация (mass>0, 0≤angle≤90, v0≥0, x0≥0, 0<t_max≤10) + индикаторы заполненности тормозов в sidebar (✓ ⚠ ○ ✗)
7. Production-конфигурация: split-settings + .env + gunicorn + nginx (см. `deploy/`)
8. Тепловой модуль: отдельная сущность `ThermalRun`, неявный Эйлер по 9-узловой/упрощённой сети, формы с авто-геометрией через prefill-кнопку, 4 графика (T/P/Q/огибающая по циклам), страницы `/run/<id>/thermal/{,/new/,/<id>/}`. Кинематика берётся из готового снапшота — не пересчитывается.

После Срезов 1–7 проведён большой рефакторинг (6 пассов): удалён legacy, разделён `views.py` на пакет, выделены сервисы, abstract base mixin, inline CSS/JS вынесены в файлы.

### Файловое хранилище

- `media/uploads/` — входные Excel-файлы расчётов
- `media/reports/<safe_name>_<id>/` — HTML-фрагменты Plotly + XLSX-отчёт. Папка создаётся при расчёте, удаляется через `delete_run_view` (`shutil.rmtree`).
- `media/brake_curves/run_<id>/brake_<idx>/` — curve-файлы тормозов конкретного расчёта
- `media/brake_catalog/curves/cat_<id>/` — curve-файлы записей каталога
- `media/thermal_reports/run_<rid>_thermal_<tid>/` — HTML-фрагменты Plotly теплового сценария. Чистятся в `post_delete` сигнале на `ThermalRun`.

## Project conventions (обязательно соблюдать)

1. **Все новые графики — через хелперы из `recoil_app/services/charting.py`**: `_apply_layout`, `_add_peak_marker`, `_add_recoil_vline`, `_make_dual_axis_figure`. Цвета — константы `RB_BLUE` (`#3D73EB`), `RB_ACCENT` (`#B44D7A`), `RB_GREEN`, `RB_AMBER`, `LINE_WIDTH_PRIMARY=3.0`. Шрифты — `FONT_FAMILY_UI` (Manrope), `FONT_FAMILY_MONO` (JetBrains Mono). Для overlay в сравнении — `_CMP_COLOR_A`/`_CMP_COLOR_B`. **Не плодить новые палитры.**
2. **Все новые шаблоны наследуют `base_v2.html`**.
3. **Числовые значения в UI — через фильтры `smart_num` или `fmt5`** из `recoil_app/templatetags/recoil_extras.py`. `floatformat:N` допускается только для случаев осознанной фиксированной точности (например, `mass|floatformat:1` в боковой таблице параметров — иначе `smart_num` выведет полную точность из БД, что некрасиво).
4. **Любые изменения схемы — миграцией** (`makemigrations` → `migrate`). Не редактировать уже применённые миграции (на момент написания их 20, последняя `0020_thermalrun`). Новые поля моделей делать `null=True, blank=True`, чтобы миграция была безопасна для существующих записей.
5. **Бизнес-логика — в `services/`, не во view'хах.** View должен только: распарсить запрос, вызвать сервис, отрендерить шаблон. Если функция начинает делать что-то «доменное» (создавать модели, считать KPI, парсить файлы) — её место в `services/<area>.py`.
6. **Перед большими изменениями — согласовать план с пользователем**, не ломиться в код.

## Gotchas

- **Шаблоны живут в `templates/` в корне проекта**, не в `recoil_app/templates/`. `TEMPLATES.DIRS = [BASE_DIR / 'templates']` в settings.
- **`run_detail_v2_view` рендерит fallback'ы для архивных расчётов**: если у `CalculationRun` нет `chart_x_t_annotated` или `chart_energy` (расчёт сделан до Среза 1), страница работает на старых полях. Проверки через `has_annotated`/`has_energy`/`has_x_t` в context.
- **Энергобаланс может быть пустым** для расчётов короче 2 точек или для архивных записей — UI это переносит (`if run.energy_residual_pct is not None`).
- **`recoil_end_time` интерполируется** по линейной интерполяции момента, когда `v` пересекает 0. `recoil_end_index` — индекс последней точки до пересечения.
- **`spring_force_signed` всегда направлена к `x=0`**; знак возвращается из абсолютного `spring_force(abs(x))`. Если симулятор выходит за табличный диапазон пружины — выставляется флаг `spring_out_of_range`, добавляется warning, но расчёт продолжается.
- **AJAX `catalog_save_from_form`** принимает form-encoded POST, не JSON. URL читается из `data-catalog-save-url` на `<form id="calculation-form">`.
- **`compare_view` использует `result_snapshot.timeline`**, а не графики на диске. Для расчётов без snapshot'а overlay будет пустым.
- **Тепловой модуль тоже зависит от `result_snapshot.timeline/forces`** — для архивных расчётов без snapshot'а `thermal_new_view` поднимет `ValueError`. Чтобы починить — пересоздать расчёт.
- **9-узловая сеть требует ровно 2 тормоза** (`build_nine_node_network` поднимает ValueError иначе). Для 1, 3, 4+ тормозов используется `single_node` пресет. Форма блокирует выбор 9-узловой через `clean()`.
- **`MagneticBrakeConfig` и `BrakeCatalog` делят 12 параметрических полей** через `BrakeParametersMixin`. Если добавлять новый параметр тормоза — добавляй в mixin, а не в каждую модель.
- **Settings разделены** на пакет `recoil_project/settings/`: `base.py` (общее), `dev.py` (DEBUG=True, локальный SQLite, `django-insecure` SECRET_KEY), `prod.py` (DEBUG=False, всё из `.env`, `CSRF_TRUSTED_ORIGINS`, `SILENCED_SYSTEM_CHECKS` для HTTPS-warnings — деплой по HTTP). `manage.py` по умолчанию указывает на `settings.dev`, `wsgi.py`/`asgi.py` — на `settings.prod`.
- **`.env`** в корне проекта (gitignored). `django-environ` читает в `base.py` через `read_env(BASE_DIR / ".env")`. Шаблон в [`.env.example`](.env.example).
- **Деплой-конфиги** в `deploy/`: [`gunicorn.service`](deploy/gunicorn.service) (systemd unit, Unix socket `/run/recoil.sock`), [`nginx.conf`](deploy/nginx.conf) (proxy + static + media, `client_max_body_size 25M`, `proxy_read_timeout 300s` для долгих расчётов), [`deploy/README.md`](deploy/README.md) — пошаговая инструкция установки.
- **`requirements.txt`** в UTF-8 (был UTF-16 LE с BOM, артефакт PowerShell — пересохранён при Срезе 7).
- **Бэкапы** (Срез 7c) пока не сделаны — отложено до запроса.

## Static / templatetags

- `recoil_app/static/recoil_app/css/design_system.css` — единая дизайн-система (~1800 строк): палитра, KPI-карточки, типографика, layout shell.
- `recoil_app/static/recoil_app/css/calc_form.css` — стили формы создания расчёта (вынесены из inline `<style>` шаблона при Pass 6).
- `recoil_app/static/recoil_app/js/shell.js` — топбар и левый rail; вставляется в `base_v2.html` декларативно через `data-*` атрибуты.
- `recoil_app/static/recoil_app/js/modules.js` — управление видимостью модулей на странице результата.
- `recoil_app/static/recoil_app/js/calc_form.js` — formset, индикаторы заполненности, AJAX «в каталог», submit + loader (вынесен из inline `<script>` шаблона при Pass 6).
- `recoil_app/static/recoil_app/js/thermal_form.js` — управление видимостью полей при смене preset'а сети, prefill-кнопки «↓ Подставить из brake params» (только для parametric-тормозов).
- `recoil_app/templatetags/recoil_extras.py` — `fmt5` (5 знаков), `smart_num` (умное форматирование), `index_or` (для индексации в шаблоне с formset'ом), `json_script_data` (безопасная сериализация в `<script type="application/json">`).

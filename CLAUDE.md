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

`requirements.txt` сохранён в **UTF-16 LE с BOM** (артефакт Windows). При правке учитывать кодировку, иначе Read/Edit увидит «битые» символы.

## Architecture

### Поток создания расчёта

`index_view` (POST на `/new/`) выполняет всё синхронно внутри одной `transaction.atomic()`:

1. Валидация `CalculationForm` + `MagneticBrakeFormSet` (formset, prefix=`brakes`).
2. `_resolve_curve_sources(brake_formset)` — для curve-тормозов разрешает источник F(v): загруженный файл, копия из ранее сохранённого `MagneticBrakeConfig`, или копия из `BrakeCatalog` (copy-on-use).
3. `_create_brake_objects_and_runtime_models` создаёт `MagneticBrakeConfig` + `BrakeForcePoint` и параллельно собирает runtime-модели для симулятора (`MagneticParams` или `CurveBrakeParams`).
4. `simulate_recoil(input_file_path, RecoilParams, runtime_brakes)` — RK4-интегрирование `(x, v)` с шагом `dt`, обнаружение момента разворота через линейную интерполяцию `v=0` и завершения цикла через интерполяцию `x=0`. Внутри вызывается `compute_energy_balance` (трапециевидное интегрирование E_кин, E_пруж, E_торм_накоп, E_вход_накоп, относительная невязка в %).
5. `save_interactive_charts(result, run_reports_dir, prefix)` — все Plotly-графики как HTML-фрагменты (`include_plotlyjs=False`) в `media/reports/<safe_name>_<id>/`.
6. `export_results_to_excel(result, report_path)` — XLSX-отчёт.
7. `build_calculation_model` + `enrich_with_basic_analysis` → `CalculationSnapshot.update_or_create` (input/result/analysis snapshots в JSON).
8. Редирект на `run_detail` (старая версия). Новая версия страницы — `run_detail_v2`, ссылка из старой через кнопку «★ Новый дизайн».

### Двойной layout (важно!)

В проекте сосуществуют **два дизайна**, нельзя их смешивать:

| Старое | Новое (срезы 1–5, обязательное для нового кода) |
|---|---|
| `templates/recoil_app/base.html` | `templates/recoil_app/base_v2.html` |
| `/` → форма расчёта (была) | `/` → дашборд (`dashboard_view`) |
| `/run/<id>/` → `run_detail` | `/run/<id>/v2/` → `run_detail_v2` (KPI-группы, энергобаланс, табы графиков) |
| `templates/recoil_app/run_detail.html` | `templates/recoil_app/run_detail_v2.html` |

URL `index` сохранён ради обратной совместимости (множество `{% url 'index' %}` в шаблонах) и теперь указывает на `/new/` (форма).

### Слой services (`recoil_app/services/`)

- `dynamics.py` — `RecoilParams`, `SimulationResult` (с energy fields), `simulate_recoil`, `compute_energy_balance`. Симулятор синхронный, чистый NumPy.
- `magnetic.py` — `MagneticParams` (parametric), `CurveBrakeParams` + `ForceCurvePoint` (табличный F(v)), `evaluate_brake_force_si`, `initial_brake_state`. Формула параметрической модели: `F_T = (B̄₃·k̄_B·Ȳ_a)² · V · [2θ_κ/R_κ + 4(2N-1)θ_y/R_y]`.
- `io_utils.py` — `load_recoil_characteristics(xlsx_path)`. Входной файл расчёта — Excel с двумя обязательными листами:
  - `сила от времени` — колонки `t (с)`, `F (кН)` (умножается на 1000)
  - `сила от перемещения` — колонки `X (м)`, `F (кН)` (берётся `abs`, умножается на 1000)
- `interpolation.py` — `LinearTailPchip`, `prepare_monotonic_nodes`.
- `charting.py` — все Plotly-графики (см. ниже).
- `analysis.py` — `enrich_with_basic_analysis` → `phase_analysis`, `characteristic_points`, `engineering_metrics`.
- `modeling.py` — `build_calculation_model` + dataclass'ы для snapshot'ов (`MODEL_VERSION = "2.0"`).
- `reporting.py` — `export_results_to_excel`.

### Модели (`recoil_app/models.py`)

- **`CalculationRun`** — главный объект. ~15 FileField'ов под HTML-фрагменты графиков (общие, фаза отката `_recoil`, фаза наката `_return`, v2-специфичные `_annotated`/`_energy`). Поля энергобаланса: `energy_residual_pct`, `energy_input_total`, `energy_brake_total`. Имя расчёта валидируется regex `[A-Za-z0-9_-]+` и должно быть уникально.
- **`CalculationSnapshot`** (One-to-One) — `input_snapshot`/`result_snapshot`/`analysis_snapshot`/`thermal_snapshot` как JSONField. Хранит `timeline.t/x/v/a`, `forces.magnetic_sum`, `phases.recoil/return.end_time/end_index` — это и есть источник данных для overlay-графиков сравнения.
- **`MagneticBrakeConfig`** — параметры тормоза для конкретного `CalculationRun` (`unique_together = (run, index)`). Тип `parametric` или `curve`.
- **`BrakeForcePoint`** — точки кривой F(v) для curve-тормоза.
- **`BrakeCatalog`** — глобальный каталог тормозов. **Copy-on-use**: при использовании в расчёте параметры/файл копируются в `MagneticBrakeConfig`, чтобы расчёт оставался воспроизводимым после редактирования каталога.

### Срезы редизайна (история)

Реализовано последовательно, нарушать архитектуру нельзя:
1. Result Page v2 (`/run/<id>/v2/`) + энергобаланс
2. Дашборд на `/`, форма расчёта переехала на `/new/`
3. Каталог тормозов (`/catalog/`)
4. CAD-форма расчёта (3-панельная), AJAX «Сохранить в каталог»
5. Страница сравнения (`/compare/`) с overlay и дельта-таблицей

### Файловое хранилище

- `media/uploads/` — входные Excel-файлы расчётов
- `media/reports/<safe_name>_<id>/` — HTML-фрагменты Plotly + XLSX-отчёт. Папка создаётся при расчёте, удаляется через `delete_run_view` (`shutil.rmtree`).
- `media/brake_curves/run_<id>/brake_<idx>/` — curve-файлы тормозов конкретного расчёта
- `media/brake_catalog/curves/cat_<id>/` — curve-файлы записей каталога

## Project conventions (обязательно соблюдать)

1. **Все новые графики — через хелперы из `recoil_app/services/charting.py`**: `_apply_layout`, `_add_peak_marker`, `_add_recoil_vline`, `_make_dual_axis_figure`. Цвета — константы `RB_BLUE` (`#3D73EB`), `RB_ACCENT` (`#B44D7A`), `RB_GREEN`, `RB_AMBER`, `LINE_WIDTH_PRIMARY=3.0`. Шрифты — `FONT_FAMILY_UI` (Manrope), `FONT_FAMILY_MONO` (JetBrains Mono). Для overlay в сравнении — `_CMP_COLOR_A`/`_CMP_COLOR_B`. **Не плодить новые палитры.**
2. **Все новые шаблоны наследуют `base_v2.html`**, не `base.html`. Старый layout трогать нельзя — он fallback для архивных расчётов.
3. **Числовые значения в UI — через фильтры `smart_num` или `fmt5`** из `recoil_app/templatetags/recoil_extras.py`, **не `floatformat`**. `smart_num` сам решает: целое с разделителями, дробное с `%g`, или научная нотация.
4. **Любые изменения схемы — миграцией** (`makemigrations` → `migrate`). Не редактировать уже применённые миграции (на момент написания их 18, последняя `0018_brake_catalog`). Новые поля моделей делать `null=True, blank=True`, чтобы миграция была безопасна для существующих записей.
5. **Перед большими изменениями — согласовать план с пользователем**, не ломиться в код.

## Gotchas

- **Шаблоны живут в `templates/` в корне проекта**, не в `recoil_app/templates/`. `TEMPLATES.DIRS = [BASE_DIR / 'templates']` в settings.py.
- **`run_detail_v2_view` рендерит fallback'ы для старых расчётов**: если у `CalculationRun` нет `chart_x_t_annotated` или `chart_energy` (расчёт сделан до Среза 1), страница работает на старых полях. Проверки через `has_annotated`/`has_energy`/`has_x_t` в context.
- **Энергобаланс может быть пустым** для расчётов короче 2 точек или для архивных записей — UI должен это переносить (`if run.energy_residual_pct is not None`).
- **`recoil_end_time` интерполируется** по линейной интерполяции момента, когда `v` пересекает 0. `recoil_end_index` — индекс последней точки до пересечения. Это аккуратно учитывается в `_add_recoil_vline`.
- **`spring_force_signed` всегда направлена к `x=0`**; знак возвращается из абсолютного `spring_force(abs(x))`. Если симулятор выходит за табличный диапазон пружины — выставляется флаг `spring_out_of_range`, добавляется warning, но расчёт продолжается.
- **AJAX `catalog_save_from_form`** принимает form-encoded POST, не JSON. Нужен CSRF-токен.
- **`_parse_force_curve_sheet`** живёт на `MagneticBrakeForm` как метод. Используется и в форме расчёта, и при импорте curve-файлов из каталога (`catalog_detail_view`, `_create_brake_objects_and_runtime_models`).
- **`compare_view` использует `result_snapshot.timeline`**, а не графики на диске. Для расчётов без snapshot'а (если такие есть) overlay будет пустым.
- **Settings разделены** на пакет `recoil_project/settings/`: `base.py` (общее), `dev.py` (DEBUG=True, локальный SQLite, `django-insecure` SECRET_KEY), `prod.py` (DEBUG=False, всё из `.env`, `CSRF_TRUSTED_ORIGINS`, `SILENCED_SYSTEM_CHECKS` для HTTPS-warnings — деплой по HTTP). `manage.py` по умолчанию указывает на `settings.dev`, `wsgi.py`/`asgi.py` — на `settings.prod`.
- **`.env`** в корне проекта (gitignored). `django-environ` читает в `base.py` через `read_env(BASE_DIR / ".env")`. Шаблон в [`.env.example`](.env.example).
- **Деплой-конфиги** в `deploy/`: [`gunicorn.service`](deploy/gunicorn.service) (systemd unit, Unix socket `/run/recoil.sock`), [`nginx.conf`](deploy/nginx.conf) (proxy + static + media, `client_max_body_size 25M`, `proxy_read_timeout 300s` для долгих расчётов), [`deploy/README.md`](deploy/README.md) — пошаговая инструкция установки.
- **`requirements.txt`** теперь UTF-8 (был UTF-16 LE с BOM, артефакт PowerShell).
- **Бэкапы** (Срез 7c) пока не сделаны — отложено до запроса.

## Static / templatetags

- `recoil_app/static/recoil_app/css/design_system.css` — единая дизайн-система (~1200+ строк): палитра, KPI-карточки, типографика, layout shell.
- `recoil_app/static/recoil_app/js/shell.js` — топбар и левый rail; вставляется в `base_v2.html` декларативно через `data-*` атрибуты.
- `recoil_app/templatetags/recoil_extras.py` — `fmt5` (5 знаков после запятой), `smart_num` (умное форматирование).

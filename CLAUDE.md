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

**Каркас (редизайн v3, ветка `redesign-ui`)**: боковая навигация с подписями и группами («Расчёты / Анализ / Справочник / Администрирование») + верхняя строка с хлебными крошками и индикатором фоновых задач рендерятся СЕРВЕРОМ в `base_v2.html`. Активный раздел и корень крошек — `recoil_app/context_processors.shell` по имени URL (`URL_SECTION`); шаблоны ничего не объявляют, только `{% block shell_crumb %}` (текущая страница) и опционально `{% block shell_crumb_parent %}` (промежуточные звенья, каждое со своим `<span class="sep">/</span>` впереди); страницы вне разделов (вход/регистрация) — `{% block shell_crumb_plain %}`. Старые блоки `shell_active`/`user_initials` больше не используются. Меню сворачивается до иконок (класс `rb-nav-collapsed` на `<html>`, localStorage `recoillab.navCollapsed`, восстанавливается инлайн-скриптом в `<head>` без мигания), на экране < 960 px — выезжающая панель. Django-сообщения рендерит `base_v2` над контентом (в шаблонах страниц их не выводить). «Новый расчёт» — одна кнопка меню + переключатель режима `includes/new_calc_modes.html` (откат и накат / свободное падение / пошагово; `?from_run=` сохраняется). Индикатор фоновых задач — `services/background_tasks.running_tasks_for(user)` (свои `DesignStudy` pending/running и `IterativeCalc` finishing), пока задачи есть — `shell.js` опрашивает `/tasks/status/` раз в 8 с и показывает тост по завершении.

### URL'ы (`recoil_app/urls.py`)

```
/                       → dashboard_view (имя 'dashboard', «Рабочий стол»)
/tasks/status/          → background_tasks_view (AJAX: фоновые задачи пользователя)
/new/                   → index_view (имя 'index'; ?from_run=<id> — копия, ?catalog=<id> — тормоз из каталога)
/free-fall/new/         → free_fall_new_view (та же форма calc_new.html, mode='free_fall')
/results/               → results_view («Все расчёты», таблица)
/run/<id>/              → run_detail_v2_view (имя 'run_detail_v2')
/run/<id>/chart/<key>/  → run_chart_view (HTML-фрагмент вторичного графика, догружается страницей)
/run/<id>/delete/       → delete_run_view (POST)
/compare/               → compare_view
/optimize/              → optimize_list_view (обратное проектирование)
/optimize/new/          → optimize_new_view (запуск в фоне)
/optimize/<id>/         → optimize_detail_view (+ /status/ AJAX, /spawn/ POST, /delete/ POST)
/iterative/             → iterative_list_view (итерационный расчёт)
/iterative/new/         → iterative_new_view (?from_run=<id> — префилл)
/iterative/<id>/        → iterative_detail_view (+ /action/ AJAX POST, /delete/ POST)
/catalog/               → catalog_list_view
/catalog/new/           → catalog_new_view
/catalog/<pk>/          → catalog_detail_view
/catalog/<pk>/edit/     → catalog_edit_view
/catalog/<pk>/delete/   → catalog_delete_view (POST)
/catalog/save-from-form/ → catalog_save_from_brake_form_view (AJAX POST)
```

### Пакет views (`recoil_app/views/`)

Раздроблен на тематические модули; `__init__.py` re-export'ит всё, чтобы `urls.py` ссылался на `views.<name>_view` без изменений.

- `views/run.py` — `index_view` и `free_fall_new_view` (оба — тонкие обёртки над общим `_new_calc_view(request, mode=...)`, шаблон `calc_new.html`), `run_detail_v2_view` (всё собирает `services/result_page.build_result_page`), `run_chart_view` (ленивые графики + 3D по ключу `geometry-<index>`), `delete_run_view`; private `_build_catalog_items`, `_deny_run_view`. Общий хвост «сохранить результат + графики + XLSX + snapshot» — `services/run_pipeline.persist_result_and_snapshot` (перенесён из view в Срезе 12: его зовут и view, и сервис итерационного расчёта).
- **«Скопировать» без повторной загрузки файла**: `CalculationForm.input_file` необязателен; при `source_run_id` (скрытое поле, ставится из `?from_run=`) берётся копия файла донора (`run_pipeline.copy_input_file`), но только если донор ВИДЕН пользователю (`CalculationForm(user=...)`, `permissions.visible_run`). Так же `resolve_curve_sources(formset, user=)` берёт F(v) из тормоза-донора только видимого расчёта. Имя копии — `run_pipeline.unique_copy_name` (run_1 → run_2, не run_1_1).
- `views/dashboard.py` — `dashboard_view` (рабочий стол: `services/run_list.workspace_summary`).
- `views/results.py` — «Все расчёты»: таблица (`includes/run_table.html`, строки — `run_list.run_rows`), поиск/фильтр/сортировка/пагинация, выбор пары для сравнения (`static/.../js/results.js`).
- `views/tasks.py` — `background_tasks_view` (JSON для индикатора в верхней строке).
- `views/compare.py` — `compare_view` (тонкий, всё в `services/compare_data.py`).
- `views/catalog.py` — 5 catalog views + AJAX `catalog_save_from_brake_form_view`.
- `views/optimize.py` — обратное проектирование: список/форма/результат исследований, AJAX-статус, `spawn` (отпочкование дизайна в `CalculationRun`), удаление.

### Слой services (`recoil_app/services/`)

**Доменные:**
- `dynamics.py` — `RecoilParams`, `SimulationResult` (с energy fields), `simulate_recoil` (= `load_recoil_characteristics` + `simulate_recoil_core`), `simulate_recoil_core` (интегрирование по уже загруженному приводу — чтобы обратная задача не перечитывала Excel на каждом из сотен прогонов), `simulate_free_fall`, `compute_energy_balance`. Симулятор синхронный, чистый NumPy.
- `magnetic.py` — `MagneticParams` (parametric), `CurveBrakeParams` + `ForceCurvePoint` (табличный F(v)), `evaluate_brake_force_si`, `initial_brake_state`. Формула параметрической модели: `F_T = (B̄₃·k̄_B·Ȳ_a)² · V · [2θ_κ/R_κ + 4(2N-1)θ_y/R_y]`. Геометрия вынесена в `_magnetic_core` (wn-независимая часть, `ft = pre·kb²`) — её переиспользуют и `magnetic_force_si` (переходный вызов, байт-в-байт как раньше), и `magnetic_force_quasistatic(v, params)` (установившаяся сила: рекуррента wn линейна → `wn* = B/(1−A)` в закрытой форме; нужна Stage 2 обратной задачи для подгона под статическую кривую). Не дублировать формулу — только через `_magnetic_core`.
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
- `run_pipeline.py` — бизнес-логика создания расчёта: `build_initial_from_run`, `resolve_curve_sources`, `create_brake_objects_and_runtime_models`, `persist_result_and_snapshot(run, brake_objects, result, *, input_extra=None, result_extra=None)` (метрики + графики + XLSX + snapshot; extra — доп. ключи верхнего уровня snapshot'ов) + private хелперы.
- `kpi.py` — `build_kpi_groups(run, snapshot_parts)` для страницы результата + `kpi_format(value)` (диапазонное форматирование, отличается от templatetag `smart_num` — не путать).
- `snapshot.py` — `extract_snapshot_parts(run)` (для KPI/сравнения) и `extract_overlay_data(run)` (для overlay-графиков).
- `compare_data.py` — `build_compare_page(run_a, run_b)` (ключевые показатели A/B с разницей + осциллограмма A/B + v(x) и |F|(|v|) из прореженных snapshot'ов; фигуры — `charting.make_compare_oscillogram_figure` / `make_compare_phase_figures`) + `build_compare_metrics_table(...)` (подробная дельта-таблица 12 метрик, свёрнута).
- `result_page.py` — **страница результата «протокол + осциллограмма»** (редизайн v3): `load_series(run)` (полные ряды из snapshot'а), `build_oscillogram_data` (прореживание min/max по корзинам для каждого канала + обязательные точки разворота/возврата/переключений; ~1,4 тыс. точек), `stage_index_for` (этап в каждой точке из `BrakeStage.t_forward/t_return` — работает и для старых итогов), `build_protocol` (величина / значение / когда; пики по ПОЛНОМУ ряду), `build_status`, `LAZY_CHART_FIELDS` + `lazy_chart_html` (вторичные графики по ключу, пропавший файл → понятный текст), `build_result_page(run)` — весь контекст шаблона. Единица силы — `force_scale` (Н до 1 кН, иначе кН). Страница ~130–170 КБ вместо ~16 МБ.
- `brake_params.py` — **одно место правды для подписей 12 параметров тормоза**: `PARAM_SPECS` (поле, подпись, символ, единица, группа), `PARAM_GROUPS`, `PARAM_HINTS`, `param_field_groups(form)` (для единого редактора), `param_rows(obj)` (карточка каталога), `param_summary(obj)` (краткая сводка, в т.ч. `BrakeCatalog.short_summary`), `geometry_3d_available(brake)`. **λa и w_n0 в редакторе не показываются** (по решению пользователя: всегда 2.5 и 1.0, отвлекают): `FIXED_PARAM_DEFAULTS`, тег выводит их скрытыми полями (`hidden_param_fields` → `as_hidden`), чтобы значение донора/каталога не терялось при копировании и «Дублировать»; формы тормоза (расчёт, пошаговая сессия, каталог) подставляют значения по умолчанию вместо пустых (`apply_fixed_param_defaults`) — ошибки в невидимом поле не бывает.
- `run_list.py` — строки таблиц расчётов (`run_rows`: статус, ссылка «Скопировать» по режиму, право удаления) и `workspace_summary` для рабочего стола.
- `chart_files.py` — `read_chart_fields(obj, fields)` читает сохранённые фрагменты Plotly; ошибка чтения → лог + понятное сообщение («График «…» не найден в хранилище — пересоздайте расчёт»), а не путь/Errno.
- `background_tasks.py` — `running_tasks_for(user)` для индикатора фоновых задач.
- `fv_reference.py` — фон графика «Сила торможения от скорости» (`chart_fmag_v`, комбинированный, согласован с пользователем ради ДОСТОВЕРНОСТИ): `build_fv_reference(result, configs, stage_index)` — характеристика каждой конфигурации тормозов из МОДЕЛИ (параметрический — `magnetic_force_quasistatic`, табличный — сама таблица, за её пределами НЕ экстраполируется; сетка 1500 точек + узлы таблиц) и расхождение расчёта с ней (порог 1 %, у нуля не сравнивается). Зовётся из `run_pipeline.persist_result_and_snapshot` (ошибка → график без фона, сохранение не падает). В `charting._save_fmag_v`: оси |v| → |F| в кН; ТОЛСТЫЕ линии — посчитанное (сплошная — откат, пунктир — накат; обычный расчёт — Σ синим + каждый тормоз своим цветом `_BRAKE_LINE_COLORS`, не совпадающим с Σ; итерационный — Σ цветом этапа); ТОНКИЙ пунктир — характеристика (модель), по этапу; расчёт отходит > 1 % → в заголовке «⚠ … до X %» и точки ×. На скоростях отката расчёт совпадает с характеристикой (#94: 0 Н в 12 626 точках) — пунктир виден лишь за пределами скоростей цикла. Старые расчёты — со старым графиком до пересчёта.

**Обратное проектирование тормоза (`services/design/`, Срез 10):**
Синтез характеристики тормоза(ов) под конечные условия цикла. **Постановка — ВЕРХНИЕ ПРЕДЕЛЫ, а не точные цели**: минимизировать откат `x_max` при `x_max ≤ X`, `T ≤ T`, `v_end ≤ V`, `ΣF ≤ ΣF_max` + границы конструкции; из семейства — самый робастный. `T`/`v_end` держатся ПОД пределами (не давятся → свобода = робастность); `ΣF_max` жёстко (у параметрики штрафуется, т.к. её сила структурно не ограничена). Прямая модель — `simulate_recoil_core` (привод грузится один раз). Кривая параметризована монотонно-насыщающейся формой `f_i = f_max·(1−exp(−cumsum(softplus(u))))`. Оптимизатор — `least_squares` (LM, method='trf'); всё на едином рабочем `work_dt = t_sim/1200`. Робастность — чувствительность метрик к индивидуальным допускам (центральная разность) → свёртка `R` + запас до `ΣF_max` в σ. Диагностика через envelope (без торможения / макс. торможение). **Конфликт**: меньше `x_max`/`v_end` требуют больше торможения, а оно растит `T` → минимизация `x_max` упирается либо в `T`, либо в `ΣF_max` (что связывает первым — у того нет запаса; это видно в результате).
- `objective.py` — **единый источник целевой функции**: `design_residuals(metrics, targets, sigma_f_max)` (мин. x_max + односторонние штрафы за превышение пределов x_max/T/v_end/ΣF), `constraint_overshoot`, `within_limits`. Используют ВСЕ три оптимизатора — не дублировать.
- `targets.py` — `DesignTargets` (T/x_max/v_end — теперь ВЕРХНИЕ ПРЕДЕЛЫ; `rel_tol` — допуск на превышение) / `DesignConstraints` / `ToleranceModel` (допуск на каждый узел).
- `forward.py` — `evaluate(drive, base, v_nodes, f_nodes) → Metrics` (ValueError/выход за curve-диапазон → «не завершился», а не исключение).
- `synthesis.py` — Stage 1 (`synthesize_curve`, `f_nodes_from_u`).
- `robustness.py` — `score_robustness` → `RobustnessReport`.
- `study.py` — оркестрация `run_design_study` → `DesignResult` (Stage 1 + опц. Stage 2 через `fit_parametric=True`).
- `param_fit.py` — **Stage 2, один тормоз**: `ParamSpace` (границы конструкции: непрерывные `delta,xm,ym,dh1,dh2,dm,bz` + целое `n`; фиксированные `gamma,mu,lya,wn0`), `fit_parametric_to_curve` (DE по квазистатической RMSE — без симуляции в цикле, только алгебра силы → тысячи прогонов дёшевы), `refine_parametric_end_to_end` (LM-доводка непрерывных параметров под МЕТРИКИ полной динамикой — закрывает переходный зазор `wn`, координаты нормированы), `_param_robustness` (чувствительность метрик к индивидуальным допускам параметров + доминирующий параметр, обычно `bz` — он в квадрате), `run_parametric_stage` → `ParametricResult`.
- `multi_brake.py` — **Stage 2, N тормозов**: динамика видит только СУММУ сил, поэтому Stage 1 даёт кривую-тотал, а здесь: раскладка по весам `w_i·F_total` → подгон каждой доли (дедуп одинаковых весов) → **совместная доводка под метрики**. Равные веса → `symmetric` путь (один общий набор 7 параметров, N ОДИНАКОВЫХ тормозов; well-posed, робастность масштабируется на √N — N независимых по производству источников разброса). Неравные веса → независимые N·7 параметров, тормоза РАЗНЫЕ. `run_multi_brake_stage` → `MultiBrakeResult`. Потолок ΣF применяется к сумме.
- `multistart.py` — **мультистарт + отбор по робастности**: подбор не единственен, поэтому генерируем семейство кандидатов (1 тормоз → разные `n`; N → разные раскладки ΣF) и среди подходящих выбираем min-R (робастность как отборщик по многообразию решений). **Двухфидельно**: дешёвый скрининг ВСЕХ кандидатов на грубом `dt` (`base.t_max/400`) → точная доводка только победителя на рабочем `dt`. **Важно**: отбор на скрининге по РАСШИРЕННОМУ допуску (`2×rel_tol`) — грубый dt смещает метрики, и строгий допуск ложно отсеивал бы почти-достижимые кандидаты; истинную достижимость решает доводка победителя на точном dt. `candidates` в `MultistartResult` — ВСЕ грубые (единая шкала для Парето), `best` — точная запись, `best_coarse` — его грубая (для ★ на графике). Флаг `--multistart` (при N перебирает раскладки, `--weights` игнорируется).
- `persist.py` — `serialize_design(DesignResult) → dict` (JSON-снапшот для `DesignStudy`: stage1/stage2/candidates + buildable `design`) + `create_brakes_from_design(run, design)` (создаёт `MagneticBrakeConfig`(и) дизайна — параметрические или curve — для отпочкования).
- `runner.py` — `start_study(study_id)`: запускает `run_design_study` в демон-**потоке** (расчёт 20–200 с — слишком долго для HTTP), пишет статус/результат в `DesignStudy`, закрывает DB-connection в finally. Страница опрашивает статус AJAX-ом.

**Рабочий шаг подбора**: `work_dt = t_sim/1200` (RK4 4-го порядка, проектной точности хватает; 2× быстрее прежних 2500 шагов). Тайминги исследования сильно зависят от целей: ~20–90 с (Stage 1/2, один тормоз), до ~2–3 мин (N тормозов + мультистарт).

**Итерационный расчёт с перестройкой тормозов (`services/iterative/`, Срез 12 — движок + хранение + UI-вкладка + этапы на странице итогового расчёта):**
Пошаговое интегрирование, в котором магнитная система меняет конфигурацию по ходу движения. Сессия ХРАНИТ состояние (t, x, v, wn по тормозам, фаза, активный этап) и всю историю узлов — каждое продвижение продолжает ровно с сохранённого узла (НЕ перезапуск с нуля). Режимы: откат (`recoil`) и свободное падение (`free_fall`).
- `physics.py` — адаптеры режимов над `dynamics.py` (`signed_forces`, `rk4_step_recoil_return`, `_free_fall_advance`, `_evaluate_brake_force_components`). Формулы не дублировать — только вызывать `dynamics`: на этом держится совпадение с обычным расчётом бит-в-бит.
- `config.py` — конфигурация = кортеж «слотов» (слот i = тормоз №i+1): `MagneticParams` / `CurveBrakeParams` / `None` (отключён). Слоты только добавляются (удаление = отключение), добавленный на этапе k слот на прошлых этапах отключён. Сериализация слотов в JSON, `slot_from_brake_config` (модель из `MagneticBrakeConfig`).
- `session.py` — `IterativeSession`: `step(n)` (ровно n шагов dt), `advance_distance(dx)` (узел ставится точно в точку regula falsi по реальному шагу интегратора, ~1e-12 м; на откате разворот раньше точки → `STOP_TURNAROUND`), `reconfigure(config)` (в текущем узле; на накате запрещено; повторная смена в том же узле правит последний этап, возврат к прежней — отменяет его), `run_to_end()`, `stop()`, `build_result() → IterativeOutcome` (`SimulationResult` + `stage_index` по строкам + этапы + события), `to_dict()/history_arrays()/from_dict()` (восстановление бит-в-бит).
- **Логика этапов**: конфигурация — функция положения x (C_k на [x_k, x_{k+1})). На накате при прохождении x_k сверху вниз — автоматический возврат к C_{k−1}, узел ложится точно в x_k. В свободном падении наката нет — менять можно на всём пути.
- **Узел переключения — ДВА узла с одинаковыми (t, x, v)** (силы старой/новой конфигурации): честный скачок на графиках, точный энергобаланс (интервал нулевой длины). Тепловой интегратор дубли уже переносит (`dt <= 0` → копия), производных по t в analysis/charting нет.
- **Правило wn** (согласовано с пользователем): слот, чья модель изменилась, стартует с начального состояния НОВОЙ модели (`wn0`; у табличного состояния нет), неизменённые продолжают. На скоростях отката это не влияет (коэффициент памяти `magnetic.wn_memory_coefficient` A=(ex·ed)² ≈ 1e-23…1e-12 — wn забывается за шаг); при A > 1% — предупреждение.
- Узел события (Δx, обратное переключение) вставляется внутрь интервала сетки; следующий шаг дошагивает остаток до регулярного узла `np.arange(0, t_max+dt, dt)`. Как и узел x=0 в обычном расчёте, узел события продвигает wn один раз.
- История узлов в `session._History` — numpy-массивы с запасом ёмкости (не списки): сохранение/загрузка между запросами = копирование памяти (у свободного падения сотни тысяч узлов).
- `store.py` — **хранение между HTTP-запросами** (модель `IterativeCalc`; НЕ импортируется из `iterative/__init__` — движок остаётся без Django). Действие = `load_session` (state JSON + `history_v{N}.npz` + привод из Excel с LRU-кэшем по (путь, mtime)) → продвижение → `_save`: новый файл `history_v{N+1}.npz` + **условный** `UPDATE ... WHERE version=N` (оптимистичная блокировка: двойной клик/вторая вкладка → `StaleCalcError`, на диске остаётся согласованная версия) → старый файл удаляется. API: `create_calc` (своя копия входного файла; `input_file_from_run(run)` — копия у донора), `step`, `advance_distance`, `reconfigure`, `run_to_end`, `finish(calc, stop_now=False, name=None)` (Досчитать до конца / Остановить → `CalculationRun(is_iterative=True)` через общий `run_pipeline.persist_result_and_snapshot` + `BrakeStage` + `snapshot["iterative"]`), `delete_calc`.
- **Как итог хранится в `CalculationRun`** (отступление от первоначального плана «`MagneticBrakeConfig.stage`»): `run.brakes` остаются «физическими» — ровно по записи на тормоз (index = слот+1, параметры = первая включённая конфигурация слота; имя «Тормоз k (включён с этапа s)»). На это опираются тепло (число колонок `f_magnetic_each` = числу тормозов), 3D-геометрия, копирование, счётчик на дашборде — их не пришлось трогать. Полные конфигурации этапов — `BrakeStage(run, stage, config JSON, x_switch, t/v_forward, t/v_return)`. В snapshot: `input_snapshot["iterative"]["stages"]`, `result_snapshot["iterative"]["stage_index"]` (этап каждой точки timeline) и `["switch_events"]`.
- Команда: `python manage.py iterative_run scenario.json [--compare-plain] [--save NAME --owner USER]` или `--from-run <id>` без сценария (формат сценария — в docstring команды: `steps`/`distance`/`configure`/`to_end`/`stop`). `--save` ведёт сценарий через `store` (каждое действие — как отдельный запрос) и сохраняет итог расчётом NAME; без `to_end`/`stop` сессия остаётся активной. Тесты — `recoil_app/test_iterative.py` (18, движок, синтетический привод): бит-в-бит с `simulate_recoil_core`/`simulate_free_fall` при любой нарезке шагов и после сериализации, зеркальность обратных переключений, отключение/добавление/смена типа, правило wn; `recoil_app/test_iterative_store.py` (11, БД + временный MEDIA_ROOT): цепочка «запросов» = обычный расчёт бит-в-бит, устаревшая версия → `StaleCalcError`, этапы в `BrakeStage`/snapshot, стоп в свободном падении, имена, удаление файлов, страницы результата/тепла/сравнения рендерятся для итога с этапами. Проверено на реальных #94/#100 (бит-в-бит) и через `--save` на копии БД.
- `editor.py` — форма ↔ слоты: `slots_initial_from_session` (редактор «Изменить конфигурацию»; у выключенного/табличного слота параметрические поля заполняются последними известными параметрами — чтобы включение обратно не требовало ввода заново), `slots_initial_from_run` (старт «с этого расчёта»; у итога итерационного — этап 0; табличная F(v) — через `source_brake_id` физического тормоза донора), `slots_from_formset(formset, current)` (F(v): загруженный файл → каталог (`run_pipeline.load_catalog_curve_points`) → тормоз донора → «оставить текущую»; тормоза текущей конфигурации удалять нельзя — только выключать). `view_state.py` — `build_view_state(session)` (текущий узел, силы/wn по тормозам, этапы с `config_diff`, энергия, графики) — ОДИН источник и для первого рендера, и для AJAX-ответа; `report_message(report)`.
- **UI (Срез 3, пункт меню «Пошаговые сессии», `views/iterative.py`)**: `/iterative/` список (видимость — `permissions.iterative_visible_to`), `/iterative/new/` старт (`IterativeCalcForm` + `IterativeSlotFormSet` prefix `slots`; `?from_run=<id>` — префилл + входной файл донора; кнопка «Пошагово» на странице результата), `/iterative/<id>/` сессия, `/iterative/<id>/action/` — **AJAX POST** (`action` = `step`/`steps`(n)/`distance`(dx)/`configure`(formset)/`to_end`/`stop`(+`result_name`)) → JSON `{ok, message, html{state,stages,editor}, charts, flags}` или `{redirect}` (после завершения → страница итогового расчёта); `StaleCalcError` → 409, ошибки ввода → 400. `/iterative/<id>/delete/`. Права: смотреть — admin/analyst любую, engineer свою (`can_view_iterative`); вести/удалять — admin или автор (`can_edit_iterative`). Графики предпросмотра — `charting.make_iterative_preview_figures` (JSON фигур Plotly, прореживание до 3000 точек с узлами переключений; на клиенте `Plotly.react`, `uirevision` сохраняет зум). Шаблоны: `iterative_{list,new,detail}.html` + `includes/iterative_{state,stages,slot_editor,slot_card}.html` (панели перерисовываются из тех же include'ов в AJAX-ответе). JS — `static/recoil_app/js/iterative.js` (делегированные обработчики редактора — HTML редактора заменяется после смены конфигурации; клавиша → = Шаг), CSS — `static/recoil_app/css/iterative.css` (глобальное `[hidden]{display:none!important}` — блоки редактора с `display:grid/flex` иначе перебивают атрибут hidden). Тесты — `recoil_app/test_iterative_views.py` (12).
- **Gotcha шаблонов**: многострочные `{# … #}` Django НЕ поддерживает (выводятся текстом) — для многострочных комментариев только `{% comment %}`.
- **Этапы на итоговом расчёте (Срез 4)**: `overlay.build_stage_overlay(outcome)` → простой dict (charting/reporting о пакете iterative НЕ знают): `segments` (интервалы времени этапов; этап k на откате и на накате — два интервала), `x_bands` (этап как функция x: [x_k, x_{k+1}), последний до x_max), `events` (переключения + `row`), `stages` (точки, конфигурации, `config_diff`), `stage_index`. Передаётся `persist_result_and_snapshot(..., stage_overlay=)` → `save_interactive_charts(..., stage_overlay=)` и `export_results_to_excel(..., stage_overlay=)`. Графики: `charting._add_stage_overlay_t` (полосы этапов k≥1 цветом `_stage_color`, линии переключений — откат сплошные / накат пунктир; для графиков фаз — окно `t_range`, чтобы не растягивать ось; полосы уже 3% окна без подписи — на быстром откате подписи налезали), `_add_stage_overlay_x` (полосы по x + ромбы переключений на v(x)); F(v) — сумма разными цветами по этапам. Тот же overlay рисует и предпросмотр сессии (`make_iterative_preview_figures(result, overlay)`) — один механизм. XLSX: колонка «этап» последней на листе `data` (остальные листы берут столбцы по номерам — не сдвигать), листы «Этапы» и «Этапы_тормоза». Страница результата (`run_detail_v2`): метка «пошаговый, этапов: N», кнопка «Открыть сессию», этапы — лентой под осью осциллограммы, компактной таблицей в боковой панели (`result_page.stage_rows`, цвета как на ленте) и сворачиваемым разделом `includes/run_stages.html` из `result_view.build_stage_tables(run)` (таблица этапов + по каждому тормозу параметры по этапам, изменённые ячейки `.rs-changed`, `<details>` открыт, если тормоз менялся; данные — из `BrakeStage`, работает и для итогов, сохранённых до overlay-графиков). Таблица «Все расчёты» — метка «пошаговый». Тесты — `recoil_app/test_iterative_result.py` (8).
- **Этапы на графиках скрыты по умолчанию** (пользователь: «не читаемо»): все элементы этапов помечены — shapes/annotations `name="stage-band"|"stage-switch"|"stage-label"`, трассы `meta="stage"`, `visible=STAGES_VISIBLE_DEFAULT` (False). Показывает переключатель «Этапы на графиках» (`<input data-stage-toggle>`, `static/recoil_app/js/stage_toggle.js`: `Plotly.relayout/restyle` по меткам на всех `.js-plotly-plot`, выбор в localStorage `recoillab.showStages`, общий для страницы результата и сессии; `iterative.js` применяет его после каждого `Plotly.react`). Новые элементы этапов на графиках — обязательно с этими метками, иначе переключатель их не увидит.
- **Срез 5**: `Stage.checkpoint` (снимок в узле до переключения) → `IterativeSession.undo_last_change()` восстанавливает состояние точно (дальше — бит-в-бит, как без изменения; убирает добавленные тормоза; работает и после «досчитался до конца»); повторная смена в том же узле идёт через него же. `resume()` — продолжить остановленный. `store.clone_calc` — копия сессии в текущем состоянии (клон остановленной продолжает счёт); `/iterative/<id>/clone/`. `store.finish_auto` — при остатке > `BACKGROUND_FINISH_STEPS` (20 000) шагов досчёт в демон-потоке: статус `finishing` (миграция `0028`: + `error_text`), `/status/` для опроса, ошибка → сессия снова `active` с текстом; `/reset/` — сбросить зависший (> 10 мин). Тесты — `recoil_app/test_iterative_extras.py` (поток в тестах подменяется синхронным `_finish_worker(..., close_connection=False)`).

### UI обратного проектирования (Срез 11: rail «Оптимизация»)

`DesignStudy` (модель, миграция `0026`) — одно исследование: донор-расчёт (`source_run`), вход (цели/ΣF/N/флаги), `status` (`pending`/`running`/`done`/`error`), `result_snapshot` (JSON от `serialize_design`), денормализованные `feasible`/`best_R`, `spawned_run` (отпочкованный `CalculationRun`). Считается в фоне (`runner.start_study`).

**Идеал vs реальный тормоз на странице результата**: синтезированная `F(v)` (Stage 1) для минимума отката — это плоская полка до `ΣF_max`, которую вихретоковый тормоз воспроизвести НЕ может (его сила растёт с v и плавно насыщается). Поэтому для параметрических дизайнов `optimize_detail_view` рисует поверх идеала (пунктир) РЕАЛЬНУЮ `F(v)` подобранного тормоза — сумму `magnetic_force_quasistatic` по N (сплошная) — через `charting.make_design_fv_fragment`. Для curve-дизайнов показывается сама кривая (табличный тормоз её реализует как есть). Итоговые метрики всегда по полной динамике реального тормоза.

Страницы `views/optimize.py` (пункт меню «Подбор тормоза»): `/optimize/` список, `/optimize/new/` форма (`DesignStudyForm`), `/optimize/<id>/` результат с AJAX-опросом `/status/` (спиннер → авто-reload), `/spawn/` (POST — из победителя собрать реальный `CalculationRun` через тот же pipeline: копия входного файла донора + `create_brakes_from_design` + `simulate_recoil` + `_persist_result_and_snapshot` → полная страница результата/тепло/сравнение), `/delete/`. Валидировано e2e: Stage 1 (curve-дизайн), Stage 2 (параметрический) и мультистарт+Парето — все создают рабочие расчёты.

**Парето-визуализация** (`charting.make_pareto_fragment`) — для мультистарт-исследований на странице результата: плоскость «откат x_max, м» (X, цель — минимизируется) ↔ «R робастность» (Y), оба «меньше — лучше» → Парето-фронт слева-снизу; размер точки — запас до ΣF_max, цвет — под пределами/нет, ★ — выбранный (min R). Точки — грубые (единая шкала), таблицы параметров/робастности — точный победитель. Строится через общие хелперы charting (`_apply_layout`, `_to_html_fragment`, палитра RB_*).

**Дальше**: тепловой отсев кандидатов, перф интегратора (numba/vectorize — чистый Python RK4 узкое место), опц. температурный дрейф в допусках, устойчивость фона к рестарту воркера (heartbeat/очередь).
- Вход: `python manage.py design_brake --from-run <id> --T .. --xmax .. --vend .. --sigma-f-max .. [--tol .. --nodes 4 --plot --parametric --param-tol 0.02 --brakes N --weights w1,.. --multistart]` (донор — recoil-расчёт с входным файлом; `--parametric`/`--brakes≥2`/`--multistart` включают Stage 2; `--brakes` ≤4 для MVP). Валидировано round-trip: Stage 1 восстанавливает достижимую кривую точно; Stage 2 (1 тормоз) при параметрически-достижимой цели попадает ~0.1–0.2%; N тормозов — симметрия и асимметрия; мультистарт — отбор min-R и для n (1 тормоз), и для раскладок ΣF (N; слишком скошенные раскладки корректно отсеиваются как недостижимые). **Статический F(v) не воспроизводит динамику параметрических тормозов с переходником `wn`** — поэтому Stage 2 = подгон под кривую (нач. приближение) + end-to-end доводка под метрики. Тайминги: Stage 1 ~15–25с, Stage 2 (1) ~50–90с, N=2 ~130–170с (в UI будет async). Дальше (не в MVP): модель `DesignStudy` + отпочкование победителя в `CalculationRun`, вкладка «Оптимизация», Парето-страница, тепловой отсев.

### Модели (`recoil_app/models.py`)

- **`BrakeParametersMixin`** — abstract base model с 12 параметрическими полями вихретокового тормоза (`gamma`, `delta`, `n`, `xm`, `ym`, `dh1`, `dh2`, `dm`, `mu`, `bz`, `lya`, `wn0`). Наследуется и `MagneticBrakeConfig`, и `BrakeCatalog` — одно место правды для параметров. Введён в Pass 5 (миграция `0019`).
- **`CalculationRun`** — главный объект. ~15 FileField'ов под HTML-фрагменты графиков (общие, фаза отката `_recoil`, фаза наката `_return`, v2-специфичные `_annotated`/`_energy`). Поля энергобаланса: `energy_residual_pct`, `energy_input_total`, `energy_brake_total`. Имя расчёта валидируется regex `[A-Za-z0-9_-]+` и должно быть уникально.
- **`CalculationSnapshot`** (One-to-One) — `input_snapshot`/`result_snapshot`/`analysis_snapshot`/`thermal_snapshot` как JSONField. Хранит `timeline.t/x/v/a`, `forces.magnetic_sum`, `phases.recoil/return.end_time/end_index` — это и есть источник данных для overlay-графиков сравнения.
- **`MagneticBrakeConfig`** (наследует `BrakeParametersMixin`) — параметры тормоза для конкретного `CalculationRun` (`unique_together = (run, index)`). Тип `parametric` или `curve`.
- **`BrakeForcePoint`** — точки кривой F(v) для curve-тормоза.
- **`BrakeCatalog`** (наследует `BrakeParametersMixin`) — глобальный каталог тормозов. **Copy-on-use**: при использовании в расчёте параметры/файл копируются в `MagneticBrakeConfig`, чтобы расчёт оставался воспроизводимым после редактирования каталога.
- **`ThermalRun`** (FK→`CalculationRun`, `unique_together=(run, name)`) — отдельный тепловой сценарий поверх готового расчёта. Хранит `network_preset` (`nine_node`/`single_node`), `repetitions`, `pause_s`, два JSON-снапшота (`config_snapshot` с полной сетью + геометрией + материалами, `result_snapshot` с decimated timeline + cycle table + peaks) и 4 FileField'а под HTML-фрагменты Plotly. Денормализованные `max_temp_c`/`max_temp_node_name`/`total_heat_j` — для KPI и фильтрации списка. Каскадно удаляется с `CalculationRun`; файлы и папка `media/thermal_reports/run_<rid>_thermal_<tid>/` чистятся через `post_delete` сигнал в [signals.py](recoil_app/signals.py).
- **`IterativeCalc`** (миграция `0027`) — сессия итерационного расчёта: режим, параметры, своя копия входного файла, `state` (JSON движка), `history_file` (`.npz` текущей `version`), `status` (`active`/`finished`), `result_run` (SET_NULL). Логика — только через `services/iterative/store.py`. Удаление чистит `media/iterative/calc_<id>/` (сигнал).
- **`BrakeStage`** (FK→`CalculationRun`, `unique_together=(run, stage)`) — этап конфигурации тормозов итога итерационного расчёта (этап 0 — исходная): `config` JSON всех тормозов, точка включения и время/скорость на откате и на накате. `CalculationRun.is_iterative=True` — у таких расчётов есть этапы.

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
9. Режим «Свободное падение» (`/free-fall/new/`, отдельная вкладка в rail): тело падает под гравитацией, тормоза противодействуют, без входного файла (F_вход=0, F_пруж=0), угол по умолчанию 90° (редактируемый), t_max без верхнего предела. Хранится как `CalculationRun` с `mode='free_fall'` (`input_file` nullable). Симулятор `simulate_free_fall` (в `dynamics.py`) устойчив к малой массе (до грамма): на каждом шаге dt замораживает состояние тормоза `wn` и интегрирует (x,v) адаптивным дроблением шага (step-doubling), избегая RK4-неустойчивости при жёсткой динамике (малая v_терм). Страница результата — та же `run_detail_v2`, mode-aware (нет фаз отката/наката/пружины, бейдж «свободное падение»).

После Срезов 1–7 проведён большой рефакторинг (6 пассов): удалён legacy, разделён `views.py` на пакет, выделены сервисы, abstract base mixin, inline CSS/JS вынесены в файлы.

**Редизайн v3 «протокол + осциллограмма»** (ветка `redesign-ui`, 5 этапов, палитра сохранена): 1) токены/контраст/типографика, чистка шаблонов от эмодзи и `<style>`; 2) серверная навигация с группами, индикатор фоновых задач, единый вход «Новый расчёт»; 3) страница результата — протокол итогов + синхронная осциллограмма из прореженного snapshot'а, вторичные графики по требованию; 4) единый редактор тормоза, `calc_new.html` вместо двух шаблонов, «Скопировать» без повторной загрузки файла; 5) рабочий стол, таблицы расчётов и каталога, сравнение на одной осциллограмме A/B.

### Файловое хранилище

- `media/uploads/` — входные Excel-файлы расчётов
- `media/reports/<safe_name>_<id>/` — HTML-фрагменты Plotly + XLSX-отчёт. Папка создаётся при расчёте, удаляется через `delete_run_view` (`shutil.rmtree`).
- `media/brake_curves/run_<id>/brake_<idx>/` — curve-файлы тормозов конкретного расчёта
- `media/brake_catalog/curves/cat_<id>/` — curve-файлы записей каталога
- `media/thermal_reports/run_<rid>_thermal_<tid>/` — HTML-фрагменты Plotly теплового сценария. Чистятся в `post_delete` сигнале на `ThermalRun`.
- `media/iterative/calc_<id>/` — сессия итерационного расчёта: копия входного Excel + `history_v{N}.npz` (только текущая версия). Чистится `post_delete`-сигналом на `IterativeCalc`; итоговый `CalculationRun` имеет свои копии файлов.

## Project conventions (обязательно соблюдать)

1. **Все новые графики — через хелперы из `recoil_app/services/charting.py`**: `_apply_layout`, `_add_peak_marker`, `_add_recoil_vline`, `_make_dual_axis_figure`. Цвета — константы `RB_BLUE` (`#3D73EB`), `RB_ACCENT` (`#B44D7A`), `RB_GREEN`, `RB_AMBER`, `LINE_WIDTH_PRIMARY=3.0`. Шрифты — `FONT_FAMILY_UI` (Manrope), `FONT_FAMILY_MONO` (JetBrains Mono). Для overlay в сравнении — `_CMP_COLOR_A`/`_CMP_COLOR_B`. **Не плодить новые палитры.**
2. **Все новые шаблоны наследуют `base_v2.html`**.
3. **Числовые значения в UI — через фильтры `smart_num` или `fmt5`** из `recoil_app/templatetags/recoil_extras.py`. `floatformat:N` допускается только для случаев осознанной фиксированной точности (например, `mass|floatformat:1` в боковой таблице параметров — иначе `smart_num` выведет полную точность из БД, что некрасиво).
4. **Любые изменения схемы — миграцией** (`makemigrations` → `migrate`). Не редактировать уже применённые миграции (на момент написания их 20, последняя `0020_thermalrun`). Новые поля моделей делать `null=True, blank=True`, чтобы миграция была безопасна для существующих записей.
5. **Бизнес-логика — в `services/`, не во view'хах.** View должен только: распарсить запрос, вызвать сервис, отрендерить шаблон. Если функция начинает делать что-то «доменное» (создавать модели, считать KPI, парсить файлы) — её место в `services/<area>.py`.
6. **Перед большими изменениями — согласовать план с пользователем**, не ломиться в код.
7. **Визуальные правила редизайна v3** (палитра RecoilLab сохранена по решению пользователя):
   - цвет = физическая величина: x — `RB_BLUE`, v — `RB_GREEN`, a — `RB_ACCENT`, F — `RB_AMBER` (для подписей — тёмные варианты `charting.QUANTITY_COLORS` / CSS `--q-*-text`);
   - градиент бренда — только фирменные элементы: полоса под верхней строкой, «Новый расчёт» в меню и ОДНА главная кнопка экрана (`.rb-btn-primary`; `.rb-btn-grad` — синоним для старых мест);
   - Manrope для всего текста, JetBrains Mono — только для числовых значений (в т.ч. в Plotly: подписи осей и легенды — `FONT_FAMILY_UI`, деления — mono);
   - подписи без КАПСА и разрядки, без эмодзи и декоративных стрелок/«·» в интерфейсе; статус — точка + слово (`.rb-status`, `.rb-status-banner-icon` пустая);
   - новые страницы — из готовых блоков: `.rb-panel` (+ `-head`/`-body`/`-note`), `.rb-table`, `.rb-protocol` (строка итогов), `.rb-fold` (сворачиваемый `<details>`), `.rb-split` (основная + боковая 320 px), `.rb-seg` (сегментный переключатель);
   - стили страниц — в `pages.css`, не в `<style>` шаблона; подтверждение/ввод имени — атрибуты формы `data-confirm="…"` / `data-prompt="…"` (обработчик в `shell.js`), не `onsubmit=`.

## Gotchas

- **Шаблоны живут в `templates/` в корне проекта**, не в `recoil_app/templates/`. `TEMPLATES.DIRS = [BASE_DIR / 'templates']` в settings.
- **Страница результата для архивных расчётов**: без snapshot'а осциллограммы нет — показываются прежние `chart_x_t(_annotated)`/`chart_v_a_t` (ленивые ключи `x_t`/`v_a_t`) и объяснение «скопируйте и пересчитайте». Какие вторичные графики есть — `result_page.available_lazy_charts(run)` (по заполненным FileField).
- **Ленивые графики**: `<div data-lazy-chart="{% url 'run_chart' run.id key %}">` — `result_page.js` грузит фрагмент, когда блок подходит к экрану или раскрывается его `<details>`, и ПЕРЕСОЗДАЁТ `<script>` (innerHTML их не исполняет); после вставки применяет переключатель этапов. Внутри закрытого `<details>`/неактивной вкладки не грузится, пока не покажут.
- **`floatformat` в русской локали ставит запятую**, а `smart_num`/протокол — точку. Для единообразия — `floatformat:"3u"` (без локализации). Встроенный `pluralize` знает только две формы — для русских трёх форм фильтр `ru_plural:"тормоз,тормоза,тормозов"`.
- **Кэш статики**: ссылки на CSS/JS в шаблонах с `?v=3` — при заметной правке стилей/скриптов увеличивать версию, иначе браузер держит старые файлы.
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
- **Режим `free_fall`**: `CalculationRun.input_file` теперь nullable — для свободного падения файла нет. Не полагаться на `run.input_file.path` без проверки режима (`run.is_free_fall`). `simulate_free_fall` требует минимум 1 тормоз (как и `simulate_recoil`); фаз отката/наката не создаёт (`recoil_end_index`/`return_end_index` = None) — `modeling`/`analysis`/`kpi`/`charting` это уже переносят. termination_reason = `"free_fall"`.
- **Численная жёсткость свободного падения**: при очень малой массе шаг dt дробится адаптивно; если упёрлись в предел (`_FREE_FALL_MAX_SUBSTEPS`), в `warnings` добавляется заметка — уменьшить dt. Семантика `wn` (одно продвижение на dt) сохранена в точности, поэтому нельзя заменить на общий адаптивный ODE-решатель.
- **Миграции**: `makemigrations` тянет паразитный `~ Alter field id` на всех моделях (расхождение `DEFAULT_AUTO_FIELD`, не настроен) — это НЕ относится к текущим правкам. Новые миграции писать точечно (см. `0025_calculationrun_free_fall_mode`, `0026_designstudy`, `0027_iterative_calc` — руками, только нужная операция), не бандлить id-churn.
- **Фоновый поток `DesignStudy`**: исследование дизайна считается в демон-`threading.Thread` (`runner.start_study`) — синхронный view не подходит (20–200 с). Поток берёт свою per-thread DB-connection и закрывает её в `finally` (SQLite). Статус в БД, страница опрашивает `/optimize/<id>/status/` и делает авто-reload. Единственный async-паттерн в проекте (Celery нет); при рестарте воркера незавершённое исследование зависнет в `running` — перезапустить. Отпочкование (`spawn`) копирует входной файл донора и гоняет полный `simulate_recoil` синхронно (это быстро, ~секунды).

## Static / templatetags

- `recoil_app/static/recoil_app/css/design_system.css` — дизайн-система v3: токены (палитра, `--q-*` цвета величин, шрифты, фокус), каркас (боковое меню, верхняя строка), базовые компоненты (кнопки, бейджи, панели, таблицы, `.rb-seg`, `.rb-fold`, формы).
- `recoil_app/static/recoil_app/css/pages.css` — компоненты страниц (протокол, осциллограмма, таблица расчётов, сравнение) и стили, вынесенные из `<style>`-блоков шаблонов (тепло, подбор, профиль, пользователи, вход, каталог), единый редактор параметров тормоза `.rb-param-*`, `.notice`.
- `recoil_app/static/recoil_app/css/calc_form.css` — форма нового расчёта (`calc_new.html`).
- `recoil_app/static/recoil_app/js/shell.js` — поведение каркаса (разметку рендерит сервер): сворачивание меню, мобильная панель, `data-confirm`/`data-prompt` на формах, опрос фоновых задач, `window.RecoilLab.toast`.
- `recoil_app/static/recoil_app/js/result_page.js` — осциллограмма (считыватель курсора, участки цикла = диапазон оси) и ленивая догрузка графиков; `compare.js` — осциллограмма A/B; `results.js` — выбор пары для сравнения и автосортировка (также на каталоге).
- `recoil_app/static/recoil_app/js/modules.js` — только вкладки `[data-tab-group]` (3D тормозов на странице результата, графики теплового сценария). Чекбоксы видимости модулей удалены — их заменили разделы `<details class="rb-fold">`.
- `recoil_app/static/recoil_app/js/calc_form.js` — formset, индикаторы заполненности (точка-статус), AJAX «в каталог», submit + loader. Карточка тормоза и шаблон «Добавить тормоз» — ОДИН include `includes/brake_card.html` («Дублировать» копирует поля по порядку — разметка должна совпадать).
- `recoil_app/static/recoil_app/js/thermal_form.js` — выбор тепловой модели, калькулятор G = h·A, кнопки «Подставить размеры тормоза» (`.tf-prefill-btn`, только parametric), условные блоки 9-узловой сети.
- `recoil_app/templatetags/recoil_extras.py` — `fmt5` (5 знаков), `smart_num` (умное форматирование), `index_or` (для индексации в шаблоне с formset'ом), `json_script_data` (безопасная сериализация в `<script type="application/json">`), `ru_plural` (три формы), `mul1000` (м → мм), тег `{% brake_param_grid form %}` — единая сетка параметров тормоза (группы, символ, подпись, единица) для формы расчёта, пошаговой сессии и каталога.

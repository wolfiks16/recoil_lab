# Срез 1: Result Page v2 + Energy Balance

Дата: производим в рамках общего плана «довести проект до совершенства».

## Что добавлено

**Физика и сервисы**

- `recoil_app/services/dynamics.py`
    - `SimulationResult` расширен 6 новыми полями (`energy_kinetic`, `energy_spring`,
      `energy_brake_cum`, `energy_input_cum`, `energy_total`, `energy_residual_pct`).
    - Добавлена функция `compute_energy_balance(result, mass)`. Считает E_кин, E_пруж,
      накопленную работу тормозов и подведённую энергию методом трапеций; даёт
      относительную невязку баланса в %.
    - `simulate_recoil` теперь вызывает `compute_energy_balance` перед возвратом.

- `recoil_app/services/charting.py`
    - `_save_annotated_x_t(result, ...)` — hero-график x(t) с подсветкой пика, аннотацией
      `x_max = … мм` и вертикальной чертой на точке разворота.
    - `_save_energy_balance(result, ...)` — график 4 кривых: E_кин, E_пруж, E_торм_накоп,
      E_вход_накоп. В заголовке выводится максимальная невязка.
    - `save_interactive_charts` зовёт обе новые функции и кладёт пути в результирующий dict.

**Модели и миграции**

- `recoil_app/models.py` — `CalculationRun` расширен:
    - `chart_x_t_annotated`, `chart_energy` (FileField, nullable)
    - `energy_residual_pct`, `energy_input_total`, `energy_brake_total` (FloatField, nullable)
- `recoil_app/migrations/0017_v2_energy_and_charts.py` — миграция для всех новых полей.

**Views и URLs**

- `recoil_app/views.py`
    - `index_view`: при сохранении расчёта новые поля `chart_x_t_annotated`, `chart_energy`,
      `energy_*` заполняются автоматически.
    - `delete_run_view`: новые файлы корректно удаляются.
    - **Новая функция** `run_detail_v2_view(request, run_id)` — отдаёт страницу нового дизайна.
    - **Новая функция** `_build_kpi_cards(run, snapshot_parts)` — формирует список KPI
      (макс. откат, пик ускор., макс. v, время цикла, рассеяно тормозами, невязка энергии).
- `recoil_app/urls.py`: добавлен path `run/<int:run_id>/v2/` → `run_detail_v2`.

**Frontend (новый дизайн)**

- `recoil_app/static/recoil_app/css/design_system.css` — дизайн-система v2:
  палитра (#3D73EB / #B44D7A / градиент), shell, KPI-карточки, кнопки, баннеры,
  типографика (Manrope + JetBrains Mono).
- `recoil_app/static/recoil_app/js/shell.js` — компонент топбара и левого rail
  с SVG-логотипом RecoilLab. Декларативная конфигурация через `data-*` атрибуты.
- `templates/recoil_app/base_v2.html` — общий layout нового дизайна.
- `templates/recoil_app/run_detail_v2.html` — страница результата:
    - Hero (название, бейджи, дата, кнопки действий)
    - Status banner (зелёный «успех» / жёлтый «по лимиту» / варнинги)
    - Ряд KPI-карточек (6 карточек, скейлится по адаптиву)
    - Главная сетка: hero-график x(t) + параметры + список тормозов
    - Секция «Энергобаланс» с pill-метриками и графиком
    - Дополнительные графики (v(t)/a(t), v(x), F(t))
    - Артефакты (XLSX-отчёт, исходник)

**Точка входа в новый дизайн**

- `templates/recoil_app/run_detail.html` — добавлена кнопка-градиент «★ Новый дизайн»
  в верхнем ряду actions, ведёт на `run_detail_v2`.

## Что НЕ менялось

- Старый `run_detail.html` остаётся рабочим — на него можно вернуться в любой момент.
- Старый `base.html`, `index.html`, `compare.html` без изменений.
- Существующие модели (`MagneticBrakeConfig`, `BrakeForcePoint`, `CalculationSnapshot`)
  не тронуты.
- Существующие миграции 0001..0016 не тронуты.

## Как установить и запустить

```bash
# 1. Применить миграцию (новые поля + nullable, безопасно)
python manage.py migrate

# 2. Запустить
python manage.py runserver
```

## Как проверить

1. Открыть любой существующий расчёт: `http://localhost:8000/run/<id>/`
2. Нажать «★ Новый дизайн» в верхней строке кнопок.
3. На новой странице:
    - **Старые расчёты**: видно KPI, hero-график будет `chart_x_t` (без аннотации),
      энергобаланс будет недоступен (написано «Пересчитайте, чтобы увидеть»).
    - **Новые расчёты** (после Create в `index_view`): видно аннотированный график
      и полный энергобаланс с невязкой.

## Что осталось на следующие срезы

- **Срез 2**: дашборд (новый list view со stat-карточками и табами)
- **Срез 3**: каталог тормозов (новые модели `BrakeCatalog`, переключатель в форме)
- **Срез 4**: новая форма расчёта (3-панельная CAD-раскладка)
- **Срез 5**: страница сравнения с overlay и дельта-таблицей

## Известные ограничения

- KPI-блок «Рассеяно тормозами» показывается только для новых расчётов
  (старые не имеют `energy_brake_total`).
- При очень коротких расчётах (<2 точки) энергобаланс возвращает нули — это
  безопасно, просто график будет плоским.
- `cut:"reports/"` в шаблоне срезает префикс из имени файла; для эксклюзивно-чистого
  отображения позже сделаем кастомный шаблонный фильтр `basename`.

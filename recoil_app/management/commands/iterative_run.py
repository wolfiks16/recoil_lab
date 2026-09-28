"""Итерационный расчёт по сценарию из JSON — проверка физики без UI.

Пример:
    python manage.py iterative_run scenario.json
    python manage.py iterative_run --from-run 94 --compare-plain   # без сценария: до конца
    python manage.py iterative_run scenario.json --save my_iter_run --owner admin
        # через хранилище (IterativeCalc), итог — обычный расчёт my_iter_run

Сценарий:
{
  "from_run": 94,                       // донор: режим, параметры, входной файл, тормоза C₀
  "mode": "recoil",                     // или "free_fall" (по умолчанию — режим донора)
  "recoil": {"dt": 1e-4, "t_max": 2.0}, // переопределение параметров (mass, angle_deg, v0, x0, t_max, dt)
  "input_file": "path.xlsx",            // вместо файла донора (для отката)
  "brakes": [ {слот}, ... ],            // вместо тормозов донора (C₀)
  "actions": [
    {"steps": 100},                     // ровно N шагов интегрирования
    {"distance": 0.30},                 // пройти путь Δx (узел — точно в точке)
    {"configure": [                     // сменить конфигурацию в текущем узле
      {"slot": 0, "set": {"bz": 1.2}},  //   правка параметров параметрического тормоза
      {"slot": 1, "off": true},         //   отключить
      {"slot": 2, "curve": [[0, 0], [5, 30000], [20, 90000]]},  // таблица F(v), Н
      {"slot": 3, "parametric": {...}}  //   слот = числу тормозов → добавить новый
    ]},
    {"to_end": true}                    // досчитать до конца  |  {"stop": true} — остановить
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from recoil_app.models import CalculationRun, IterativeCalc, MagneticBrakeConfig
from recoil_app.services.dynamics import RecoilParams, simulate_free_fall, simulate_recoil_core
from recoil_app.services.io_utils import load_recoil_characteristics
from recoil_app.services.iterative import store
from recoil_app.services.iterative.config import KIND_LABELS, config_diff
from recoil_app.services.iterative import (
    MODE_FREE_FALL,
    MODE_RECOIL,
    IterativeSession,
    slot_from_brake_config,
    slot_kind,
)
from recoil_app.services.magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams

_RECOIL_FIELDS = ("mass", "angle_deg", "v0", "x0", "t_max", "dt")
_COMPARE = ("t", "x", "v", "a", "f_total", "f_magnetic", "f_magnetic_each", "wn_each")


def _fmt(value, prec=6):
    if value is None:
        return "—"
    return f"{float(value):.{prec}g}"


class _MemoryDriver:
    """Сессия в памяти (без БД) — быстрая проверка физики."""

    result_run = None

    def __init__(self, session: IterativeSession):
        self.session = session

    def step(self, n):
        return self.session.step(n)

    def distance(self, dx):
        return self.session.advance_distance(dx)

    def configure(self, config):
        return self.session.reconfigure(config)

    def to_end(self):
        return self.session.run_to_end()

    def stop(self):
        self.session.stop()


class _StoreDriver:
    """Через хранилище: каждое действие — как отдельный HTTP-запрос (перечитать запись,
    загрузить сессию, продвинуть, сохранить новую версию)."""

    def __init__(self, calc: IterativeCalc):
        self.calc = calc
        self.result_run = None

    def _fresh(self) -> IterativeCalc:
        return IterativeCalc.objects.get(pk=self.calc.pk)

    @property
    def session(self) -> IterativeSession:
        return store.load_session(self._fresh())

    def step(self, n):
        return store.step(self._fresh(), n)

    def distance(self, dx):
        return store.advance_distance(self._fresh(), dx)

    def configure(self, config):
        return store.reconfigure(self._fresh(), config)

    def to_end(self):
        report = store.run_to_end(self._fresh())
        self.result_run = store.finish(self._fresh())
        return report

    def stop(self):
        self.result_run = store.finish(self._fresh(), stop_now=True)


class Command(BaseCommand):
    help = "Итерационный расчёт по сценарию: шаги, путь Δx, смена конфигурации тормозов, досчёт."

    def add_arguments(self, parser):
        parser.add_argument("scenario", nargs="?", help="JSON-сценарий (см. описание команды).")
        parser.add_argument("--from-run", type=int, help="ID расчёта-донора (приоритетнее from_run сценария).")
        parser.add_argument("--compare-plain", action="store_true",
                            help="Сравнить с обычным расчётом исходной конфигурации C₀ "
                                 "(совпадение бит-в-бит ожидается, если конфигурацию не меняли).")
        parser.add_argument("--save", metavar="NAME",
                            help="Вести расчёт через хранилище (IterativeCalc — каждое действие как "
                                 "отдельный запрос) и сохранить итог расчётом NAME. Без to_end/stop "
                                 "в конце сценария сессия остаётся активной.")
        parser.add_argument("--owner", metavar="USERNAME", help="Владелец сессии/расчёта (для --save).")

    def handle(self, *args, **opts):
        scenario = self._load_scenario(opts["scenario"])
        run_id = opts["from_run"] or scenario.get("from_run")
        run = self._load_run(run_id) if run_id else None

        mode = scenario.get("mode") or (run.mode if run else MODE_RECOIL)
        if mode not in (MODE_RECOIL, MODE_FREE_FALL):
            raise CommandError(f"Неизвестный режим: {mode!r}")
        recoil = self._recoil_params(run, scenario.get("recoil", {}))
        drive = self._drive(run, scenario, mode)
        config = self._initial_config(run, scenario)

        if opts["save"]:
            driver = self._store_driver(opts, scenario, run, mode, recoil, config)
        else:
            driver = _MemoryDriver(IterativeSession(mode, recoil, config, drive))

        session = driver.session
        title = f"донор «{run.name}» (#{run.id})" if run else "без донора"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nИтерационный расчёт · {'откат' if mode == MODE_RECOIL else 'свободное падение'} · {title}"))
        self.stdout.write(
            f"m={_fmt(recoil.mass)} кг · угол={_fmt(recoil.angle_deg)}° · dt={_fmt(recoil.dt)} с · "
            f"t_max={_fmt(recoil.t_max)} с · тормозов={session.n_slots}"
            + (f" · сессия #{driver.calc.pk} «{driver.calc.name}»" if opts["save"] else ""))
        self._print_node(session, "старт")

        actions = scenario.get("actions") or [{"to_end": True}]
        for number, action in enumerate(actions, 1):
            self._apply(driver, action, number)

        session = driver.session
        outcome = session.build_result()
        self._print_summary(session, outcome)
        if opts["compare_plain"]:
            self._compare_plain(session, outcome, mode, recoil, drive)
        if opts["save"]:
            if driver.result_run is not None:
                self.stdout.write(self.style.SUCCESS(
                    f"Итог сохранён: расчёт #{driver.result_run.pk} «{driver.result_run.name}» "
                    f"(/run/{driver.result_run.pk}/)"))
            else:
                self.stdout.write(self.style.WARNING(
                    f"Сессия #{driver.calc.pk} оставлена активной (сценарий без to_end/stop)."))

    def _store_driver(self, opts, scenario, run, mode, recoil, config) -> "_StoreDriver":
        owner = None
        if opts["owner"]:
            owner = get_user_model().objects.filter(username=opts["owner"]).first()
            if owner is None:
                raise CommandError(f"Пользователь «{opts['owner']}» не найден.")
        input_file = None
        if mode == MODE_RECOIL:
            path = scenario.get("input_file")
            input_file = (ContentFile(Path(path).read_bytes(), name=Path(path).name) if path
                          else store.input_file_from_run(run))
        try:
            calc = store.create_calc(
                name=opts["save"], mode=mode, recoil=recoil, config=config,
                owner=owner, input_file=input_file, source_run=run,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return _StoreDriver(calc)

    # ----------------------------------------------------------------- действия

    def _apply(self, driver, action: dict, number: int) -> None:
        session = driver.session
        if session.finished and not action.get("stop"):
            self.stdout.write(self.style.WARNING(f"#{number}: расчёт уже завершён — действие пропущено."))
            return
        try:
            if "steps" in action:
                report = driver.step(int(action["steps"]))
                label = f"шагов {action['steps']}"
            elif "distance" in action:
                report = driver.distance(float(action["distance"]))
                label = f"путь Δx={_fmt(action['distance'])} м"
            elif "configure" in action:
                changed = driver.configure(self._new_config(session, action["configure"]))
                session = driver.session
                self.stdout.write(f"#{number} конфигурация: "
                                  f"{'изменена' if changed else 'без изменений'} → этап {session.active_stage}")
                self._print_node(session, "после смены")
                return
            elif action.get("to_end"):
                report = driver.to_end()
                label = "досчитать до конца"
            elif action.get("stop"):
                driver.stop()
                self.stdout.write(f"#{number} остановлено пользователем.")
                return
            else:
                raise CommandError(f"#{number}: неизвестное действие {action!r}")
        except ValueError as exc:
            raise CommandError(f"#{number}: {exc}") from exc

        self.stdout.write(f"#{number} {label} → {report.reason} (регулярных шагов: {report.grid_steps})"
                          + (" · РАЗВОРОТ" if report.turned else ""))
        for event in report.switches:
            self.stdout.write(f"     переключение {event.direction}: этап {event.stage_from}→{event.stage_to} "
                              f"при x={_fmt(event.x, 9)} м, t={_fmt(event.t)} с, v={_fmt(event.v)} м/с")
        self._print_node(driver.session, "узел")

    def _new_config(self, session: IterativeSession, edits: list[dict]) -> list:
        config = list(session.config)
        for edit in edits:
            slot = int(edit["slot"])
            if slot == len(config):
                config.append(None)
            elif not 0 <= slot < len(config):
                raise CommandError(f"Слот {slot}: вне диапазона (тормозов {len(config)}).")
            config[slot] = self._slot_from_spec(edit, config[slot], self._last_parametric(session, slot))
        return config

    @staticmethod
    def _last_parametric(session: IterativeSession, slot: int):
        """Последние параметры слота (для «set» по отключённому тормозу — повторное включение)."""
        for stage in reversed(session.stages[:session.active_stage + 1]):
            if slot < len(stage.config) and isinstance(stage.config[slot], MagneticParams):
                return stage.config[slot]
        return None

    @staticmethod
    def _slot_from_spec(spec: dict, current=None, fallback=None):
        if spec.get("off"):
            return None
        if "set" in spec:
            base = current if isinstance(current, MagneticParams) else fallback
            if base is None:
                raise CommandError("«set»: у тормоза нет параметрической конфигурации — "
                                   "задайте её полностью через «parametric».")
            return replace(base, **spec["set"])
        if "parametric" in spec:
            base = asdict(current) if isinstance(current, MagneticParams) else {}
            base.update(spec["parametric"])
            return MagneticParams(**base)
        if "curve" in spec:
            return CurveBrakeParams(points=tuple(
                ForceCurvePoint(velocity=float(v), force=float(f)) for v, f in spec["curve"]))
        raise CommandError(f"Непонятное описание тормоза: {spec!r}")

    # ------------------------------------------------------------------- вход

    @staticmethod
    def _load_scenario(path: str | None) -> dict:
        if not path:
            return {}
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Не удалось прочитать сценарий: {exc}") from exc

    @staticmethod
    def _load_run(run_id: int) -> CalculationRun:
        run = CalculationRun.objects.filter(pk=run_id).first()
        if run is None:
            raise CommandError(f"Расчёт #{run_id} не найден.")
        return run

    @staticmethod
    def _recoil_params(run, overrides: dict) -> RecoilParams:
        values = {f: getattr(run, f) for f in _RECOIL_FIELDS} if run else {}
        unknown = set(overrides) - set(_RECOIL_FIELDS)
        if unknown:
            raise CommandError(f"Неизвестные параметры recoil: {sorted(unknown)}")
        values.update(overrides)
        if "mass" not in values:
            raise CommandError("Не задана масса (нужен донор или recoil.mass).")
        return RecoilParams(**{k: float(v) for k, v in values.items()})

    @staticmethod
    def _drive(run, scenario: dict, mode: str):
        if mode != MODE_RECOIL:
            return None
        path = scenario.get("input_file")
        if not path:
            if not (run and run.input_file):
                raise CommandError("Для отката нужен входной файл (донор с файлом или input_file).")
            path = run.input_file.path
        return load_recoil_characteristics(path)

    def _initial_config(self, run, scenario: dict) -> list:
        if scenario.get("brakes"):
            return [self._slot_from_spec(spec) for spec in scenario["brakes"]]
        if run is None:
            raise CommandError("Не заданы тормоза (нужен донор или brakes).")
        brakes = MagneticBrakeConfig.objects.filter(run=run).order_by("index")
        config = [slot_from_brake_config(b) for b in brakes]
        if not config:
            raise CommandError(f"У расчёта #{run.id} нет тормозов.")
        return config

    # ------------------------------------------------------------------ вывод

    def _print_node(self, session: IterativeSession, label: str) -> None:
        cur = session.current()
        forces = ", ".join(_fmt(f, 5) for f in cur["f_each"])
        self.stdout.write(
            f"     {label}: t={_fmt(cur['t'])} с · x={_fmt(cur['x'])} м · v={_fmt(cur['v'])} м/с · "
            f"a={_fmt(cur['a'])} м/с² · F_торм={_fmt(cur['f_magnetic'], 5)} Н [{forces}] · "
            f"фаза {cur['phase']} · этап {cur['stage']}"
            + (" · ЗАВЕРШЁН" if cur["finished"] else ""))

    def _print_summary(self, session: IterativeSession, outcome) -> None:
        res = outcome.result
        self.stdout.write(self.style.MIGRATE_HEADING("\nИтог"))
        v_end = res.v[res.return_end_index] if res.return_end_index is not None else None
        self.stdout.write(
            f"завершение: {res.termination_reason} · узлов: {len(res.t)} · "
            f"x_max={_fmt(np.max(res.x))} м · разворот t={_fmt(res.recoil_end_time)} с · "
            f"конец наката T={_fmt(res.return_end_time)} с · v_end={_fmt(v_end)} м/с")
        self.stdout.write(
            f"пик |F_торм|={_fmt(np.max(np.abs(res.f_magnetic)), 5)} Н · "
            f"невязка энергобаланса={_fmt(res.energy_residual_pct, 4)} %")

        self.stdout.write(self.style.MIGRATE_HEADING("Этапы"))
        for stage in outcome.stages:
            kinds = " ".join(KIND_LABELS[slot_kind(s)] for s in stage.config)
            if stage.index == 0:
                where = "исходная"
            elif session.mode == MODE_FREE_FALL:
                where = f"x={_fmt(stage.x, 9)} м · включён t={_fmt(stage.t)} с, v={_fmt(stage.v)} м/с"
            else:
                where = (f"x={_fmt(stage.x, 9)} м · откат t={_fmt(stage.t)} с, v={_fmt(stage.v)} м/с · "
                         f"накат t={_fmt(stage.return_t)} с, v={_fmt(stage.return_v)} м/с")
            self.stdout.write(f"  этап {stage.index}: [{kinds}] · {where}")
            if stage.index > 0:
                for line in config_diff(outcome.stages[stage.index - 1].config, stage.config):
                    self.stdout.write(f"      {line}")
        for warning in res.warnings:
            self.stdout.write(self.style.WARNING(f"⚠ {warning}"))

    def _compare_plain(self, session, outcome, mode, recoil, drive) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Сравнение с обычным расчётом C₀"))
        if len(outcome.stages) > 1:
            self.stdout.write(self.style.WARNING(
                "Конфигурацию меняли — совпадения с обычным расчётом не ожидается."))
        models = [s for s in outcome.stages[0].config if s is not None]
        plain = (simulate_recoil_core(*drive, recoil, models) if mode == MODE_RECOIL
                 else simulate_free_fall(recoil, models))
        res = outcome.result
        all_equal = True
        for name in _COMPARE:
            a, b = getattr(plain, name), getattr(res, name)
            if a.shape != b.shape:
                self.stdout.write(f"  {name}: разная длина {a.shape} vs {b.shape}")
                all_equal = False
                continue
            equal = np.array_equal(a, b)
            all_equal &= equal
            self.stdout.write(f"  {name}: " + ("совпадает бит-в-бит" if equal else
                                               f"max|Δ|={np.max(np.abs(a - b)):.3e}"))
        if all_equal:
            self.stdout.write(self.style.SUCCESS("Итерационный прогон совпадает с обычным расчётом бит-в-бит."))

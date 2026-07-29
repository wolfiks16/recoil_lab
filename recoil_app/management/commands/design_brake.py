"""MVP обратного проектирования тормоза.

Синтезирует характеристику одиночного curve-тормоза F(|v|), обеспечивающую
заданные конечные условия цикла (T, x_max, v_end) при потолке ΣF, и оценивает
робастность к индивидуальным допускам узлов кривой.

Пример:
    python manage.py design_brake --from-run 12 \
        --T 0.9 --xmax 0.45 --vend 0.2 --sigma-f-max 80000 \
        --tol 800,1200,1600,2000 --plot
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recoil_app.models import CalculationRun
from recoil_app.services.design import (
    DesignConstraints,
    DesignTargets,
    ToleranceModel,
    run_design_study,
)


def _fmt(v, prec=6):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{prec}g}"
    except (TypeError, ValueError):
        return str(v)


class Command(BaseCommand):
    help = "Обратное проектирование характеристики тормоза под конечные условия цикла (MVP)."

    def add_arguments(self, parser):
        parser.add_argument("--from-run", type=int, required=True,
                            help="ID расчёта-донора привода (F(t)/F(x), масса, угол, dt).")
        parser.add_argument("--T", type=float, required=True, help="Целевое время цикла, с.")
        parser.add_argument("--xmax", type=float, required=True, help="Целевой откат x_max, м.")
        parser.add_argument("--vend", type=float, required=True,
                            help="Целевая |скорость| в момент x=0 (конец наката), м/с.")
        parser.add_argument("--sigma-f-max", type=float, required=True,
                            help="Потолок суммарного усилия тормозов ΣF_max, Н.")
        parser.add_argument("--nodes", type=int, default=4,
                            help="Число свободных узлов кривой F(v) (default 4).")
        parser.add_argument("--tol", type=str, default="",
                            help="Допуски узлов (Н): одно число (равномерно) или список через запятую. "
                                 "По умолчанию 2%% от ΣF_max на узел.")
        parser.add_argument("--rel-tol", type=float, default=0.02,
                            help="Относительный допуск попадания в цель (default 0.02).")
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--plot", action="store_true",
                            help="Сохранить standalone HTML-график F(v).")
        parser.add_argument("--parametric", action="store_true",
                            help="Stage 2: подобрать физические параметры тормоза под кривую "
                                 "(+ end-to-end доводка под метрики, робастность). Медленнее.")
        parser.add_argument("--param-tol", type=float, default=0.02,
                            help="Относительный допуск на параметры для робастности Stage 2 (default 0.02).")
        parser.add_argument("--brakes", type=int, default=1,
                            help="Число тормозов N (≥2 → раскладка ΣF + совместная доводка). "
                                 "Включает Stage 2 автоматически.")
        parser.add_argument("--weights", type=str, default="",
                            help="Веса раскладки ΣF по тормозам (через запятую, N значений). "
                                 "По умолчанию поровну.")
        parser.add_argument("--multistart", action="store_true",
                            help="Перебрать семейство кандидатов (для 1 тормоза — разные n; "
                                 "для N — разные раскладки ΣF) и выбрать самый робастный. "
                                 "Включает Stage 2.")

    def handle(self, *args, **opts):
        run = self._load_run(opts["from_run"])

        n_free = opts["nodes"]
        sigma_f_max = opts["sigma_f_max"]
        tol = self._parse_tol(opts["tol"], n_free, sigma_f_max)

        targets = DesignTargets(T=opts["T"], x_max=opts["xmax"], v_end=opts["vend"],
                                rel_tol=opts["rel_tol"])
        constraints = DesignConstraints(sigma_f_max=sigma_f_max, n_free_nodes=n_free)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nОбратное проектирование тормоза · донор расчёт «{run.name}» (#{run.id})"))
        self.stdout.write(
            f"Цели: T={_fmt(targets.T)} с · x_max={_fmt(targets.x_max)} м · "
            f"v_end={_fmt(targets.v_end)} м/с · допуск ±{targets.rel_tol*100:.0f}%")
        self.stdout.write(
            f"Ограничение: ΣF ≤ {_fmt(sigma_f_max)} Н · узлов={n_free} · "
            f"допуски узлов={[round(t, 1) for t in tol.node_tol]} Н")
        self.stdout.write("Считаю (синтез + верификация + робастность)…\n")

        n_brakes = max(1, opts["brakes"])
        if n_brakes > 4:
            raise CommandError("Для MVP --brakes ограничено 4 (дальше слишком долго).")
        use_ms = opts["multistart"]
        do_stage2 = opts["parametric"] or n_brakes >= 2 or use_ms
        weights = self._parse_weights(opts["weights"], n_brakes)
        if use_ms and weights is not None:
            self.stdout.write(self.style.WARNING(
                "--weights игнорируется при --multistart (раскладки перебираются автоматически)."))

        if do_stage2:
            mode = "мультистарт + отбор по робастности" if use_ms else f"{n_brakes} тормоз(а)"
            self.stdout.write(f"Stage 2 включён ({mode}) — после синтеза кривой это дольше…")

        result = run_design_study(
            input_file_path=run.input_file.path,
            mass=run.mass, angle_deg=run.angle_deg, v0=run.v0, x0=run.x0,
            base_dt=run.dt,
            targets=targets, constraints=constraints, tol=tol, seed=opts["seed"],
            fit_parametric=do_stage2, param_tol_rel=opts["param_tol"],
            n_brakes=n_brakes, weights=weights, multistart=use_ms,
        )

        self._print_result(result, run)

        if result.multistart_result is not None:
            self._print_multistart(result.multistart_result, constraints, n_brakes)
        elif result.parametric is not None:
            self._print_parametric(result.parametric, constraints)
        elif result.multi is not None:
            self._print_multi(result.multi, constraints)

        if opts["plot"]:
            self._save_plot(result, run)

    # --- helpers ---

    def _load_run(self, run_id: int) -> CalculationRun:
        try:
            run = CalculationRun.objects.get(pk=run_id)
        except CalculationRun.DoesNotExist as exc:
            raise CommandError(f"Расчёт #{run_id} не найден.") from exc
        if run.is_free_fall or not run.input_file:
            raise CommandError(
                "Донор должен быть расчётом отката с входным файлом (выстрел + пружина). "
                "Расчёт свободного падения не подходит."
            )
        return run

    def _parse_tol(self, raw: str, n_free: int, sigma_f_max: float) -> ToleranceModel:
        raw = (raw or "").strip()
        if not raw:
            return ToleranceModel.from_fraction(n_free, sigma_f_max, 0.02)
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        try:
            vals = [float(p) for p in parts]
        except ValueError as exc:
            raise CommandError(f"Не удалось разобрать --tol: {raw!r}") from exc
        if len(vals) == 1:
            return ToleranceModel.uniform(n_free, vals[0])
        if len(vals) != n_free:
            raise CommandError(
                f"--tol: ожидалось 1 или {n_free} значений, получено {len(vals)}."
            )
        return ToleranceModel(node_tol=tuple(vals))

    def _parse_weights(self, raw: str, n: int):
        raw = (raw or "").strip()
        if not raw:
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        try:
            vals = [float(p) for p in parts]
        except ValueError as exc:
            raise CommandError(f"Не удалось разобрать --weights: {raw!r}") from exc
        if len(vals) != n:
            raise CommandError(f"--weights: ожидалось {n} значений, получено {len(vals)}.")
        if any(v <= 0 for v in vals):
            raise CommandError("--weights: все веса должны быть положительными.")
        return vals

    def _print_result(self, r, run):
        w = self.stdout.write
        style = self.style

        verdict = style.SUCCESS("✔ ДОСТИЖИМО") if r.feasible else style.ERROR("✘ НЕ достигнуто в допуске")
        w(f"\n=== ВЕРДИКТ: {verdict} ===")

        a, t = r.achieved, r.targets
        w("\nДостигнуто vs цель:")
        w(f"  {'метрика':<10}{'цель':>14}{'достигнуто':>16}{'откл.':>12}")
        for key, tgt, ach in (("x_max", t.x_max, a.x_max),
                              ("T", t.T, a.T),
                              ("v_end", t.v_end, a.v_end)):
            err = r.rel_error.get(key)
            err_s = f"{err*100:+.2f}%" if err is not None and err == err else "—"
            w(f"  {key:<10}{_fmt(tgt):>14}{_fmt(ach):>16}{err_s:>12}")

        sigma_f_max = r.sim.get("sigma_f_max")
        w(f"\nΣF пик = {_fmt(a.sigma_f_peak)} Н  (потолок ΣF_max = {_fmt(sigma_f_max)} Н · "
          f"задействовано {_fmt(max(r.f_nodes) if r.f_nodes else 0.0)} Н)")

        # Синтезированная характеристика
        w("\nСинтезированная характеристика F(v):")
        w(f"  {'v, м/с':>12}{'F, Н':>14}")
        for v, f in zip(r.v_nodes, r.f_nodes):
            w(f"  {_fmt(v):>12}{_fmt(f):>14}")

        # Робастность
        if r.robustness is not None:
            rob = r.robustness
            w("\nРобастность (разброс метрик от допусков узлов):")
            w(f"  R (свёртка, меньше = лучше) = {_fmt(rob.R, 4)}")
            for k in ("x_max", "T", "v_end"):
                w(f"    σ[{k}] = {_fmt(rob.sigma_abs[k], 4)}  "
                  f"(отн. {_fmt(rob.rel_sigma[k]*100, 3)}%)")
            margin = rob.sigma_f_margin
            margin_s = "∞" if margin == float("inf") else f"{margin:.1f}σ"
            w(f"  Запас до ΣF_max = {margin_s}")

        # Envelope
        env = r.envelope
        w("\nEnvelope достижимости (откат x_max):")
        w(f"  без торможения: x_max={_fmt(env['no_brake'].x_max)} м, "
          f"цикл={'да' if env['no_brake'].completed else 'нет'}")
        w(f"  макс. торможение: x_max={_fmt(env['full_brake'].x_max)} м, "
          f"цикл={'да' if env['full_brake'].completed else 'нет'}")

        # Диагностика / сообщения
        if r.messages:
            w("\nДиагностика:")
            for m in r.messages:
                w(f"  • {m}")

        w(f"\n(t_sim={_fmt(r.sim['t_sim'])} с · work_dt={_fmt(r.sim['work_dt'])} с · "
          f"v_peak≈{_fmt(r.sim['v_peak'])} м/с · synth_loss={_fmt(r.synth_loss, 4)})\n")

    def _print_parametric(self, pr, constraints):
        w = self.stdout.write
        style = self.style

        w(style.MIGRATE_HEADING("\n\n════ СТАДИЯ 2 · подбор физических параметров ════"))

        verdict = (style.SUCCESS("✔ параметры обеспечивают цели")
                   if (pr.within_tol and pr.sigma_f_ok)
                   else style.ERROR("✘ цели не достигнуты в допуске"))
        w(f"Вердикт: {verdict}")

        w(f"\nПодгон под кривую: RMSE {pr.fit.curve_rmse*100:.2f}% → "
          f"после доводки под метрики {pr.curve_rmse_final*100:.2f}% (форма уступила метрикам)")

        p = pr.params_final
        w("\nИтоговые физические параметры тормоза:")
        rows = [("gamma (проводник)", p.gamma), ("delta", p.delta), ("n", p.n),
                ("xm", p.xm), ("ym", p.ym), ("dh1", p.dh1), ("dh2", p.dh2),
                ("dm", p.dm), ("mu", p.mu), ("bz (B̄₃)", p.bz), ("lya", p.lya), ("wn0", p.wn0)]
        for name, val in rows:
            w(f"    {name:<18}{_fmt(val)}")

        a = pr.achieved
        w("\nПолная динамика с этими параметрами vs цель:")
        w(f"  {'метрика':<10}{'достигнуто':>16}{'откл.':>12}")
        for key, ach in (("x_max", a.x_max), ("T", a.T), ("v_end", a.v_end)):
            err = pr.rel_error.get(key)
            err_s = f"{err*100:+.2f}%" if err is not None and err == err else "—"
            w(f"  {key:<10}{_fmt(ach):>16}{err_s:>12}")

        cap_s = style.SUCCESS("в пределах") if pr.sigma_f_ok else style.ERROR("ПРЕВЫШЕН")
        w(f"\nΣF пик = {_fmt(pr.sigma_f_peak)} Н / потолок {_fmt(constraints.sigma_f_max)} Н → {cap_s}")

        rob = pr.robustness or {}
        if rob:
            w("\nРобастность к допускам параметров:")
            w(f"  R = {_fmt(rob.get('R'), 4)}")
            rs = rob.get("rel_sigma", {})
            for k in ("x_max", "T", "v_end"):
                if k in rs:
                    w(f"    отн. σ[{k}] = {_fmt(rs[k]*100, 3)}%")
            margin = rob.get("sigma_f_margin", float("inf"))
            margin_s = "∞" if margin == float("inf") else f"{margin:.1f}σ"
            w(f"  Запас до ΣF_max = {margin_s}")
            # самый влиятельный параметр (по |вкладу в T|)
            pp = [x for x in rob.get("per_param", []) if x.get("T") == x.get("T")]
            if pp:
                dom = max(pp, key=lambda x: abs(x["T"]))
                w(f"  Самый влиятельный параметр (на T): {dom['param']}")

        if pr.messages:
            w("\nДиагностика Stage 2:")
            for m in pr.messages:
                w(f"  • {m}")

    def _print_multi(self, mr, constraints):
        w = self.stdout.write
        style = self.style

        w(style.MIGRATE_HEADING(
            f"\n\n════ СТАДИЯ 2 · {mr.n_brakes} тормоза · подбор параметров ════"))
        verdict = (style.SUCCESS("✔ N тормозов обеспечивают цели")
                   if (mr.within_tol and mr.sigma_f_ok)
                   else style.ERROR("✘ цели не достигнуты в допуске"))
        w(f"Вердикт: {verdict}")
        w("Раскладка ΣF по весам: " + ", ".join(f"{100*x:.0f}%" for x in mr.weights))

        for i, (b, rmse) in enumerate(zip(mr.brakes, mr.per_brake_curve_rmse), start=1):
            w(f"\nТормоз {i} (доля {100*mr.weights[i-1]:.0f}% · curve-fit RMSE {rmse*100:.1f}%):")
            w(f"    delta={_fmt(b.delta)} n={b.n} xm={_fmt(b.xm)} ym={_fmt(b.ym)} "
              f"dh1={_fmt(b.dh1)} dh2={_fmt(b.dh2)} dm={_fmt(b.dm)} bz={_fmt(b.bz)}")

        a = mr.achieved
        w("\nПолная динамика (сумма N тормозов) vs цель:")
        w(f"  {'метрика':<10}{'достигнуто':>16}{'откл.':>12}")
        for key, ach in (("x_max", a.x_max), ("T", a.T), ("v_end", a.v_end)):
            err = mr.rel_error.get(key)
            err_s = f"{err*100:+.2f}%" if err is not None and err == err else "—"
            w(f"  {key:<10}{_fmt(ach):>16}{err_s:>12}")

        cap_s = style.SUCCESS("в пределах") if mr.sigma_f_ok else style.ERROR("ПРЕВЫШЕН")
        w(f"\nСуммарный ΣF пик = {_fmt(mr.sigma_f_peak)} Н / потолок "
          f"{_fmt(constraints.sigma_f_max)} Н → {cap_s}")

        rob = mr.robustness or {}
        if rob:
            w("\nРобастность к допускам параметров (все тормоза):")
            w(f"  R = {_fmt(rob.get('R'), 4)}")
            rs = rob.get("rel_sigma", {})
            for k in ("x_max", "T", "v_end"):
                if k in rs:
                    w(f"    отн. σ[{k}] = {_fmt(rs[k]*100, 3)}%")
            margin = rob.get("sigma_f_margin", float("inf"))
            margin_s = "∞" if margin == float("inf") else f"{margin:.1f}σ"
            w(f"  Запас до ΣF_max = {margin_s}")
            pp = [x for x in rob.get("per_param", []) if x.get("T") == x.get("T")]
            if pp:
                dom = max(pp, key=lambda x: abs(x["T"]))
                w(f"  Самый влиятельный (на T): тормоз {dom['brake']} · {dom['param']}")

        if mr.messages:
            w("\nДиагностика Stage 2:")
            for m in mr.messages:
                w(f"  • {m}")

    def _print_multistart(self, ms, constraints, n_brakes):
        w = self.stdout.write
        style = self.style

        w(style.MIGRATE_HEADING(
            "\n\n════ МУЛЬТИСТАРТ · отбор по робастности ════"))
        w(f"Оценено кандидатов: {ms.n_evaluated} (грубый скрининг) · допустимо: {ms.n_feasible}")
        w("Ранжирование (допустимые — по возрастанию R = меньше = робастнее):")
        w(f"  {'#':<3}{'кандидат':<16}{'цель':>8}{'R':>10}{'макс.откл':>12}{'':>8}")
        for i, c in enumerate(ms.candidates, start=1):
            ok = "да" if c.feasible else "нет"
            r_s = _fmt(c.R, 4) if c.R == c.R and c.R != float("inf") else "—"
            err_s = f"{c.max_abs_err*100:.1f}%" if c.max_abs_err == c.max_abs_err else "—"
            mark = " ★" if (ms.best and c is ms.best) else ""
            w(f"  {i:<3}{c.label:<16}{ok:>8}{r_s:>10}{err_s:>12}{mark:>8}")

        if ms.best is None:
            w(style.ERROR("\nНи один кандидат не попал в цель в допуске. "
                          "Ослабьте цели/ΣF или расширьте границы параметров."))
            return

        w(style.SUCCESS(f"\nВЫБРАН самый робастный: «{ms.best.label}» "
                        f"(R={_fmt(ms.best.R, 4)}, доведён на рабочем dt)"))

        # Детальный вывод победителя (single или N).
        res = ms.best.result
        if n_brakes <= 1:
            self._print_parametric(res, constraints)
        else:
            self._print_multi(res, constraints)

    def _save_plot(self, r, run):
        from recoil_app.services.charting import make_brake_curve_fragment

        points = [{"velocity": float(v), "force": float(f)}
                  for v, f in zip(r.v_nodes, r.f_nodes)]
        fragment = make_brake_curve_fragment(points, title="Синтезированная F(v)")

        out_dir = Path(settings.MEDIA_ROOT) / "design"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"design_brake_run{run.id}.html"

        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"
            f"<title>F(v) · {run.name}</title></head><body>{fragment}</body></html>"
        )
        out_path.write_text(html, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"График сохранён: {out_path}"))

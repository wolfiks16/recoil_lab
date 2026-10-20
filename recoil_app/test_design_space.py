"""Тесты границ подбора тормоза и ограничения длины шины (`services/design/space.py`,
`objective.py`, форма/страницы «Подбор тормоза»). Без долгих полных прогонов подбора."""

from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .forms import DesignStudyForm
from .models import CalculationRun, DesignStudy, MagneticBrakeConfig
from .services.design.forward import Metrics
from .services.design.multi_brake import refine_multi_end_to_end
from .services.design.multistart import _default_configs
from .services.design.objective import (
    BUS_REL_TOL,
    bus_overshoot,
    bus_report,
    design_residuals,
    system_length,
)
from .services.design.param_fit import (
    fit_parametric_to_curve,
    params_from_vec,
    quasistatic_curve,
    refine_parametric_end_to_end,
)
from .services.design.persist import study_summary
from .services.design.runner import study_inputs
from .services.design.space import (
    CONT_PARAMS,
    DEFAULT_BOUNDS,
    ParamSpace,
    bound_hits,
    bound_hits_message,
    brake_param_table,
    build_space,
    n_choices_range,
    space_with_overrides,
)
from .services.design.targets import DesignTargets
from .services.magnetic import MagneticParams

BRAKE = MagneticParams(gamma=1.77e7, delta=0.006, xm=0.022, ym=0.55, dh1=0.02, dh2=0.02,
                       dm=0.014, n=12, mu=1.0, bz=0.83)
TARGETS = DesignTargets(T=1.6, x_max=0.9, v_end=0.5, rel_tol=0.05)


def _metrics(x_max=0.8, completed=True):
    return Metrics(x_max=x_max, T=1.0 if completed else None, v_end=0.1 if completed else None,
                   sigma_f_peak=1000.0, completed=completed)


class ParamSpaceTests(SimpleTestCase):

    def test_default_roundtrip_and_empty(self):
        space = ParamSpace.default()
        self.assertEqual(space.free_params, CONT_PARAMS)
        again = ParamSpace.from_dict(space.to_dict())
        self.assertEqual(again.to_dict(), space.to_dict())
        self.assertEqual(ParamSpace.from_dict(None).to_dict(), space.to_dict())

    def test_fixed_excluded_from_vector(self):
        space = space_with_overrides(ParamSpace.default(), fixed={"bz": 1.2, "ym": 0.5})
        self.assertEqual(space.free_params, ("delta", "xm", "dh1", "dh2", "dm"))
        p = params_from_vec([0.004, 0.02, 0.01, 0.01, 0.01], 10, space)
        self.assertEqual((p.bz, p.ym, p.n, p.gamma), (1.2, 0.5, 10, 1.77e7))
        self.assertEqual((p.delta, p.xm, p.dm), (0.004, 0.02, 0.01))

    def test_validation(self):
        bounds = dict(DEFAULT_BOUNDS)
        fixed = {"gamma": 1.77e7, "mu": 1.0, "lya": 2.5, "wn0": 1.0}
        with self.assertRaises(ValueError):   # bz и в диапазоне, и зафиксирован
            ParamSpace(cont_bounds=bounds, n_choices=(8,), fixed={**fixed, "bz": 1.0})
        with self.assertRaises(ValueError):   # bz нигде
            ParamSpace(cont_bounds={k: v for k, v in bounds.items() if k != "bz"},
                       n_choices=(8,), fixed=fixed)
        with self.assertRaises(ValueError):   # lo ≥ hi
            ParamSpace(cont_bounds={**bounds, "xm": (0.03, 0.02)}, n_choices=(8,), fixed=fixed)
        with self.assertRaises(ValueError):   # нет вариантов N
            ParamSpace(cont_bounds=bounds, n_choices=(), fixed=fixed)

    def test_n_choices_range_and_build_space(self):
        self.assertEqual(n_choices_range(8, 24, 2), (8, 10, 12, 14, 16, 18, 20, 22, 24))
        self.assertEqual(n_choices_range(5, 10, 3), (5, 8))
        rows = {p: ("free", *DEFAULT_BOUNDS[p]) for p in CONT_PARAMS}
        rows["bz"] = ("fixed", 1.1)
        space = build_space(rows, (16,), 5.8e7)
        self.assertTrue(space.n_fixed)
        self.assertEqual(space.fixed["bz"], 1.1)
        self.assertEqual(space.fixed["gamma"], 5.8e7)
        self.assertNotIn("bz", space.free_params)

    def test_bound_hits(self):
        space = ParamSpace.default()
        p = SimpleNamespace(delta=0.008, xm=0.012, ym=0.4, dh1=0.02, dh2=0.02, dm=0.01, bz=1.0, n=24)
        hits = {h["param"]: h["side"] for h in bound_hits(p, space)}
        self.assertEqual(hits, {"delta": "max", "xm": "min", "n": "max"})
        self.assertIn("δ — у максимума", bound_hits_message([bound_hits(p, space)]))
        self.assertIsNone(bound_hits_message([[]]))
        # N зафиксирован — у границы быть не может.
        self.assertNotIn("n", {h["param"] for h in bound_hits(p, space.with_n_choices((24,)))})

    def test_brake_param_table(self):
        space = space_with_overrides(ParamSpace.default(), fixed={"bz": 0.83})
        params = {"gamma": 1.77e7, "delta": 0.008, "xm": 0.02, "ym": 0.5, "dh1": 0.02,
                  "dh2": 0.02, "dm": 0.01, "n": 12, "mu": 1.0, "bz": 0.83, "lya": 2.5, "wn0": 1.0}
        second = {**params, "delta": 0.004}
        rows = {r["field"]: r for r in brake_param_table([params, second], space)}
        self.assertNotIn("lya", rows)
        self.assertNotIn("wn0", rows)
        self.assertFalse(rows["bz"]["free"])
        self.assertFalse(rows["gamma"]["free"])
        self.assertEqual((rows["xm"]["lo"], rows["xm"]["hi"]), DEFAULT_BOUNDS["xm"])
        self.assertEqual(rows["n"]["lo"], 8)
        # Столбец на тормоз: у первого δ у максимума, у второго — нет.
        self.assertEqual([c["value"] for c in rows["delta"]["cells"]], [0.008, 0.004])
        self.assertEqual([c["hit"] for c in rows["delta"]["cells"]], ["max", None])

    def test_default_configs_with_fixed_n(self):
        space = ParamSpace.default().with_n_choices((14,))
        self.assertEqual([c["n"] for c in _default_configs(1, space)], [14])


class BusConstraintTests(SimpleTestCase):

    def test_system_length(self):
        self.assertAlmostEqual(system_length(12, 0.022, 0.014), 12 * 0.022 + 11 * 0.014)
        self.assertAlmostEqual(system_length(1, 0.03, 0.5), 0.03)

    def test_overshoot(self):
        length = system_length(BRAKE.n, BRAKE.xm, BRAKE.dm)        # 0.418 м
        self.assertEqual(bus_overshoot([BRAKE], 0.5, None), 0.0)
        self.assertEqual(bus_overshoot([BRAKE], 0.5, length + 0.6), 0.0)
        self.assertAlmostEqual(bus_overshoot([BRAKE], 0.5, 0.8), (length + 0.5 - 0.8) / 0.8)
        self.assertEqual(bus_overshoot([BRAKE], float("nan"), length), 0.0)   # ход неизвестен → 0
        # Берётся худший тормоз (у каждого своя шина той же длины).
        self.assertAlmostEqual(bus_overshoot([BRAKE, replace(BRAKE, n=16)], 0.0, 0.5),
                               (system_length(16, BRAKE.xm, BRAKE.dm) - 0.5) / 0.5)

    def test_report(self):
        self.assertIsNone(bus_report([BRAKE], 0.5, None))
        rep = bus_report([BRAKE], 0.5, 1.0)
        self.assertTrue(rep["fits"])
        self.assertAlmostEqual(rep["required"], system_length(12, 0.022, 0.014) + 0.5)
        self.assertAlmostEqual(rep["margin"], 1.0 - rep["required"])
        self.assertFalse(bus_report([BRAKE], 0.7, 1.0)["fits"])
        self.assertTrue(bus_report([BRAKE], 0.582 + 0.5 * BUS_REL_TOL, 1.0)["fits"])  # численный шум
        self.assertFalse(bus_report([BRAKE], None, 1.0)["fits"])                     # цикл не завершился

    def test_residuals_length_constant(self):
        # Система 0.418 м + ход 0.8 м = 1.218 м: на шине 1.5 м помещается, на 1.0 м — нет.
        fits = design_residuals(_metrics(), TARGETS, 2000.0, brakes=[BRAKE], bus_length=1.5)
        short = design_residuals(_metrics(), TARGETS, 2000.0, brakes=[BRAKE], bus_length=1.0)
        failed = design_residuals(_metrics(completed=False), TARGETS, 2000.0,
                                  brakes=[BRAKE], bus_length=1.0)
        self.assertEqual([len(fits), len(short), len(failed)], [6, 6, 6])
        self.assertEqual(len(design_residuals(_metrics(), TARGETS, 2000.0)), 5)
        self.assertEqual(fits[-1], 0.0)
        self.assertGreater(short[-1], 0.0)
        np.testing.assert_array_equal(fits[:5], short[:5])


class ParamFitSpaceTests(SimpleTestCase):
    """Подгон под кривую уважает фиксацию и шину (квазистатика — без динамики, быстро)."""

    v_grid = np.linspace(0.5, 10.0, 12)

    def test_fixed_bz_kept_and_bounds_respected(self):
        target = quasistatic_curve(self.v_grid, BRAKE)
        space = space_with_overrides(
            ParamSpace.default(), fixed={"bz": 0.83, "ym": 0.55, "dh1": 0.02, "dh2": 0.02},
            bounds={"xm": (0.015, 0.03), "dm": (0.008, 0.02), "delta": (0.004, 0.008)},
            n_choices=(12,))
        fit = fit_parametric_to_curve(self.v_grid, target, space, maxiter=10, popsize=6)
        self.assertEqual(fit.params.bz, 0.83)
        self.assertEqual(fit.params.ym, 0.55)
        for name in space.free_params:
            lo, hi = space.cont_bounds[name]
            self.assertTrue(lo <= getattr(fit.params, name) <= hi, name)
        self.assertLess(fit.curve_rmse, 0.05)

    def test_all_dimensions_fixed_picks_n(self):
        target = quasistatic_curve(self.v_grid, BRAKE)
        fixed = {p: getattr(BRAKE, p) for p in CONT_PARAMS}
        space = space_with_overrides(ParamSpace.default(), fixed=fixed, n_choices=(8, 12, 16))
        self.assertEqual(space.free_params, ())
        fit = fit_parametric_to_curve(self.v_grid, target, space)
        self.assertEqual(fit.n, 12)
        self.assertAlmostEqual(fit.curve_rmse, 0.0, places=9)

    def test_bus_penalty_in_curve_fit(self):
        """Без шины лучший по кривой — длинный n=16; шина 0,5 м с ходом 0,1 м его отсекает."""
        target = quasistatic_curve(self.v_grid, replace(BRAKE, n=16))
        fixed = {p: getattr(BRAKE, p) for p in CONT_PARAMS}
        space = space_with_overrides(ParamSpace.default(), fixed=fixed, n_choices=(8, 16))
        self.assertEqual(fit_parametric_to_curve(self.v_grid, target, space).n, 16)
        # n=16: 0.562 м + ход 0.1 м > 0.5 м — штраф; n=8: 0.274 + 0.1 — помещается.
        fit = fit_parametric_to_curve(self.v_grid, target, space, bus_length=0.5, stroke=0.1)
        self.assertEqual(fit.n, 8)
        self.assertLessEqual(system_length(fit.n, fit.params.xm, fit.params.dm) + 0.1, 0.5)

    def test_refine_without_free_params_is_noop(self):
        fixed = {p: getattr(BRAKE, p) for p in CONT_PARAMS}
        space = space_with_overrides(ParamSpace.default(), fixed=fixed, n_choices=(12,))
        # drive=None: при пустом векторе поиска динамика не вызывается вовсе.
        self.assertIs(refine_parametric_end_to_end(None, None, BRAKE, TARGETS, space), BRAKE)
        self.assertEqual(refine_multi_end_to_end(None, None, [BRAKE, BRAKE], TARGETS, space),
                         [BRAKE, BRAKE])


class StudySnapshotTests(SimpleTestCase):

    def _study(self, **kw):
        base = dict(target_T=1.6, target_x_max=0.9, target_v_end=0.5, rel_tol=0.05,
                    sigma_f_max=2000.0, n_nodes=4, n_brakes=2, param_tol_rel=0.02,
                    do_parametric=True, multistart=False, param_space=None, bus_length=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_study_inputs_default_and_custom_space(self):
        inputs = study_inputs(self._study())
        self.assertEqual(inputs["space"].to_dict(), ParamSpace.default().to_dict())
        self.assertIsNone(inputs["constraints"].bus_length)

        custom = space_with_overrides(ParamSpace.default(), fixed={"bz": 1.0}, n_choices=(10,))
        inputs = study_inputs(self._study(param_space=custom.to_dict(), bus_length=1.2))
        self.assertEqual(inputs["space"].fixed["bz"], 1.0)
        self.assertEqual(inputs["space"].n_choices, (10,))
        self.assertEqual(inputs["constraints"].bus_length, 1.2)
        self.assertEqual(inputs["n_brakes"], 2)

    def test_summary_requires_bus(self):
        s1 = {"feasible": True, "robustness": {"R": 0.5}}
        ok = {"stage1": s1, "stage2": {"kind": "multi", "within_tol": True, "sigma_f_ok": True,
                                         "fits_bus": True, "robustness": {"R": 0.1}}}
        self.assertEqual(study_summary(ok), (True, 0.1))
        ok["stage2"]["fits_bus"] = False
        self.assertEqual(study_summary(ok), (False, 0.1))
        legacy = {"stage1": s1, "stage2": {"kind": "single", "within_tol": True, "sigma_f_ok": True}}
        self.assertTrue(study_summary(legacy)[0])                     # старые снапшоты без шины
        failed = {"stage1": s1, "stage2": {"kind": "multistart_failed"}}
        self.assertEqual(study_summary(failed), (True, 0.5))          # реализуемый дизайн — кривая


def _form_data(**overrides) -> dict:
    data = {"name": "space_study", "target_x_max": "0.9", "target_T": "1.6", "target_v_end": "0.5",
            "sigma_f_max": "2000", "rel_tol": "0.05", "n_brakes": "2", "do_parametric": "on",
            "gamma": "17700000", "bus_length": ""}
    for p in CONT_PARAMS:
        lo, hi = DEFAULT_BOUNDS[p]
        data.update({f"{p}_mode": "free", f"{p}_min": str(lo), f"{p}_max": str(hi), f"{p}_value": ""})
    data.update({"n_mode": "free", "n_min": "8", "n_max": "24", "n_step": "2", "n_value": "16"})
    data.update(overrides)
    return data


class DesignFormTests(TestCase):

    def setUp(self):
        self.donor = CalculationRun.objects.create(name="donor_run", mass=100.0,
                                                   input_file="uploads/drive.xlsx")

    def _form(self, **overrides):
        return DesignStudyForm(_form_data(source_run=str(self.donor.pk), **overrides))

    def test_valid_builds_space(self):
        form = self._form(bz_mode="fixed", bz_value="1.2", bus_length="1.5")
        self.assertTrue(form.is_valid(), form.errors)
        space = ParamSpace.from_dict(form.cleaned_data["param_space"])
        self.assertEqual(space.fixed["bz"], 1.2)
        self.assertNotIn("bz", space.free_params)
        self.assertEqual(space.n_choices, n_choices_range(8, 24, 2))
        self.assertEqual(form.cleaned_data["bus_length"], 1.5)

    def test_inactive_field_errors_ignored(self):
        form = self._form(bz_value="abc")             # bz подбирается — «значение» не используется
        self.assertTrue(form.is_valid(), form.errors)

    def test_min_not_less_than_max(self):
        form = self._form(xm_min="0.03", xm_max="0.02")
        self.assertFalse(form.is_valid())
        self.assertIn("xm_max", form.errors)

    def test_sign_rules(self):
        self.assertTrue(self._form(dh1_mode="fixed", dh1_value="0").is_valid())
        form = self._form(delta_mode="fixed", delta_value="0")
        self.assertFalse(form.is_valid())
        self.assertIn("delta_value", form.errors)

    def test_everything_fixed(self):
        overrides = {f"{p}_mode": "fixed" for p in CONT_PARAMS}
        overrides.update({f"{p}_value": str(DEFAULT_BOUNDS[p][0]) for p in CONT_PARAMS})
        form = self._form(n_mode="fixed", n_value="12", **overrides)
        self.assertFalse(form.is_valid())
        self.assertIn("подбирать нечего", " ".join(form.non_field_errors()))
        # Только N подбирается — уже есть что подбирать.
        self.assertTrue(self._form(**overrides).is_valid())

    def test_too_many_n_variants(self):
        form = self._form(n_min="1", n_max="40", n_step="1")
        self.assertFalse(form.is_valid())
        self.assertIn("n_step", form.errors)

    def test_bus_shorter_than_shortest_system(self):
        # Наименьшая система: 8·0.012 + 7·0.006 = 0.138 м.
        form = self._form(bus_length="0.13")
        self.assertFalse(form.is_valid())
        self.assertIn("bus_length", form.errors)
        self.assertTrue(self._form(bus_length="0.2").is_valid())


class DesignViewsTests(TestCase):

    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("space_owner", "o@example.com", "pw")
        self.other = users.create_user("space_other", "x@example.com", "pw")
        self.donor = CalculationRun.objects.create(name="donor_views", mass=100.0, owner=self.owner,
                                                   input_file="uploads/drive.xlsx")
        for i in (1, 2):
            MagneticBrakeConfig.objects.create(
                run=self.donor, index=i, model_type=MagneticBrakeConfig.MODEL_TYPE_PARAMETRIC,
                gamma=1.77e7, delta=0.005 + 0.001 * i, xm=0.022, ym=0.55, dh1=0.02, dh2=0.02,
                dm=0.014, n=16, mu=1.0, bz=0.83, lya=2.5, wn0=1.0)
        self.client.force_login(self.owner)

    def test_donor_brakes_json(self):
        response = self.client.get(reverse("optimize_donor_brakes", args=[self.donor.pk]))
        self.assertEqual(response.status_code, 200)
        brakes = response.json()["brakes"]
        self.assertEqual([b["index"] for b in brakes], [1, 2])
        self.assertAlmostEqual(brakes[1]["values"]["delta"], 0.007)
        self.assertEqual(brakes[0]["values"]["n"], 16)

        self.client.force_login(self.other)       # чужой расчёт инженеру не виден
        response = self.client.get(reverse("optimize_donor_brakes", args=[self.donor.pk]))
        self.assertEqual(response.status_code, 404)

    def test_new_saves_space_and_bus(self):
        data = _form_data(source_run=str(self.donor.pk), name="space_new", ym_mode="fixed",
                          ym_value="0.5", bus_length="1.4")
        with mock.patch("recoil_app.views.optimize.start_study") as start:
            response = self.client.post(reverse("optimize_new"), data)
        study = DesignStudy.objects.get(name="space_new")
        self.assertRedirects(response, reverse("optimize_detail", args=[study.pk]),
                             fetch_redirect_response=False)
        start.assert_called_once_with(study.pk)
        self.assertEqual(study.bus_length, 1.4)
        self.assertEqual(ParamSpace.from_dict(study.param_space).fixed["ym"], 0.5)

    def test_form_page_renders_space_table(self):
        response = self.client.get(reverse("optimize_new"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Границы подбора")
        self.assertContains(response, 'name="bz_mode"')
        self.assertContains(response, 'name="n_step"')
        self.assertContains(response, "Подставить из расчёта-донора")

    def test_detail_shows_bounds_hits_and_bus(self):
        space = space_with_overrides(ParamSpace.default(), fixed={"bz": 0.83})
        params = {"gamma": 1.77e7, "delta": 0.008, "xm": 0.02, "ym": 0.5, "dh1": 0.02, "dh2": 0.02,
                  "dm": 0.01, "n": 12, "mu": 1.0, "bz": 0.83, "lya": 2.5, "wn0": 1.0}
        metrics = {"x_max": 0.8, "T": 1.5, "v_end": 0.3, "sigma_f_peak": 1900.0, "completed": True}
        snapshot = {
            "stage1": {"feasible": True, "achieved": metrics, "rel_error": {},
                       "curve": {"v_nodes": [0.0, 5.0, 10.0], "f_nodes": [0.0, 1500.0, 2000.0]},
                       "envelope": {"no_brake": metrics, "full_brake": metrics}, "messages": [],
                       "robustness": None},
            "stage2": {"kind": "single", "n_brakes": 1, "params": [params], "weights": [1.0],
                       "achieved": metrics, "rel_error": {}, "within_tol": True,
                       "sigma_f_peak": 1900.0, "sigma_f_ok": True, "robustness": None,
                       "messages": ["Подбор упёрся в границу диапазона (δ — у максимума)."],
                       "bus": {"bus_length": 1.0, "stroke": 0.8, "system_lengths": [0.35],
                               "required": 1.15, "margin": -0.15, "overshoot": 0.15, "fits": False},
                       "fits_bus": False},
            "design": {"type": "curve", "curve": {"v_nodes": [0.0, 5.0, 10.0],
                                                  "f_nodes": [0.0, 1500.0, 2000.0]}},
            "space": space.to_dict(), "bus_length": 1.0,
        }
        study = DesignStudy.objects.create(
            name="space_detail", source_run=self.donor, owner=self.owner, target_T=1.6,
            target_x_max=0.9, target_v_end=0.5, sigma_f_max=2000.0, bus_length=1.0,
            status=DesignStudy.STATUS_DONE, result_snapshot=snapshot, feasible=False)
        response = self.client.get(reverse("optimize_detail", args=[study.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "у максимума")
        self.assertContains(response, "длиннее")
        self.assertContains(response, "Длина шины")
        self.assertContains(response, "задан")                     # bz зафиксирован
        self.assertContains(response, "δ — у максимума")           # сообщения Stage 2 выводятся
        delta_row = next(r for r in response.context["brake_rows"] if r["field"] == "delta")
        self.assertTrue(math.isclose(delta_row["cells"][0]["value"], 0.008))
        self.assertEqual(len(response.context["brake_columns"]), 1)

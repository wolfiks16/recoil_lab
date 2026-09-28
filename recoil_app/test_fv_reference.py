"""График «Сила торможения от скорости»: расчёт + характеристика тормозов (модель) + проверка расхождения."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from django.test import SimpleTestCase

from .services.charting import save_interactive_charts
from .services.dynamics import simulate_recoil_core
from .services.fv_reference import build_fv_reference, configs_from_stage_overlay
from .services.iterative.overlay import build_stage_overlay
from .services.magnetic import CurveBrakeParams, ForceCurvePoint, magnetic_force_quasistatic
from .test_iterative import B1, B2, DRIVE, RECOIL
from .test_iterative_result import _staged_outcome


class FvReferenceTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain = simulate_recoil_core(*DRIVE, RECOIL, [B1, B2])

    def test_calculation_matches_characteristic(self):
        ref = build_fv_reference(self.plain, [[B1, B2]])
        self.assertEqual(len(ref["curves"]), 1)
        # Характеристика — на сетке (1500 точек), в точках расчёта — интерполяция:
        # погрешность ~1e-5, на три порядка ниже порога пометки (1 %).
        self.assertLess(ref["deviation"]["max_rel"], 1e-4)
        self.assertEqual(ref["deviation"]["rows"], [])
        self.assertAlmostEqual(ref["curves"][0]["v"][-1], 1.05 * float(np.max(np.abs(self.plain.v))))

    def test_staged_run_matches_each_stage_characteristic(self):
        outcome = _staged_outcome()
        overlay = build_stage_overlay(outcome)
        ref = build_fv_reference(outcome.result, configs_from_stage_overlay(overlay), overlay["stage_index"])
        self.assertEqual([c["stage"] for c in ref["curves"]], [0, 1, 2])
        self.assertLess(ref["deviation"]["max_rel"], 1e-4)

    def test_curve_brake_not_extrapolated(self):
        short = CurveBrakeParams(points=(ForceCurvePoint(0.0, 0.0), ForceCurvePoint(5.0, 40e3)))
        ref = build_fv_reference(self.plain, [[short]])
        self.assertLessEqual(ref["curves"][0]["v"][-1], 5.0)
        self.assertIn(5.0, ref["curves"][0]["v"])       # узел таблицы — в сетке (излом не сглажен)

    def test_deviation_detected(self):
        v = np.linspace(0.5, 12.0, 200)
        model = np.array([magnetic_force_quasistatic(x, B1) for x in v])
        fake = SimpleNamespace(v=v, f_magnetic=-model * 1.05)       # расчёт на 5 % выше характеристики
        ref = build_fv_reference(fake, [[B1]])
        self.assertAlmostEqual(ref["deviation"]["max_rel"], 0.05, places=3)
        self.assertGreater(len(ref["deviation"]["rows"]), 0)

    def test_chart_combines_calculation_and_characteristic(self):
        ref = build_fv_reference(self.plain, [[B1, B2]])
        with tempfile.TemporaryDirectory() as tmp:
            files = save_interactive_charts(self.plain, tmp, prefix="fv", fv_reference=ref)
            html = Path(files["chart_fmag_v"]).read_text(encoding="utf-8")
        self.assertIn("Сила торможения от скорости", html)
        self.assertIn("характеристика Σ (модель)", html)
        self.assertIn("Σ тормозов", html)
        self.assertIn("тормоз 2", html)
        self.assertNotIn("⚠", html)

        deviating = {**ref, "deviation": {"max_rel": 0.2, "rows": [100, 200]}}
        with tempfile.TemporaryDirectory() as tmp:
            files = save_interactive_charts(self.plain, tmp, prefix="fv", fv_reference=deviating)
            html = Path(files["chart_fmag_v"]).read_text(encoding="utf-8")
        self.assertIn("⚠ расчёт отходит от характеристики до 20.0 %", html)

    def test_chart_without_reference_still_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = save_interactive_charts(self.plain, tmp, prefix="fv")
            self.assertIn("Сила торможения от скорости", Path(files["chart_fmag_v"]).read_text(encoding="utf-8"))

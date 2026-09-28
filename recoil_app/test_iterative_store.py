"""Тесты хранения итерационного расчёта (`services/iterative/store.py`, модель `IterativeCalc`).

Каждое действие идёт через перечитанную из БД запись — как отдельный HTTP-запрос.
Проверяется: состояние между запросами не искажается (итог = обычный расчёт
бит-в-бит), оптимистичная блокировка версий, сохранение итога с этапами,
удаление файлов. MEDIA_ROOT — временная папка.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import openpyxl
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from .models import BrakeStage, CalculationRun, IterativeCalc
from .services.dynamics import RecoilParams, simulate_recoil_core
from .services.io_utils import load_recoil_characteristics
from .services.iterative import MODE_FREE_FALL, MODE_RECOIL, TERMINATION_STOPPED
from .services.iterative import store
from .services.magnetic import CurveBrakeParams, ForceCurvePoint, MagneticParams

B1 = MagneticParams(gamma=1.77e7, delta=0.005, xm=0.022, ym=0.3, dh1=0.02, dh2=0.02,
                    dm=0.014, n=16, mu=1.0, bz=0.83, lya=2.5, wn0=1.0)
B2 = MagneticParams(gamma=1.77e7, delta=0.003, xm=0.021, ym=0.3, dh1=0.02, dh2=0.02,
                    dm=0.017, n=16, mu=1.0, bz=1.61, lya=2.5, wn0=1.0)
CURVE = CurveBrakeParams(points=tuple(
    ForceCurvePoint(velocity=v, force=f)
    for v, f in [(0.0, 0.0), (2.0, 20e3), (6.0, 55e3), (12.0, 90e3), (20.0, 110e3)]
))
RECOIL = RecoilParams(mass=2800.0, angle_deg=0.0, t_max=2.0, dt=4e-4)


def _drive_xlsx() -> ContentFile:
    """Входной Excel в формате `load_recoil_characteristics` (кН)."""
    wb = openpyxl.Workbook()
    ws_t = wb.active
    ws_t.title = "сила от времени"
    ws_t.append([None, "t, с", "F, кН"])
    for t, f in [(0.0, 0.0), (0.002, 3000.0), (0.005, 4000.0), (0.010, 2000.0), (0.015, 0.0)]:
        ws_t.append([None, t, f])
    ws_x = wb.create_sheet("сила от перемещения")
    ws_x.append([None, None, None, "X,м", "F, кН"])
    for x, f in [(0.0, 20.0), (1.5, 95.0)]:
        ws_x.append([None, None, None, x, f])
    buffer = io.BytesIO()
    wb.save(buffer)
    return ContentFile(buffer.getvalue(), name="drive.xlsx")


class IterativeStoreTests(TestCase):

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="iter_media_")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        # id записей после отката тестовой транзакции переиспользуются — чистим media.
        for child in Path(self._media).iterdir():
            shutil.rmtree(child, ignore_errors=True)

    # --- helpers ---

    def _create(self, name="it_calc", config=(B1, B2)) -> IterativeCalc:
        return store.create_calc(
            name=name, mode=MODE_RECOIL, recoil=RECOIL, config=list(config),
            input_file=_drive_xlsx(),
        )

    @staticmethod
    def _fresh(calc: IterativeCalc) -> IterativeCalc:
        return IterativeCalc.objects.get(pk=calc.pk)

    def _folder(self, calc: IterativeCalc) -> Path:
        return Path(self._media) / f"iterative/calc_{calc.pk}"

    # --- tests ---

    def test_create_initial_state(self):
        calc = self._create()
        self.assertEqual(calc.version, 1)
        self.assertTrue(calc.is_active)
        self.assertTrue(Path(calc.history_file.path).exists())
        self.assertTrue(Path(calc.input_file.path).exists())
        self.assertEqual(store.load_session(self._fresh(calc)).row_count, 1)

    def test_requests_chain_matches_plain_run_bitwise(self):
        calc = self._create()
        for n in (1, 50, 700):
            store.step(self._fresh(calc), n)
        run = store.finish(self._fresh(calc))

        core = simulate_recoil_core(*load_recoil_characteristics(calc.input_file.path), RECOIL, [B1, B2])
        timeline = run.snapshot.result_snapshot["timeline"]
        for key in ("t", "x", "v", "a"):
            self.assertTrue(np.array_equal(np.asarray(timeline[key]), getattr(core, key)), key)
        self.assertEqual(run.termination_reason, "returned_to_zero")
        self.assertTrue(run.is_iterative)
        self.assertEqual(run.brakes.count(), 2)
        self.assertEqual(BrakeStage.objects.filter(run=run).count(), 1)

        calc = self._fresh(calc)
        self.assertEqual(calc.status, IterativeCalc.STATUS_FINISHED)
        self.assertEqual(calc.result_run_id, run.pk)
        histories = list(self._folder(calc).glob("history_v*.npz"))
        self.assertEqual([p.name for p in histories], [Path(calc.history_file.name).name])

    def test_stale_version_rejected(self):
        calc = self._create()
        first, second = self._fresh(calc), self._fresh(calc)
        store.step(first, 5)
        with self.assertRaises(store.StaleCalcError):
            store.step(second, 5)
        calc = self._fresh(calc)
        self.assertEqual(calc.version, 2)
        self.assertEqual(store.load_session(calc).row_count, 6)
        self.assertEqual(len(list(self._folder(calc).glob("history_v*.npz"))), 1)

    def test_finish_persists_stages(self):
        calc = self._create()
        weaker = replace(B1, bz=B1.bz * 0.7)
        store.advance_distance(self._fresh(calc), 0.25)
        store.reconfigure(self._fresh(calc), [weaker, B2])
        store.advance_distance(self._fresh(calc), 0.25)
        store.reconfigure(self._fresh(calc), [weaker, None, CURVE])
        run = store.finish(self._fresh(calc))

        brakes = list(run.brakes.order_by("index"))
        self.assertEqual([b.index for b in brakes], [1, 2, 3])
        self.assertEqual(brakes[0].bz, B1.bz)                     # C₀, не ослабленный
        self.assertEqual(brakes[2].model_type, "curve")
        self.assertIn("этапа 2", brakes[2].name)
        self.assertEqual(brakes[2].force_points.count(), 5)

        stages = list(run.brake_stages.order_by("stage"))
        self.assertEqual([s.stage for s in stages], [0, 1, 2])
        self.assertIsNone(stages[0].x_switch)
        self.assertAlmostEqual(stages[1].x_switch, 0.25, delta=1e-9)
        self.assertAlmostEqual(stages[2].x_switch, 0.50, delta=1e-9)
        self.assertIsNotNone(stages[1].t_return)
        self.assertIsNone(stages[2].config[1])                    # тормоз 2 отключён на этапе 2
        self.assertEqual(stages[2].config[2]["type"], "curve")

        snap = run.snapshot
        self.assertEqual(len(snap.input_snapshot["iterative"]["stages"]), 3)
        stage_index = snap.result_snapshot["iterative"]["stage_index"]
        self.assertEqual(len(stage_index), len(snap.result_snapshot["timeline"]["t"]))
        self.assertEqual(len(snap.result_snapshot["iterative"]["switch_events"]), 4)
        self.assertEqual(np.asarray(snap.result_snapshot["forces"]["magnetic_each"]).shape[1], 3)

    def test_stop_now_free_fall(self):
        recoil = RecoilParams(mass=5.0, angle_deg=90.0, t_max=1.0, dt=1e-3)
        calc = store.create_calc(name="it_ff", mode=MODE_FREE_FALL, recoil=recoil, config=[B2])
        self.assertFalse(calc.input_file)
        store.step(self._fresh(calc), 100)
        run = store.finish(self._fresh(calc), stop_now=True)
        self.assertEqual(run.termination_reason, TERMINATION_STOPPED)
        self.assertEqual(run.mode, CalculationRun.MODE_FREE_FALL)
        self.assertEqual(len(run.snapshot.result_snapshot["timeline"]["t"]), 101)

    def test_actions_after_finish_rejected(self):
        calc = self._create()
        store.finish(self._fresh(calc), stop_now=True)
        with self.assertRaises(ValueError):
            store.step(self._fresh(calc), 1)
        with self.assertRaises(ValueError):
            store.finish(self._fresh(calc))

    def test_name_validation(self):
        CalculationRun.objects.create(name="taken", mass=1.0)
        with self.assertRaises(ValueError):
            self._create(name="taken")
        with self.assertRaises(ValueError):
            self._create(name="имя с пробелом")
        self._create(name="free_name")
        with self.assertRaises(ValueError):
            self._create(name="free_name")

    def test_finish_name_conflict_and_override(self):
        calc = self._create(name="clash")
        CalculationRun.objects.create(name="clash", mass=1.0)
        with self.assertRaises(ValueError):
            store.finish(self._fresh(calc), stop_now=True)
        self.assertTrue(self._fresh(calc).is_active)          # ничего не испорчено
        run = store.finish(self._fresh(calc), stop_now=True, name="clash_2")
        self.assertEqual(run.name, "clash_2")

    def test_delete_removes_media_but_keeps_result(self):
        calc = self._create()
        run = store.finish(self._fresh(calc), stop_now=True)
        folder = self._folder(calc)
        self.assertTrue(folder.exists())
        store.delete_calc(self._fresh(calc))
        self.assertFalse(folder.exists())
        self.assertTrue(CalculationRun.objects.filter(pk=run.pk).exists())
        self.assertTrue(Path(run.input_file.path).exists())

    def test_existing_pages_render_for_iterative_run(self):
        """Итог с этапами (3 тормоза, узлы-дубли) — страница результата, тепло, сравнение."""
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        user = get_user_model().objects.create_superuser("iter_admin", "a@example.com", "pw")
        self.client.force_login(user)

        calc = store.create_calc(name="it_pages", mode=MODE_RECOIL, recoil=RECOIL,
                                 config=[B1, B2], input_file=_drive_xlsx(), owner=user)
        store.advance_distance(self._fresh(calc), 0.3)
        store.reconfigure(self._fresh(calc), [replace(B1, bz=0.6), None, CURVE])
        staged = store.finish(self._fresh(calc))
        other = store.finish(
            store.create_calc(name="it_pages_b", mode=MODE_RECOIL, recoil=RECOIL,
                              config=[B1, B2], input_file=_drive_xlsx(), owner=user),
            stop_now=True,
        )

        for url in (
            reverse("run_detail_v2", args=[staged.pk]),
            reverse("thermal_new", args=[staged.pk]),
            reverse("compare") + f"?run_a={staged.pk}&run_b={other.pk}",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_invalid_drive_leaves_nothing(self):
        bad = ContentFile(b"not an excel file", name="bad.xlsx")
        with self.assertRaises(Exception):
            store.create_calc(name="bad_drive", mode=MODE_RECOIL, recoil=RECOIL,
                              config=[B1], input_file=bad)
        self.assertFalse(IterativeCalc.objects.filter(name="bad_drive").exists())
        self.assertEqual(list((Path(self._media) / "iterative").glob("calc_*")), [])

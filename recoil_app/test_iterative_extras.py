"""Срез 5: отмена последнего изменения, клонирование, фоновый «Досчитать до конца»."""

from __future__ import annotations

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CalculationRun, IterativeCalc
from .services.iterative import MODE_RECOIL
from .services.iterative import store
from .test_iterative_store import B1, B2, RECOIL, _drive_xlsx
from .test_iterative_views import _param_slot, _slots_data


def _sync_worker(calc_id, version, run_name):
    """Фоновый поток в тестах — синхронно и без закрытия соединения тестовой транзакции."""
    store._finish_worker(calc_id, version, run_name, close_connection=False)


class IterativeExtrasTests(TestCase):

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="iter_extras_media_")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        for child in Path(self._media).iterdir():
            shutil.rmtree(child, ignore_errors=True)
        self.user = get_user_model().objects.create_user("extras_owner", "e@example.com", "pw")
        self.client.force_login(self.user)
        self.calc = store.create_calc(name="it_extras", mode=MODE_RECOIL, recoil=RECOIL,
                                      config=[B1, B2], owner=self.user, input_file=_drive_xlsx())

    def _fresh(self, calc=None) -> IterativeCalc:
        return IterativeCalc.objects.get(pk=(calc or self.calc).pk)

    def _action(self, calc=None, **data):
        return self.client.post(reverse("iterative_action", args=[(calc or self.calc).pk]), data)

    def _staged(self):
        self._action(action="distance", dx="0.25")
        self._action(action="configure", **_slots_data([_param_slot(B1, bz=0.6), _param_slot(B2)], initial=2))
        self._action(action="steps", n="50")

    # --- отмена ---

    def test_undo_action(self):
        self._staged()
        data = self._action(action="undo").json()
        self.assertTrue(data["ok"], data)
        self.assertIn("отменено", data["message"])
        self.assertFalse(data["flags"]["can_undo"])
        session = store.load_session(self._fresh())
        self.assertEqual(len(session.stages), 1)
        self.assertAlmostEqual(session.x, 0.25, delta=1e-9)

        again = self._action(action="undo")
        self.assertEqual(again.status_code, 400)

    # --- клонирование ---

    def test_clone_copies_state_and_keeps_original(self):
        self._staged()
        source = self._fresh()
        response = self.client.post(reverse("iterative_clone", args=[source.pk]), {"name": "it_extras_clone"})
        clone = IterativeCalc.objects.get(name="it_extras_clone")
        self.assertRedirects(response, reverse("iterative_detail", args=[clone.pk]))
        self.assertEqual(clone.owner, self.user)

        original_session = store.load_session(source)
        clone_session = store.load_session(clone)
        self.assertEqual(clone_session.x, original_session.x)
        self.assertEqual(len(clone_session.stages), 2)
        self.assertTrue(Path(clone.input_file.path).exists())
        self.assertNotEqual(clone.input_file.path, source.input_file.path)

        self._action(clone, action="undo")                   # правка клона …
        self.assertEqual(len(store.load_session(self._fresh(source)).stages), 2)   # … оригинал цел
        self.assertEqual(self._fresh(source).version, source.version)

    def test_clone_of_stopped_session_continues(self):
        self._action(action="steps", n="100")
        self._action(action="stop", result_name="it_extras_stopped")
        self.assertFalse(self._fresh().is_active)

        self.client.post(reverse("iterative_clone", args=[self.calc.pk]), {"name": "it_extras_resumed"})
        clone = IterativeCalc.objects.get(name="it_extras_resumed")
        self.assertTrue(clone.is_active)
        self.assertFalse(store.load_session(clone).finished)
        data = self._action(clone, action="step").json()
        self.assertTrue(data["ok"], data)

    def test_clone_name_validation(self):
        response = self.client.post(reverse("iterative_clone", args=[self.calc.pk]), {"name": "it_extras"})
        self.assertRedirects(response, reverse("iterative_detail", args=[self.calc.pk]))
        self.assertEqual(IterativeCalc.objects.count(), 1)

    # --- фоновое завершение ---

    def test_long_finish_goes_background_then_redirects(self):
        with mock.patch.object(store, "BACKGROUND_FINISH_STEPS", 100), \
                mock.patch.object(store, "_spawn_worker", _sync_worker):
            data = self._action(action="to_end", result_name="it_extras_bg").json()
        self.assertTrue(data["background"])
        status = self.client.get(data["status_url"]).json()
        run = CalculationRun.objects.get(name="it_extras_bg")
        self.assertEqual(status["status"], IterativeCalc.STATUS_FINISHED)
        self.assertEqual(status["redirect"], reverse("run_detail_v2", args=[run.pk]))
        self.assertEqual(run.termination_reason, "returned_to_zero")

    def test_short_finish_stays_synchronous(self):
        data = self._action(action="to_end", result_name="it_extras_sync").json()
        self.assertIn("redirect", data)
        self.assertNotIn("background", data)

    def test_background_error_returns_session_to_active(self):
        with mock.patch.object(store, "BACKGROUND_FINISH_STEPS", 100), \
                mock.patch.object(store, "_spawn_worker", _sync_worker), \
                mock.patch.object(store, "_finish_session", side_effect=RuntimeError("диск переполнен")):
            self._action(action="to_end", result_name="it_extras_err")
        calc = self._fresh()
        self.assertTrue(calc.is_active)
        self.assertIn("диск переполнен", calc.error_text)
        page = self.client.get(reverse("iterative_detail", args=[calc.pk]))
        self.assertContains(page, "Фоновый досчёт не удался")
        self.assertEqual(self._action(action="step").status_code, 200)   # сессия цела, можно продолжать

    def test_actions_rejected_while_finishing_and_reset(self):
        IterativeCalc.objects.filter(pk=self.calc.pk).update(status=IterativeCalc.STATUS_FINISHING,
                                                             updated_at=timezone.now())
        response = self._action(action="step")
        self.assertEqual(response.status_code, 400)
        self.assertIn("фоновый досчёт", response.json()["error"])
        page = self.client.get(reverse("iterative_detail", args=[self.calc.pk]))
        self.assertContains(page, "Досчитываю до конца в фоне")

        self.client.post(reverse("iterative_reset", args=[self.calc.pk]))   # ещё рано
        self.assertTrue(self._fresh().is_finishing)

        IterativeCalc.objects.filter(pk=self.calc.pk).update(
            updated_at=timezone.now() - timedelta(minutes=11))
        self.client.post(reverse("iterative_reset", args=[self.calc.pk]))
        calc = self._fresh()
        self.assertTrue(calc.is_active)
        self.assertIn("прерван", calc.error_text)

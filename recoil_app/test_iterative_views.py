"""Тесты страниц итерационного расчёта (`views/iterative.py`): список, старт, AJAX-действия, права."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CalculationRun, IterativeCalc, UserProfile
from .services.iterative import MODE_FREE_FALL, MODE_RECOIL
from .services.iterative import store
from .test_iterative_store import B1, B2, RECOIL, _drive_xlsx

PARAMS = ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")


def _slots_data(slots: list[dict], initial: int = 0) -> dict:
    """POST-данные formset'а `slots`: [{"kind": ..., <параметры>...}, ...]."""
    data = {
        "slots-TOTAL_FORMS": str(len(slots)),
        "slots-INITIAL_FORMS": str(initial),
        "slots-MIN_NUM_FORMS": "1",
        "slots-MAX_NUM_FORMS": "1000",
    }
    for i, slot in enumerate(slots):
        for key, value in slot.items():
            data[f"slots-{i}-{key}"] = "" if value is None else str(value)
    return data


def _param_slot(params, **overrides) -> dict:
    values = {k: v for k, v in asdict(params).items() if k in PARAMS}
    values.update(overrides)
    return {"kind": "parametric", **values}


class IterativeViewsTests(TestCase):

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="iter_views_media_")
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
        users = get_user_model().objects
        self.owner = users.create_user("iter_owner", "o@example.com", "pw")
        self.other = users.create_user("iter_other", "x@example.com", "pw")
        self.analyst = users.create_user("iter_analyst", "a@example.com", "pw")
        UserProfile.objects.filter(user=self.analyst).update(role=UserProfile.ROLE_ANALYST)
        self.client.force_login(self.owner)

    def _calc(self, name="it_view") -> IterativeCalc:
        return store.create_calc(name=name, mode=MODE_RECOIL, recoil=RECOIL, config=[B1, B2],
                                 owner=self.owner, input_file=_drive_xlsx())

    def _action(self, calc, **data):
        return self.client.post(reverse("iterative_action", args=[calc.pk]), data)

    # --- список / старт ---

    def test_list_renders_own_sessions(self):
        calc = self._calc()
        response = self.client.get(reverse("iterative_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, calc.name)

    def test_new_post_recoil_creates_session(self):
        data = {
            "name": "it_new", "mode": MODE_RECOIL, "mass": "2800", "angle_deg": "0",
            "v0": "0", "x0": "0", "t_max": "2", "dt": "0.0004",
            **_slots_data([_param_slot(B1), _param_slot(B2)]),
        }
        data["input_file"] = _drive_xlsx()
        response = self.client.post(reverse("iterative_new"), data)
        calc = IterativeCalc.objects.get(name="it_new")
        self.assertRedirects(response, reverse("iterative_detail", args=[calc.pk]))
        self.assertEqual(calc.owner, self.owner)
        self.assertEqual(len(calc.state["stages"][0]["config"]), 2)

        page = self.client.get(reverse("iterative_detail", args=[calc.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="it-charts"')
        self.assertContains(page, "Изменить конфигурацию")

    def test_new_post_recoil_without_file_rejected(self):
        data = {
            "name": "it_nofile", "mode": MODE_RECOIL, "mass": "2800", "angle_deg": "0",
            "v0": "0", "x0": "0", "t_max": "2", "dt": "0.0004",
            **_slots_data([_param_slot(B1)]),
        }
        response = self.client.post(reverse("iterative_new"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(IterativeCalc.objects.filter(name="it_nofile").exists())
        self.assertContains(response, "загрузите файл")

    def test_new_post_free_fall_without_file(self):
        data = {
            "name": "it_ff", "mode": MODE_FREE_FALL, "mass": "5", "angle_deg": "90",
            "v0": "0", "x0": "0", "t_max": "30", "dt": "0.001",
            **_slots_data([_param_slot(B2), {"kind": "off"}]),
        }
        response = self.client.post(reverse("iterative_new"), data)
        calc = IterativeCalc.objects.get(name="it_ff")
        self.assertRedirects(response, reverse("iterative_detail", args=[calc.pk]))
        self.assertIsNone(calc.state["stages"][0]["config"][1])

    def test_new_prefill_from_run(self):
        calc = self._calc(name="it_donor")
        run = store.finish(calc, stop_now=True)
        response = self.client.get(reverse("iterative_new") + f"?from_run={run.pk}")
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["name"], "it_donor_1")
        self.assertEqual(form.initial["source_run_id"], run.pk)
        self.assertEqual(len(response.context["slot_formset"].forms), 2)

        # Старт без нового файла — берётся файл донора.
        data = {
            "name": "it_from_donor", "mode": MODE_RECOIL, "source_run_id": str(run.pk),
            "mass": "2800", "angle_deg": "0", "v0": "0", "x0": "0", "t_max": "2", "dt": "0.0004",
            **_slots_data([_param_slot(B1), _param_slot(B2)]),
        }
        self.client.post(reverse("iterative_new"), data)
        created = IterativeCalc.objects.get(name="it_from_donor")
        self.assertEqual(created.source_run, run)
        self.assertTrue(Path(created.input_file.path).exists())

    # --- действия ---

    def test_step_steps_distance(self):
        calc = self._calc()
        data = self._action(calc, action="step").json()
        self.assertTrue(data["ok"])
        self.assertIn("state", data["html"])
        self.assertEqual(set(data["charts"]), {"x_t", "v_t", "f_t", "v_x"})

        self._action(calc, action="steps", n="99")
        data = self._action(calc, action="distance", dx="0.2").json()
        self.assertTrue(data["ok"], data)
        self.assertIn("Точка достигнута", data["message"])
        session = store.load_session(IterativeCalc.objects.get(pk=calc.pk))
        self.assertGreater(session.x, 0.2 - 1e-9)
        self.assertEqual(IterativeCalc.objects.get(pk=calc.pk).version, 4)   # создание + 3 действия

    def test_bad_inputs_return_400(self):
        calc = self._calc()
        self.assertEqual(self._action(calc, action="steps", n="abc").status_code, 400)
        self.assertEqual(self._action(calc, action="distance", dx="-1").status_code, 400)
        self.assertEqual(self._action(calc, action="nope").status_code, 400)

    def test_configure_changes_stage_and_rejects_invalid(self):
        calc = self._calc()
        self._action(calc, action="distance", dx="0.25")
        data = self._action(calc, action="configure",
                            **_slots_data([_param_slot(B1, bz=0.5), _param_slot(B2)], initial=2)).json()
        self.assertTrue(data["ok"], data)
        self.assertIn("этап 1", data["message"])
        self.assertIn("bz 0.83→0.5", data["html"]["stages"])
        self.assertIn("editor", data["html"])

        bad = self._action(calc, action="configure",
                           **_slots_data([{"kind": "parametric", "gamma": "1"}, _param_slot(B2)], initial=2))
        self.assertEqual(bad.status_code, 400)
        self.assertIn("коэффициенты", bad.json()["error"])

        removed = self._action(calc, action="configure",
                               **_slots_data([_param_slot(B1), {**_param_slot(B2), "DELETE": "on"}], initial=2))
        self.assertEqual(removed.status_code, 400)

    def test_configure_forbidden_on_return(self):
        calc = self._calc()
        self._action(calc, action="distance", dx="50")      # до разворота
        response = self._action(calc, action="configure",
                                **_slots_data([_param_slot(B1, bz=0.5), _param_slot(B2)], initial=2))
        self.assertEqual(response.status_code, 400)
        self.assertIn("накате", response.json()["error"])

    def test_finish_to_end_redirects_to_result(self):
        calc = self._calc()
        data = self._action(calc, action="to_end", result_name="it_view_result").json()
        run = CalculationRun.objects.get(name="it_view_result")
        self.assertEqual(data["redirect"], reverse("run_detail_v2", args=[run.pk]))
        self.assertTrue(run.is_iterative)
        calc.refresh_from_db()
        self.assertFalse(calc.is_active)

        page = self.client.get(reverse("iterative_detail", args=[calc.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Итоговый расчёт")
        self.assertNotContains(page, 'id="it-controls"')

    # --- права ---

    def test_permissions(self):
        calc = self._calc()
        detail = reverse("iterative_detail", args=[calc.pk])

        self.client.force_login(self.other)                  # чужой инженер
        self.assertEqual(self.client.get(detail).status_code, 403)
        self.assertEqual(self._action(calc, action="step").status_code, 403)
        self.assertNotContains(self.client.get(reverse("iterative_list")), calc.name)

        self.client.force_login(self.analyst)                # аналитик: смотрит, но не ведёт
        page = self.client.get(detail)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'id="it-controls"')
        self.assertEqual(self._action(calc, action="step").status_code, 403)

        self.client.logout()
        self.assertEqual(self.client.get(detail).status_code, 302)

    def test_delete(self):
        calc = self._calc()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("iterative_delete", args=[calc.pk])).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("iterative_delete", args=[calc.pk]))
        self.assertRedirects(response, reverse("iterative_list"))
        self.assertFalse(IterativeCalc.objects.filter(pk=calc.pk).exists())

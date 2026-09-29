"""Новый расчёт: «Скопировать» без повторной загрузки входного файла, права на донора, каталог."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BrakeCatalog, CalculationRun
from .test_iterative import B1
from .test_iterative_store import _drive_xlsx

PARAMS = {f: getattr(B1, f) for f in ("gamma", "delta", "xm", "ym", "dh1", "dh2", "dm", "n", "mu", "bz", "lya", "wn0")}


def _post_data(name: str, **extra) -> dict:
    data = {
        "name": name, "mass": "2800", "angle_deg": "0", "v0": "0", "x0": "0", "t_max": "0.2", "dt": "0.0004",
        "brakes-TOTAL_FORMS": "1", "brakes-INITIAL_FORMS": "0",
        "brakes-MIN_NUM_FORMS": "0", "brakes-MAX_NUM_FORMS": "1000",
        "brakes-0-model_type": "parametric", "brakes-0-name": "B1",
    }
    data.update({f"brakes-0-{k}": str(v) for k, v in PARAMS.items()})
    data.update(extra)
    return data


class CalcCopyTests(TestCase):

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="calc_copy_media_")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("copy_owner", "o@example.com", "pw")
        self.other = users.create_user("copy_other", "x@example.com", "pw")
        self.client.force_login(self.owner)
        data = _post_data("donor")
        data["input_file"] = _drive_xlsx()
        response = self.client.post(reverse("index"), data)
        self.donor = CalculationRun.objects.get(name="donor")
        self.assertRedirects(response, reverse("run_detail_v2", args=[self.donor.pk]))

    def test_copy_prefills_and_reuses_input_file(self):
        page = self.client.get(reverse("index") + f"?from_run={self.donor.pk}")
        self.assertContains(page, "donor_1")                      # свободное имя копии
        self.assertContains(page, f'name="source_run_id" value="{self.donor.pk}"')
        self.assertContains(page, "Можно не загружать")

        response = self.client.post(reverse("index"), _post_data("donor_1", source_run_id=str(self.donor.pk)))
        copy = CalculationRun.objects.get(name="donor_1")
        self.assertRedirects(response, reverse("run_detail_v2", args=[copy.pk]))
        self.assertNotEqual(copy.input_file.name, self.donor.input_file.name)   # своя копия файла
        self.assertEqual(Path(copy.input_file.path).read_bytes(), Path(self.donor.input_file.path).read_bytes())
        self.assertAlmostEqual(copy.x_max, self.donor.x_max)

    def test_cannot_copy_input_file_of_foreign_run(self):
        self.client.force_login(self.other)
        page = self.client.get(reverse("index") + f"?from_run={self.donor.pk}")
        self.assertNotContains(page, "donor_1")                   # чужой расчёт не подставляется
        response = self.client.post(reverse("index"), _post_data("stolen", source_run_id=str(self.donor.pk)))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CalculationRun.objects.filter(name="stolen").exists())
        self.assertContains(response, "Загрузите входной файл")

    def test_without_file_and_source_asks_for_file(self):
        response = self.client.post(reverse("index"), _post_data("no_file"))
        self.assertContains(response, "Загрузите входной файл")

    def test_catalog_prefill(self):
        entry = BrakeCatalog.objects.create(name="cat_b1", model_type="parametric", **PARAMS)
        page = self.client.get(reverse("index") + f"?catalog={entry.pk}")
        self.assertContains(page, "подставлен из каталога")
        self.assertContains(page, f'name="brakes-0-catalog_source_id" value="{entry.pk}"')


class FixedBrakeParamsTests(TestCase):
    """λa и w_n0 не показываются в редакторе тормоза, но передаются и по умолчанию равны 2.5 и 1.0."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="calc_fixed_media_")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user("fixed_owner", "f@example.com", "pw")
        self.client.force_login(self.user)

    def test_editor_hides_lya_and_wn0(self):
        page = self.client.get(reverse("index")).content.decode()
        self.assertIn('type="hidden" name="brakes-0-lya" value="2.5"', page)
        self.assertIn('type="hidden" name="brakes-0-wn0" value="1.0"', page)
        self.assertIn('type="hidden" name="brakes-__prefix__-lya"', page)   # шаблон «Добавить тормоз»
        self.assertNotIn("Параметр λa", page)
        self.assertNotIn("Начальное состояние wn", page)

    def test_missing_lya_and_wn0_default(self):
        data = _post_data("no_fixed")
        del data["brakes-0-lya"], data["brakes-0-wn0"]
        data["input_file"] = _drive_xlsx()
        response = self.client.post(reverse("index"), data)
        run = CalculationRun.objects.get(name="no_fixed")
        self.assertRedirects(response, reverse("run_detail_v2", args=[run.pk]))
        brake = run.brakes.get()
        self.assertEqual((brake.lya, brake.wn0), (2.5, 1.0))

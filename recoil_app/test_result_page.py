"""Сервис страницы результата: прореживание осциллограммы и форматирование протокола."""

import numpy as np
from django.test import SimpleTestCase

from .services.result_page import (
    DECIMATION_MIN_POINTS,
    decimate_indices,
    fmt_number,
    force_scale,
    stage_segments,
)


class DecimationTests(SimpleTestCase):
    def test_short_series_kept_whole(self):
        x = np.arange(100.0)
        self.assertEqual(len(decimate_indices([x], [])), 100)

    def test_extremes_and_required_points_survive(self):
        n = 50_000
        t = np.linspace(0.0, 1.0, n)
        x = np.sin(40 * t)
        x[12_345] = 7.0          # одиночный пик — не должен потеряться
        v = np.cos(40 * t)
        idx = decimate_indices([x, v], keep=[31_000, 31_001])
        self.assertLess(len(idx), DECIMATION_MIN_POINTS)
        self.assertIn(12_345, idx)
        self.assertIn(31_000, idx)
        self.assertIn(31_001, idx)
        self.assertEqual(idx[0], 0)
        self.assertEqual(idx[-1], n - 1)
        self.assertTrue(np.all(np.diff(idx) > 0))
        self.assertAlmostEqual(float(x[idx].max()), 7.0)
        self.assertAlmostEqual(float(v[idx].min()), float(v.min()))


class FormattingTests(SimpleTestCase):
    def test_fmt_number(self):
        self.assertEqual(fmt_number(1080.64, 1), "1 080.6")
        self.assertEqual(fmt_number(-0.00001, 3), "0.000")
        self.assertEqual(fmt_number(-2.5, 1), "−2.5")
        self.assertEqual(fmt_number(None, 2), "—")
        self.assertEqual(fmt_number(float("nan"), 2), "—")

    def test_force_scale(self):
        self.assertEqual(force_scale(250_000.0), (1000.0, "кН"))
        self.assertEqual(force_scale(0.4), (1.0, "Н"))

    def test_stage_segments(self):
        t = np.arange(6.0)
        stage = np.array([0, 0, 1, 1, 0, 0])
        self.assertEqual(stage_segments(t, stage), [
            {"t0": 0.0, "t1": 1.0, "stage": 0},
            {"t0": 2.0, "t1": 3.0, "stage": 1},
            {"t0": 4.0, "t1": 5.0, "stage": 0},
        ])

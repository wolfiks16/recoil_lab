"""Тесты движка итерационного расчёта (`services/iterative`).

Главная гарантия — пошаговый прогон продолжает ровно с сохранённого состояния,
поэтому без изменений конфигурации он совпадает с обычным расчётом бит-в-бит
(при любой нарезке на шаги и после сериализации). Остальное — логика этапов:
точная посадка узла, обратные переключения на накате, отключение/добавление
тормозов, смена типа, правило wn.

Привод синтетический (без Excel), тормоза — параметры реального расчёта.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace

import numpy as np
from django.test import SimpleTestCase

from .services.dynamics import RecoilParams, simulate_free_fall, simulate_recoil_core
from .services.interpolation import LinearTailPchip
from .services.iterative import (
    DIRECTION_FORWARD,
    DIRECTION_RETURN,
    MODE_FREE_FALL,
    MODE_RECOIL,
    STOP_FINISHED,
    STOP_STEPS,
    STOP_TARGET,
    STOP_TURNAROUND,
    TERMINATION_STOPPED,
    IterativeSession,
)
from .services.magnetic import (
    CurveBrakeParams,
    ForceCurvePoint,
    MagneticParams,
    wn_memory_coefficient,
)

DRIVE = (
    LinearTailPchip(np.array([0.0, 0.002, 0.005, 0.010, 0.015]),
                    np.array([0.0, 3.0e6, 4.0e6, 2.0e6, 0.0])),
    LinearTailPchip(np.array([0.0, 1.5]), np.array([20e3, 95e3])),
    0.015,
    (0.0, 1.5),
)
B1 = MagneticParams(gamma=1.77e7, delta=0.005, xm=0.022, ym=0.3, dh1=0.02, dh2=0.02,
                    dm=0.014, n=16, mu=1.0, bz=0.83, lya=2.5, wn0=1.0)
B2 = MagneticParams(gamma=1.77e7, delta=0.003, xm=0.021, ym=0.3, dh1=0.02, dh2=0.02,
                    dm=0.017, n=16, mu=1.0, bz=1.61, lya=2.5, wn0=1.0)
CURVE = CurveBrakeParams(points=tuple(
    ForceCurvePoint(velocity=v, force=f)
    for v, f in [(0.0, 0.0), (2.0, 20e3), (6.0, 55e3), (12.0, 90e3), (20.0, 110e3)]
))
RECOIL = RecoilParams(mass=2800.0, angle_deg=0.0, t_max=2.0, dt=4e-4)

_ARRAYS = ("t", "x", "v", "a", "f_total", "f_ext", "f_spring", "f_magnetic", "f_angle",
           "f_magnetic_each", "wn_each", "energy_kinetic", "energy_spring",
           "energy_brake_cum", "energy_input_cum")


def _new_session(config=(B1, B2)) -> IterativeSession:
    return IterativeSession(MODE_RECOIL, RECOIL, list(config), DRIVE)


def _stage_sequence(stage_index: np.ndarray) -> list[int]:
    seq = [int(stage_index[0])]
    for s in stage_index[1:]:
        if int(s) != seq[-1]:
            seq.append(int(s))
    return seq


class _BitwiseMixin:
    def assertSameResult(self, expected, actual):
        for name in _ARRAYS:
            a, b = getattr(expected, name), getattr(actual, name)
            self.assertEqual(a.shape, b.shape, name)
            self.assertTrue(np.array_equal(a, b), f"{name} differs")
        for name in ("recoil_end_time", "recoil_end_index", "return_end_time",
                     "return_end_index", "termination_reason", "spring_out_of_range",
                     "warnings", "energy_residual_pct"):
            self.assertEqual(getattr(expected, name), getattr(actual, name), name)


class RecoilEquivalenceTests(_BitwiseMixin, SimpleTestCase):
    """Без изменений конфигурации — ровно обычный расчёт."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.core = simulate_recoil_core(*DRIVE, RECOIL, [B1, B2])

    def test_core_cycle_is_complete(self):
        self.assertEqual(self.core.termination_reason, "returned_to_zero")

    def test_run_to_end_bitwise(self):
        session = _new_session()
        report = session.run_to_end()
        self.assertEqual(report.reason, STOP_FINISHED)
        self.assertSameResult(self.core, session.build_result().result)

    def test_chunked_stepping_bitwise(self):
        session = _new_session()
        for n in (1, 1, 7, 250, 1000):
            self.assertEqual(session.step(n).reason, STOP_STEPS)
        self.assertEqual(session.step(10**6).reason, STOP_FINISHED)
        self.assertSameResult(self.core, session.build_result().result)

    def test_state_roundtrip_bitwise(self):
        session = _new_session()
        session.step(1234)

        state = json.loads(json.dumps(session.to_dict()))
        buffer = io.BytesIO()
        np.savez(buffer, **session.history_arrays())
        buffer.seek(0)
        history = dict(np.load(buffer))

        restored = IterativeSession.from_dict(state, history, DRIVE)
        restored.run_to_end()
        self.assertSameResult(self.core, restored.build_result().result)

    def test_equal_config_is_noop(self):
        session = _new_session()
        session.step(300)
        self.assertFalse(session.reconfigure([replace(B1), replace(B2)]))
        self.assertEqual(len(session.stages), 1)
        session.run_to_end()
        self.assertSameResult(self.core, session.build_result().result)

    def test_change_then_revert_at_same_node_cancels_stage(self):
        session = _new_session()
        session.step(300)
        self.assertTrue(session.reconfigure([replace(B1, bz=0.5), B2]))
        self.assertTrue(session.reconfigure([replace(B1, bz=0.6), None]))
        self.assertEqual(len(session.stages), 2)          # правка, а не новый этап
        self.assertTrue(session.reconfigure([B1, B2]))    # вернули как было
        self.assertEqual(len(session.stages), 1)
        self.assertEqual(session.switch_events, [])
        session.run_to_end()
        self.assertSameResult(self.core, session.build_result().result)


class FreeFallTests(_BitwiseMixin, SimpleTestCase):
    """Свободное падение: лёгкое тело (адаптивное дробление шага)."""

    FF_RECOIL = RecoilParams(mass=0.04947, angle_deg=90.0, t_max=0.3, dt=1e-3)
    FF_BRAKE = MagneticParams(gamma=1.77e7, delta=0.003, xm=0.01, ym=0.3, dh1=0.02, dh2=0.02,
                              dm=0.006, n=1, mu=1.0, bz=0.32, lya=2.5, wn0=1.0)

    def test_run_to_end_bitwise(self):
        core = simulate_free_fall(self.FF_RECOIL, [self.FF_BRAKE])
        session = IterativeSession(MODE_FREE_FALL, self.FF_RECOIL, [self.FF_BRAKE])
        session.step(17)
        session.run_to_end()
        self.assertSameResult(core, session.build_result().result)

    def test_switch_forward_only(self):
        session = IterativeSession(MODE_FREE_FALL, self.FF_RECOIL, [self.FF_BRAKE])
        self.assertEqual(session.advance_distance(0.002).reason, STOP_TARGET)
        self.assertAlmostEqual(session.x, 0.002, delta=1e-12)
        session.reconfigure([replace(self.FF_BRAKE, bz=0.5)])
        session.run_to_end()
        outcome = session.build_result()
        self.assertEqual(outcome.result.termination_reason, "free_fall")
        self.assertEqual(_stage_sequence(outcome.stage_index), [0, 1])
        self.assertEqual([e.direction for e in outcome.switch_events], [DIRECTION_FORWARD])


class SwitchingTests(SimpleTestCase):

    def test_distance_lands_exactly_and_returns_to_grid(self):
        session = _new_session()
        report = session.advance_distance(0.25)
        self.assertEqual(report.reason, STOP_TARGET)
        self.assertAlmostEqual(session.x, 0.25, delta=1e-10)
        self.assertFalse(session.current()["on_grid"])
        j = session.grid_index
        session.step(1)
        self.assertEqual(session.t, float(np.arange(0.0, RECOIL.t_max + RECOIL.dt, RECOIL.dt)[j + 1]))

    def test_reverse_switches_mirror_forward(self):
        session = _new_session()
        session.advance_distance(0.25)
        session.reconfigure([replace(B1, bz=B1.bz * 0.7), B2])
        session.advance_distance(0.25)
        session.reconfigure([replace(B1, bz=B1.bz * 0.7), None])
        session.run_to_end()
        outcome = session.build_result()

        self.assertEqual(outcome.result.termination_reason, "returned_to_zero")
        self.assertEqual(_stage_sequence(outcome.stage_index), [0, 1, 2, 1, 0])
        events = outcome.switch_events
        self.assertEqual([(e.direction, e.stage_from, e.stage_to) for e in events], [
            (DIRECTION_FORWARD, 0, 1), (DIRECTION_FORWARD, 1, 2),
            (DIRECTION_RETURN, 2, 1), (DIRECTION_RETURN, 1, 0),
        ])
        self.assertAlmostEqual(events[2].x, events[1].x, delta=1e-9)
        self.assertAlmostEqual(events[3].x, events[0].x, delta=1e-9)
        self.assertLess(events[2].v, 0.0)

        res = outcome.result
        for e in events:
            # узел-дубль: те же (t, x, v), силы старой и новой конфигурации
            self.assertEqual(res.t[e.row], res.t[e.row - 1])
            self.assertEqual(res.x[e.row], res.x[e.row - 1])
            self.assertEqual(outcome.stage_index[e.row], e.stage_to)
            self.assertEqual(outcome.stage_index[e.row - 1], e.stage_from)

        stage2 = outcome.stage_index == 2
        self.assertTrue(np.all(res.f_magnetic_each[stage2, 1] == 0.0))
        self.assertTrue(np.any(res.f_magnetic_each[~stage2, 1] != 0.0))
        self.assertLess(res.energy_residual_pct, 0.5)

    def test_add_slot_and_change_type(self):
        session = _new_session()
        session.advance_distance(0.3)
        session.reconfigure([CURVE, B2, CURVE])      # слот 0 → таблица, слот 2 добавлен
        session.run_to_end()
        outcome = session.build_result()
        res = outcome.result

        self.assertEqual(res.f_magnetic_each.shape[1], 3)
        stage0 = outcome.stage_index == 0
        self.assertTrue(np.all(res.f_magnetic_each[stage0, 2] == 0.0))
        moving1 = (outcome.stage_index == 1) & (np.abs(res.v) > 1e-3)
        self.assertTrue(np.all(res.f_magnetic_each[moving1, 2] != 0.0))
        self.assertEqual(_stage_sequence(outcome.stage_index), [0, 1, 0])
        self.assertIsNone(outcome.stages[0].config[2])

    def test_wn_rule_changed_slot_resets_unchanged_keeps(self):
        session = _new_session()
        session.step(200)
        wn_before = list(session.wn)
        session.reconfigure([replace(B1, bz=0.9, wn0=0.37), B2])
        self.assertEqual(session.wn[0], 0.37)
        self.assertEqual(session.wn[1], wn_before[1])

    def test_reconfigure_on_return_forbidden(self):
        session = _new_session()
        while not session.turned:
            session.step(50)
        self.assertFalse(session.can_reconfigure)
        with self.assertRaises(ValueError):
            session.reconfigure([B1, None])

    def test_turnaround_before_target(self):
        session = _new_session()
        report = session.advance_distance(50.0)
        self.assertEqual(report.reason, STOP_TURNAROUND)
        self.assertTrue(report.turned)
        self.assertFalse(session.finished)

    def test_stop_gives_partial_result(self):
        session = _new_session()
        session.step(100)
        session.stop()
        res = session.build_result().result
        self.assertEqual(res.termination_reason, TERMINATION_STOPPED)
        self.assertEqual(len(res.t), 101)
        self.assertIsNone(res.return_end_time)
        with self.assertRaises(ValueError):
            session.reconfigure([B1, None])

    def test_removing_slot_rejected(self):
        session = _new_session()
        session.step(10)
        with self.assertRaises(ValueError):
            session.reconfigure([B1])


class UndoAndResumeTests(_BitwiseMixin, SimpleTestCase):
    """Срез 5: отмена последнего изменения и продолжение остановленного расчёта."""

    WEAK = replace(B1, bz=0.6)

    def test_undo_restores_state_bitwise(self):
        # Эталон: до 0.25 м, C1, 100 шагов (ещё откат), до конца.
        reference = _new_session()
        reference.advance_distance(0.25)
        reference.reconfigure([self.WEAK, B2])
        reference.step(100)
        reference.run_to_end()

        # То же + лишнее изменение (с новым тормозом), немного шагов, до конца — и отмена.
        session = _new_session()
        session.advance_distance(0.25)
        session.reconfigure([self.WEAK, B2])
        session.step(100)
        session.reconfigure([self.WEAK, None, CURVE])
        session.step(300)
        session.run_to_end()
        self.assertTrue(session.finished)

        removed = session.undo_last_change()
        self.assertEqual(removed.index, 2)
        self.assertFalse(session.finished)
        self.assertEqual(session.n_slots, 2)
        self.assertEqual(len(session.stages), 2)
        self.assertEqual(session.phase, "recoil")
        session.run_to_end()
        self.assertSameResult(reference.build_result().result, session.build_result().result)

    def test_undo_everything_equals_plain_distance_run(self):
        reference = _new_session()
        reference.advance_distance(0.25)
        reference.run_to_end()

        session = _new_session()
        session.advance_distance(0.25)
        session.reconfigure([self.WEAK, B2])
        session.advance_distance(0.2)
        session.reconfigure([self.WEAK, None])
        session.step(50)
        session.undo_last_change()
        session.undo_last_change()
        self.assertFalse(session.can_undo)
        with self.assertRaises(ValueError):
            session.undo_last_change()
        session.run_to_end()
        self.assertSameResult(reference.build_result().result, session.build_result().result)

    def test_undo_survives_serialization(self):
        session = _new_session()
        session.advance_distance(0.25)
        session.reconfigure([self.WEAK, B2])
        session.step(200)
        restored = IterativeSession.from_dict(
            json.loads(json.dumps(session.to_dict())), session.history_arrays(), DRIVE)
        self.assertTrue(restored.can_undo)
        restored.undo_last_change()
        self.assertEqual(restored.x, session.stages[1].x)
        self.assertEqual(restored.config, session.stages[0].config)

    def test_resume_after_stop_bitwise(self):
        core = simulate_recoil_core(*DRIVE, RECOIL, [B1, B2])
        session = _new_session()
        session.step(100)
        session.stop()
        self.assertTrue(session.resume())
        self.assertFalse(session.resume())      # уже идёт — повторно нечего
        session.run_to_end()
        self.assertSameResult(core, session.build_result().result)


class WnMemoryTests(SimpleTestCase):

    def test_negligible_at_recoil_speeds(self):
        self.assertLess(wn_memory_coefficient(10.0, B1), 1e-15)

    def test_significant_for_thick_plate_at_high_speed(self):
        thick = replace(B1, delta=0.008, xm=0.012, dm=0.006)
        self.assertGreater(wn_memory_coefficient(100.0, thick), 0.01)

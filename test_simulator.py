"""Behavioral checks for simulation, noise accounting, and process boundaries."""

import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

import simulator
import scheduling
from atommovr.utils.AtomArray import AtomArray
from atommovr.utils.Move import Move
from atommovr.utils.core import PhysicalParams
from atommovr.utils.errormodels import ZeroNoise
from atommovr.utils.failure_policy import FailureEvent


def run_core(**config):
    clean, error = simulator._validate_config(config)
    if error:
        raise AssertionError(error)
    return simulator._simulate_core(clean)


def native_replay(**config):
    """Diagnostic reference: replay unprotected original algorithm batches."""
    clean, error = simulator._validate_config(config)
    if error:
        raise AssertionError(error)
    array, _ = simulator._make_initial_array(clean)
    _, batches, planned = simulator.ALGORITHMS[clean["algorithm"]]().get_moves(
        copy.deepcopy(array), do_ejection=False)
    array.evaluate_moves(batches)
    return bool(planned), int((array.matrix * array.target).sum()), int(array.matrix.sum())


class SimulatorTests(unittest.TestCase):
    def test_preview_matches_simulation_without_algorithms_or_spawn(self):
        with patch.object(simulator, "ALGORITHMS", {name: None for name in simulator.ALGORITHMS}), \
             patch.object(simulator.mp, "get_context", side_effect=AssertionError("preview spawned")):
            initial = simulator.preview()
        executed = run_core()
        self.assertTrue(initial["preview"])
        self.assertEqual(initial["summary"]["status"], "preview")
        self.assertEqual(initial["frames"], [])
        self.assertEqual(initial["initial"], executed["initial"])
        self.assertEqual(initial["target"], executed["target"])
        self.assertEqual(initial["summary"]["initial_count"], executed["summary"]["initial_count"])
        self.assertEqual(initial["summary"]["filled"], sum(
            cell * initial["target"][r][c] for r, row in enumerate(initial["initial"]) for c, cell in enumerate(row)))
        loading_seed, _ = np.random.SeedSequence(1).spawn(2)
        expected = simulator.random_loading([10, 10], .6, rng=np.random.default_rng(loading_seed))
        self.assertEqual(initial["initial"], expected.tolist())
        json.dumps(initial, allow_nan=False)

    def test_preview_target_matches_all_patterns(self):
        for pattern in simulator.PATTERNS:
            with self.subTest(pattern=pattern):
                displayed = simulator.preview({"pattern": pattern, "loading_prob": .8})
                result = run_core(pattern=pattern, loading_prob=.8)
                self.assertEqual(displayed["initial"], result["initial"])
                self.assertEqual(displayed["target"], result["target"])

    def test_manual_matrix_replays_same_initial_state_and_error_stream(self):
        config = dict(noise=True, pickup_success=50, putdown_success=50)
        random = run_core(**config)
        matrix = simulator.preview(config)["initial"]
        manual_config = dict(config, initial_mode="manual", initial_matrix=matrix)
        displayed = simulator.preview(manual_config)
        manual = run_core(**manual_config)
        self.assertEqual(displayed["initial"], matrix)
        self.assertEqual(displayed["target"], manual["target"])
        self.assertEqual(manual["initial"], random["initial"])
        self.assertEqual(manual["frames"], random["frames"])
        self.assertEqual(manual["summary"], random["summary"])
        matrix[0][0] = 1 - matrix[0][0]
        self.assertNotEqual(displayed["initial"], matrix)

    def test_manual_empty_full_and_pickup_failure_counts(self):
        empty = [[0] * 4 for _ in range(4)]
        displayed = simulator.preview({"n": 4, "initial_mode": "manual", "initial_matrix": empty})
        self.assertEqual(displayed["summary"]["status"], "preview")
        self.assertEqual(displayed["summary"]["initial_count"], 0)
        result = run_core(n=4, initial_mode="manual", initial_matrix=empty)
        self.assertEqual(result["summary"]["status"], "insufficient")
        self.assertIn("点击阵列", result["summary"]["message"])
        full = run_core(n=4, loading_prob=0, initial_mode="manual", initial_matrix=[[1] * 4 for _ in range(4)])
        self.assertEqual(full["summary"]["status"], "success")
        self.assertEqual(full["summary"]["initial_count"], 16)
        self.assertEqual(full["summary"]["filled"], 16)
        self.assertEqual(full["frames"], [])
        one = [[0] * 4 for _ in range(4)]
        one[0][0] = 1
        for pickup, putdown, remaining, event_count in [(0, 100, 1, "pickup_failures"), (100, 0, 0, "putdown_losses")]:
            with self.subTest(pickup=pickup, putdown=putdown):
                failed = run_core(n=4, target_size=1, initial_mode="manual", initial_matrix=one,
                                  noise=True, lifetime=3600, pickup_success=pickup, putdown_success=putdown)
                self.assertEqual(failed["summary"]["status"], "incomplete")
                self.assertEqual(failed["summary"]["initial_count"], 1)
                self.assertEqual(failed["summary"]["remaining"], remaining)
                self.assertEqual(failed["summary"]["losses"], 1 - remaining)
                self.assertEqual(failed["summary"][event_count], 1)

    def test_manual_validation_rejects_bad_shapes_and_cells_without_spawn(self):
        valid = [[0] * 4 for _ in range(4)]
        invalid = [None, [], valid[:-1], [[0] * 3 for _ in range(4)],
                   [[0, 0, 0, 2]] + valid[1:], [[0, 0, 0, "1"]] + valid[1:],
                   [[0, 0, 0, True]] + valid[1:], [[0, 0, 0, float("nan")]] + valid[1:]]
        for matrix in invalid:
            config = {"n": 4, "initial_mode": "manual", "initial_matrix": matrix}
            with self.subTest(matrix=matrix), patch.object(simulator.mp, "get_context") as context:
                result = simulator.simulate(config)
                displayed = simulator.preview(config)
                self.assertEqual(result["summary"]["status"], "invalid")
                self.assertEqual(displayed["summary"]["status"], "invalid")
                json.dumps(result, allow_nan=False)
                json.dumps(displayed, allow_nan=False)
                context.assert_not_called()
        self.assertEqual(simulator.preview({"initial_mode": "automatic"})["summary"]["status"], "invalid")

    def test_default_and_repeat_are_deterministic_and_json_safe(self):
        first = run_core()
        self.assertEqual(first, run_core())
        self.assertEqual(first["summary"]["status"], "success")
        self.assertEqual(first["summary"]["filled"], 16)
        self.assertEqual(first["summary"]["losses"], 0)
        json.dumps(first, allow_nan=False)

    def test_every_public_algorithm_and_pattern_combination(self):
        for algorithm in simulator.ALGORITHMS:
            for pattern in simulator.PATTERNS:
                if pattern not in simulator.SUPPORTED_PATTERNS_BY_ALGORITHM[algorithm]:
                    self.assertEqual(simulator.simulate({"algorithm": algorithm, "pattern": pattern})["summary"]["status"], "invalid")
                    continue
                with self.subTest(algorithm=algorithm, pattern=pattern):
                    result = run_core(algorithm=algorithm, pattern=pattern, loading_prob=0.8)
                    self.assertEqual(result["summary"]["status"], "success")
                    self.assertEqual(result["summary"]["filled"], result["summary"]["target_count"])
                    self.assertEqual(result["summary"]["remaining"], result["summary"]["initial_count"])
                    for previous, current in zip(result["frames"], result["frames"][1:]):
                        self.assertEqual(previous["after"], current["before"])

    def test_additional_native_algorithm_edges_have_truthful_results(self):
        for algorithm in ("lbap", "generalized", "bc"):
            for n in (4, 5, 6, 24):
                for pattern in simulator.SUPPORTED_PATTERNS_BY_ALGORITHM[algorithm]:
                    with self.subTest(algorithm=algorithm, n=n, pattern=pattern):
                        result = run_core(algorithm=algorithm, n=n, target_size=2,
                                          pattern=pattern, loading_prob=.9)
                        summary = result["summary"]
                        self.assertIn(summary["status"], ("success", "incomplete"))
                        self.assertEqual(summary["executed_batches"], len(result["frames"]))
                        final = np.asarray(result["frames"][-1]["after"] if result["frames"] else result["initial"])
                        target = np.asarray(result["target"])
                        self.assertEqual(summary["remaining"], int(final.sum()))
                        self.assertEqual(summary["filled"], int((final * target).sum()))
                        self.assertEqual(summary["losses"], summary["initial_count"] - int(final.sum()))
                        if summary["status"] == "success":
                            self.assertEqual(summary["filled"], summary["target_count"])
                        else:
                            self.assertLess(summary["filled"], summary["target_count"])

    def test_lbap_native_planned_success_does_not_hide_incomplete_replay(self):
        # The original LBAP planner marks this feasible case successful, but
        # its returned rounds do not fill the target during native replay.
        config = dict(algorithm="lbap", n=5, target_size=4, loading_prob=.8, seed=42)
        planned, native_filled, _ = native_replay(**config)
        self.assertTrue(planned)
        self.assertEqual(native_filled, 11)
        result = run_core(**config)
        self.assertEqual(result["summary"]["status"], "success")
        self.assertEqual(result["summary"]["target_count"], 16)
        self.assertEqual(result["summary"]["filled"], 16)
        self.assertEqual(result["summary"]["tweezer_count"], 1)
        self.assertEqual(result["summary"]["collision_losses"], 0)

    def test_legacy_bc_actual_success_overrides_native_false_flag(self):
        # BC's original target broadcasting makes its return flag unreliable;
        # the library remains unchanged and actual replay determines success.
        result = run_core(algorithm="bc")
        self.assertFalse(result["summary"]["planned_success"])
        self.assertEqual(result["summary"]["status"], "success")
        self.assertEqual(result["summary"]["filled"], 16)
        self.assertEqual(result["summary"]["losses"], 0)

    def test_lbap_native_round_limit_option_fills_distant_small_targets(self):
        for n in (7, 10, 24):
            initial = [[0] * n for _ in range(n)]
            initial[-1][-1] = 1
            config = dict(algorithm="lbap", n=n, target_size=1,
                          initial_mode="manual", initial_matrix=initial)
            with self.subTest(n=n):
                native_planned, native_filled, _ = native_replay(**config)
                self.assertFalse(native_planned)
                self.assertEqual(native_filled, 0)
                result = run_core(**config)
                self.assertEqual(result["summary"]["status"], "success")
                self.assertTrue(result["summary"]["planned_success"])
                self.assertEqual(result["summary"]["filled"], 1)
                self.assertEqual(result["summary"]["remaining"], 1)

    def test_new_native_stable_initial_cases_are_deterministic(self):
        for algorithm in ("lbap", "generalized", "bc"):
            with self.subTest(algorithm=algorithm):
                first = run_core(algorithm=algorithm, loading_prob=.8)
                self.assertEqual(first, run_core(algorithm=algorithm, loading_prob=.8))
                self.assertEqual(first["summary"]["status"], "success")

    def test_native_planning_exception_retains_initial_preview(self):
        class BrokenAlgorithm:
            def get_moves(self, *_args, **_kwargs):
                raise RuntimeError("native planner failed")
        with patch.dict(simulator.ALGORITHMS, {"generalized": BrokenAlgorithm}):
            result = run_core(algorithm="generalized")
        self.assertEqual(result["summary"]["status"], "algorithm_error")
        self.assertIn("native planner failed", result["summary"]["message"])
        self.assertEqual(len(result["initial"]), 10)
        self.assertEqual(result["frames"], [])

    def test_empty_insufficient_and_already_complete(self):
        empty = run_core(loading_prob=0)
        self.assertEqual(empty["summary"]["status"], "insufficient")
        self.assertEqual(empty["frames"], [])
        full = run_core(loading_prob=1)
        self.assertEqual(full["summary"]["status"], "success")
        self.assertEqual(full["frames"], [])
        self.assertEqual(full["summary"]["remaining"], 100)
        insufficient = run_core(target_size=10)
        self.assertEqual(insufficient["summary"]["status"], "insufficient")
        self.assertEqual(insufficient["summary"]["target_count"], 100)

    def test_invalid_config_is_safe_and_does_not_spawn(self):
        for config in [[], {"n": True}, {"n": 25}, {"target_size": 11}, {"speed": 0},
                       {"spacing_um": float("nan")}, {"lifetime": 0}, {"seed": -1},
                       {"pickup_success": 101}, {"noise": "false"}, {"pattern": "unknown"},
                       {"algorithm": []}, {"pattern": {}}, {"seed": 10**1000},
                       {"tweezer_count": 0}, {"tweezer_count": 25}, {"tweezer_count": 1.5}]:
            with self.subTest(config=config), patch.object(simulator.mp, "get_context") as context:
                result = simulator.simulate(config)
                self.assertEqual(result["summary"]["status"], "invalid")
                json.dumps(result, allow_nan=False)
                context.assert_not_called()

    def test_speed_and_spacing_control_physical_time(self):
        default = run_core()
        half_speed = run_core(speed=0.05)
        double_spacing = run_core(spacing_um=10)
        self.assertEqual(default["initial"], half_speed["initial"])
        self.assertEqual(default["frames"][-1]["after"], half_speed["frames"][-1]["after"])
        self.assertAlmostEqual(half_speed["summary"]["simulated_time"], 2 * default["summary"]["simulated_time"])
        self.assertAlmostEqual(double_spacing["summary"]["simulated_time"], 2 * default["summary"]["simulated_time"])

    def test_replay_time_matches_library_evaluate_moves(self):
        result = run_core()
        array = AtomArray([10, 10], params=PhysicalParams(), error_model=ZeroNoise())
        array.matrix = np.asarray(result["initial"], dtype=np.uint8)[:, :, None]
        batches = [[Move(*move["from"], *move["to"]) for move in frame["moves"]] for frame in result["frames"]]
        time, counts = array.evaluate_moves(batches)
        self.assertAlmostEqual(time, result["summary"]["simulated_time"])
        self.assertEqual(counts[0], result["summary"]["executed_batches"])
        self.assertEqual(counts[1], result["summary"]["total_moves"])
        self.assertEqual(array.matrix[:, :, 0].tolist(), result["frames"][-1]["after"])

    def test_nonzero_operation_times_match_native_evaluation_with_noise_off_and_on(self):
        config = dict(pickup_time_us=11, putdown_time_us=17, accel_time_us=23, decel_time_us=31)
        result = run_core(**config)
        self.assertEqual(result["initial"], run_core()["initial"])
        self.assertGreater(result["summary"]["simulated_time"], run_core()["summary"]["simulated_time"])
        array = AtomArray([10, 10], params=PhysicalParams(),
                          error_model=ZeroNoise(pickup_time=11e-6, putdown_time=17e-6,
                                                accel_time=23e-6, decel_time=31e-6))
        array.matrix = np.asarray(result["initial"], dtype=np.uint8)[:, :, None]
        batches = [[Move(*move["from"], *move["to"]) for move in frame["moves"]] for frame in result["frames"]]
        native_time, _ = array.evaluate_moves(batches)
        self.assertAlmostEqual(native_time, result["summary"]["simulated_time"])
        noisy = run_core(**config, noise=True, lifetime=3600, pickup_success=100, putdown_success=100)
        self.assertAlmostEqual(noisy["summary"]["simulated_time"], native_time)
        self.assertEqual(noisy["frames"][-1]["after"], result["frames"][-1]["after"])
        self.assertEqual(noisy["summary"]["losses"], 0)

    def test_operation_times_are_applied_once_across_native_continuous_segments(self):
        class ContinuousAlgorithm:
            def get_moves(self, *_args, **_kwargs):
                return None, [[Move(2, 0, 2, 1)], [Move(2, 1, 2, 2)]], True
        initial = [[0] * 6 for _ in range(6)]
        initial[2][0] = 1
        config = dict(n=6, target_size=1, initial_mode="manual", initial_matrix=initial,
                      pickup_time_us=11, putdown_time_us=17, accel_time_us=23, decel_time_us=31)
        with patch.dict(simulator.ALGORITHMS, {"parallel": ContinuousAlgorithm}):
            ideal = run_core(**config)
            failed_release = run_core(**config, noise=True, lifetime=3600,
                                      pickup_success=100, putdown_success=0)
        self.assertEqual(ideal["summary"]["status"], "success")
        self.assertAlmostEqual(ideal["frames"][0]["duration"], (50 + 11 + 23) * 1e-6)
        self.assertAlmostEqual(ideal["frames"][1]["duration"], (50 + 17 + 31) * 1e-6)
        self.assertAlmostEqual(ideal["summary"]["simulated_time"], 182e-6)
        self.assertEqual(failed_release["frames"][0]["moves"][0]["event_name"], "SUCCESS")
        self.assertEqual(failed_release["frames"][1]["moves"][0]["event_name"], "PUTDOWN_FAIL")
        self.assertEqual(failed_release["summary"]["putdown_losses"], 1)
        self.assertEqual(failed_release["summary"]["collision_losses"], 0)

    def test_operation_time_validation_is_finite_bounded_and_never_spawns(self):
        for operation in ("pickup", "putdown", "accel", "decel"):
            for bad in (-1, 10001, float("inf"), float("nan"), True, "1"):
                with self.subTest(operation=operation, bad=bad), patch.object(simulator.mp, "get_context") as context:
                    result = simulator.simulate({f"{operation}_time_us": bad})
                    self.assertEqual(result["summary"]["status"], "invalid")
                    json.dumps(result, allow_nan=False)
                    context.assert_not_called()
            clean, error = simulator._validate_config({f"{operation}_time_us": 10000})
            self.assertIsNone(error)
            self.assertEqual(simulator._operation_times(clean)[f"{operation}_time"], .01)

    def test_vacuum_loss_uses_total_operation_time_and_noise_off_stays_ideal(self):
        config = dict(pickup_time_us=10000, putdown_time_us=10000, accel_time_us=10000, decel_time_us=10000)
        noisy = run_core(**config, noise=True, lifetime=.001, pickup_success=100, putdown_success=100)
        self.assertEqual(noisy["summary"]["vacuum_losses"], noisy["summary"]["initial_count"])
        self.assertEqual(noisy["summary"]["remaining"], 0)
        self.assertEqual(noisy["summary"]["putdown_losses"], 0)
        self.assertEqual(noisy, run_core(**config, noise=True, lifetime=.001, pickup_success=100, putdown_success=100))
        short = run_core(noise=True, lifetime=.001, pickup_success=100, putdown_success=100)
        self.assertGreater(short["summary"]["remaining"], noisy["summary"]["remaining"])
        ideal = run_core(**config, lifetime=.001)
        self.assertEqual(ideal["summary"]["status"], "success")
        self.assertEqual(ideal["summary"]["losses"], 0)
        self.assertGreater(ideal["summary"]["simulated_time"], .04)

    def test_noise_is_reproducible_and_vacuum_loss_changes_result(self):
        config = dict(noise=True, speed=0.001, lifetime=0.01, pickup_success=100, putdown_success=100)
        result = run_core(**config)
        self.assertEqual(result, run_core(**config))
        self.assertGreater(result["summary"]["vacuum_losses"], 0)
        self.assertEqual(result["summary"]["vacuum_losses"], sum(len(frame["vacuum_losses"]) for frame in result["frames"]))
        self.assertLess(result["summary"]["remaining"], result["summary"]["initial_count"])
        self.assertEqual(result["summary"]["status"], "incomplete")
        ideal = run_core(speed=0.001, lifetime=0.01)
        self.assertEqual(ideal["summary"]["losses"], 0)
        self.assertEqual(ideal["summary"]["status"], "success")

    def test_pickup_failure_leaves_atom_while_putdown_failure_loses_it(self):
        for fail_key, expected_remaining, expected_event in [
            ("pickup_fail_rate", 1, FailureEvent.PICKUP_FAIL),
            ("putdown_fail_rate", 0, FailureEvent.PUTDOWN_FAIL),
        ]:
            model = simulator.RecordingErrorModel(lifetime=np.inf, pickup_fail_rate=0,
                                                  putdown_fail_rate=0, seed=1)
            setattr(model, fail_key, 1)
            array = simulator.RecordingAtomArray([4, 4], error_model=model)
            array.matrix[0, 0, 0] = 1
            move = Move(0, 0, 0, 1)
            array.move_atoms([move])
            self.assertEqual(int(array.matrix.sum()), expected_remaining)
            self.assertEqual(move.fail_event, expected_event)

    def test_empty_aod_intersections_are_not_atom_losses(self):
        result = run_core(algorithm="bcv2")
        self.assertGreater(result["summary"]["empty_moves"], 0)
        self.assertEqual(result["summary"]["losses"], 0)
        self.assertEqual(result["summary"]["collision_losses"], 0)

    def test_recording_captures_library_completed_move_round(self):
        array = simulator.RecordingAtomArray([4, 4], error_model=simulator.RecordingErrorModel(
            lifetime=np.inf, pickup_fail_rate=0, putdown_fail_rate=0, seed=1))
        array.matrix[0, 0, 0] = 1
        array.matrix[1, 1, 0] = 1
        # Two diagonal entries imply four physical AOD intersections.
        sparse = [Move(0, 0, 0, 1), Move(1, 1, 1, 2)]
        array.move_atoms(sparse)
        self.assertEqual(len(array.applied_moves), 4)
        self.assertEqual(sum(m.fail_event == FailureEvent.NO_ATOM for m in array.applied_moves), 2)

    def test_overlap_cleanup_is_recorded_without_changing_library_behavior(self):
        array = simulator.RecordingAtomArray([4, 4], error_model=simulator.RecordingErrorModel(
            lifetime=np.inf, pickup_fail_rate=0, putdown_fail_rate=0, seed=1))
        array.matrix[0, 0, 0] = array.matrix[0, 1, 0] = 1
        array.move_atoms([Move(0, 0, 0, 1)])
        self.assertEqual(array.overlap_losses, [[0, 1]])
        self.assertEqual(array.overlap_lost_atoms, 2)
        self.assertEqual(int(array.matrix.sum()), 0)

    def test_partial_frames_survive_unexpected_replay_error(self):
        original = simulator.RecordingAtomArray.move_atoms
        calls = 0
        def fail_second(array, *args, **kwargs):
            nonlocal calls
            # Safety trial copies always use ZeroNoise; inject only into the
            # actual noisy replay, after the first completed visible frame.
            if isinstance(array.error_model, simulator.RecordingErrorModel):
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected replay failure")
            return original(array, *args, **kwargs)
        with patch.object(simulator.RecordingAtomArray, "move_atoms", fail_second):
            result = run_core(noise=True, lifetime=3600, pickup_success=100, putdown_success=100)
        self.assertEqual(result["summary"]["status"], "algorithm_error")
        self.assertEqual(len(result["frames"]), 1)
        self.assertEqual(result["summary"]["executed_batches"], 1)
        self.assertIn("injected replay failure", result["summary"]["message"])

    def test_public_spawned_process_returns_default_result(self):
        result = simulator.simulate()
        self.assertEqual(result["summary"]["status"], "success", result["summary"]["message"])
        self.assertEqual(result, run_core())

    def test_public_lbap_worker_uses_native_dependency_and_truthful_status(self):
        result = simulator.simulate({"algorithm": "lbap"})
        self.assertEqual(result, run_core(algorithm="lbap"))
        self.assertTrue(result["summary"]["planned_success"])
        self.assertEqual(native_replay(algorithm="lbap")[1], 14)
        self.assertEqual(result["summary"]["status"], "success")
        self.assertEqual(result["summary"]["filled"], 16)
        self.assertEqual(result["summary"]["collision_losses"], 0)
        self.assertEqual(result["summary"]["max_active_tweezers"], 1)

    def test_public_timeout_returns_safe_error(self):
        with patch.object(simulator, "SIMULATION_TIMEOUT_SECONDS", 0.001):
            result = simulator.simulate()
        self.assertEqual(result["summary"]["status"], "algorithm_error")
        self.assertIn("超过", result["summary"]["message"])
        json.dumps(result, allow_nan=False)

    def test_process_setup_failure_returns_reviewable_error_data(self):
        with patch.object(simulator.mp, "get_context", side_effect=OSError("injected process setup failure")):
            result = simulator.simulate()
        self.assertEqual(result["summary"]["status"], "algorithm_error")
        self.assertIn("injected process setup failure", result["summary"]["message"])
        self.assertEqual(result["frames"], [])
        json.dumps(result, allow_nan=False)

    def test_process_start_method_is_configurable_and_validated(self):
        with patch.dict(simulator.os.environ, {}, clear=True):
            self.assertEqual(simulator.simulation_start_method(), "spawn")
        with patch.dict(simulator.os.environ, {"ATOMMOVR_PROCESS_START_METHOD": "fork"}, clear=True), \
             patch.object(simulator.mp, "get_all_start_methods", return_value=["spawn", "fork"]):
            self.assertEqual(simulator.simulation_start_method(), "fork")
        with patch.dict(simulator.os.environ, {"ATOMMOVR_PROCESS_START_METHOD": "invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "spawn"):
                simulator.simulation_start_method()


class SchedulingTests(unittest.TestCase):
    @staticmethod
    def array_with(*positions):
        array = AtomArray([4, 4], error_model=ZeroNoise())
        for row, column in positions:
            array.matrix[row, column, 0] = 1
        return array

    @staticmethod
    def replay(array, schedule):
        for index, batch in enumerate(schedule.batches):
            array.move_atoms(batch, schedule.batches[index - 1] if index else [],
                             schedule.batches[index + 1] if index + 1 < len(schedule.batches) else [])
        return array

    def test_capacity_counts_empty_and_hold_aod_intersections(self):
        array = self.array_with((0, 0), (1, 1))
        native = [[Move(0, 0, 0, 1), Move(1, 1, 1, 2)]]
        self.assertEqual(len(scheduling.aod_closure(array, native[0])), 4)
        for cap, expected_batches, expected_peak in [(4, 1, 4), (2, 2, 1), (1, 2, 1)]:
            with self.subTest(cap=cap):
                schedule = scheduling.schedule_moves(array, native, cap)
                self.assertIsNone(schedule.blocked_reason)
                self.assertEqual(len(schedule.batches), expected_batches)
                self.assertEqual(max(map(len, schedule.batches)), expected_peak)
                result = self.replay(copy.deepcopy(array), schedule)
                self.assertEqual(int(result.matrix.sum()), 2)
                self.assertTrue(result.matrix[0, 1, 0])
                self.assertTrue(result.matrix[1, 2, 0])

    def test_occupied_extra_ghost_is_not_promoted_to_algorithm_intent(self):
        array = self.array_with((0, 0), (1, 1), (1, 0))
        native = [[Move(0, 0, 0, 1), Move(1, 1, 1, 2)]]
        schedule = scheduling.schedule_moves(array, native, 4)
        self.assertIsNone(schedule.blocked_reason)
        self.assertEqual(len(schedule.batches), 2)
        result = self.replay(copy.deepcopy(array), schedule)
        self.assertTrue(result.matrix[1, 0, 0], "extra occupied intersection must stay put")
        self.assertTrue(result.matrix[0, 1, 0])
        self.assertTrue(result.matrix[1, 2, 0])
        self.assertEqual(int(result.matrix.sum()), 3)

    def test_single_tweezer_chain_starts_at_vacant_destination_end(self):
        array = self.array_with((0, 0), (0, 1))
        schedule = scheduling.schedule_moves(array, [[Move(0, 0, 0, 1), Move(0, 1, 0, 2)]], 1)
        self.assertIsNone(schedule.blocked_reason)
        self.assertEqual(scheduling.source(schedule.batches[0][0]), (0, 1))
        result = self.replay(array, schedule)
        self.assertEqual(result.matrix[0, :, 0].tolist(), [0, 1, 1, 0])

    def test_swap_dependency_is_blocked_without_buffer_or_loss(self):
        array = self.array_with((0, 0), (0, 1))
        initial = array.matrix.copy()
        schedule = scheduling.schedule_moves(array, [[Move(0, 0, 0, 1), Move(0, 1, 0, 0)]], 1)
        self.assertIsNotNone(schedule.blocked_reason)
        self.assertEqual(schedule.batches, [])
        np.testing.assert_array_equal(array.matrix, initial)

    def test_continuous_intersection_is_detected_between_distinct_endpoints(self):
        first, second = Move(0, 0, 1, 1), Move(0, 1, 1, 0)
        self.assertNotEqual(scheduling.source(first), scheduling.source(second))
        self.assertNotEqual(scheduling.destination(first), scheduling.destination(second))
        self.assertEqual(scheduling.minimum_relative_distance_squared(first, second), 0)
        safe, reason, _, _ = scheduling.check_batch(self.array_with(), [first, second], 4)
        self.assertFalse(safe)
        self.assertIn("碰撞", reason)
        self.assertEqual(scheduling.minimum_relative_distance_squared(Move(0, 0, 0, 1), Move(1, 0, 1, 1)), 1)

    def test_static_occupied_endpoint_is_blocked_before_library_execution(self):
        array = self.array_with((0, 0), (0, 1))
        initial = array.matrix.copy()
        safe, _, _, _ = scheduling.check_batch(array, [Move(0, 0, 0, 1)], 1)
        self.assertFalse(safe)
        np.testing.assert_array_equal(array.matrix, initial)

    def test_out_of_bounds_and_mutated_long_moves_are_not_silently_clipped(self):
        array = self.array_with((0, 0))
        long_move = Move(0, 0, 0, 1)
        long_move.to_col = 2
        for invalid in (long_move, Move(0, 0, -1, 0), Move(-1, 0, 0, 0)):
            with self.subTest(move=invalid):
                schedule = scheduling.schedule_moves(array, [[invalid]], 4)
                self.assertIsNotNone(schedule.blocked_reason)
                self.assertEqual(schedule.batches, [])
                safe, _, _, _ = scheduling.check_batch(array, [invalid], 4)
                self.assertFalse(safe)

    def test_resource_limit_counts_full_aod_closure_and_preserves_safe_prefix(self):
        array = self.array_with((0, 0), (1, 1))
        native = [[Move(0, 0, 0, 1), Move(1, 1, 1, 2)]]
        schedule = scheduling.schedule_moves(array, native, 4, max_moves=3)
        self.assertIsNotNone(schedule.blocked_reason)
        self.assertEqual(schedule.batches, [])
        limited = scheduling.schedule_moves(array, native, 1, max_batches=1)
        self.assertEqual(len(limited.batches), 1)
        self.assertIsNotNone(limited.blocked_reason)

    def test_default_capacity_interfaces_and_bcv2_parallel_benefit(self):
        results = [run_core(algorithm="bcv2", tweezer_count=capacity) for capacity in (1, 4)]
        for result, cap in zip(results, (1, 4)):
            summary = result["summary"]
            self.assertEqual(summary["status"], "success", summary["message"])
            self.assertEqual(summary["tweezer_count"], cap)
            self.assertLessEqual(summary["max_active_tweezers"], cap)
            self.assertEqual(summary["collision_checked_batches"], summary["total_batches"])
            self.assertEqual(summary["collision_losses"], 0)
            for frame in result["frames"]:
                self.assertTrue(frame["collision_checked"])
                self.assertEqual(frame["active_tweezers"], len(frame["moves"]))
                self.assertEqual([move["tweezer_id"] for move in frame["moves"]], list(range(1, len(frame["moves"]) + 1)))
        self.assertLess(results[1]["summary"]["executed_batches"], results[0]["summary"]["executed_batches"])
        self.assertLess(results[1]["summary"]["simulated_time"], results[0]["summary"]["simulated_time"])

    def test_generalized_real_parallel_case_and_fixed_single_algorithms(self):
        result = run_core(algorithm="generalized", n=6, target_size=4, loading_prob=.8, seed=5, tweezer_count=2)
        self.assertEqual(result["summary"]["status"], "success")
        self.assertEqual(result["summary"]["max_active_tweezers"], 2)
        self.assertIn("generalized", simulator.MULTI_TWEEZER_ALGORITHMS)
        for algorithm in ("hungarian", "lbap"):
            result = run_core(algorithm=algorithm, tweezer_count=24)
            self.assertEqual(result["summary"]["tweezer_count"], 1)
            self.assertLessEqual(result["summary"]["max_active_tweezers"], 1)

    def test_pickup_failure_residue_stops_before_following_collision(self):
        class ChainAlgorithm:
            def get_moves(self, *_args, **_kwargs):
                return None, [[Move(1, 0, 1, 1), Move(1, 1, 1, 2),
                               Move(2, 0, 2, 1), Move(2, 1, 2, 2)]], True
        initial = [[0] * 4 for _ in range(4)]
        for row in (1, 2):
            initial[row][0] = initial[row][1] = 1
        with patch.dict(simulator.ALGORITHMS, {"parallel": ChainAlgorithm}):
            result = run_core(n=4, target_size=2, initial_mode="manual", initial_matrix=initial,
                              noise=True, pickup_success=0, putdown_success=100, lifetime=3600)
        summary = result["summary"]
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(len(result["frames"]), 1)
        self.assertEqual(result["frames"][0]["after"], initial)
        self.assertEqual(summary["pickup_failures"], 2)
        self.assertEqual(summary["collision_losses"], 0)
        self.assertEqual(summary["remaining"], 4)
        self.assertIn("当前占据", summary["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Focused comparison tests for fairness, metric definitions, and failures."""

import copy
import math
import unittest
from unittest.mock import patch

import comparison


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(comparison.simulator.DEFAULT_CONFIG)
        self.initial = [[1, 0, 1, 1], [1, 1, 0, 0], [0] * 4, [0] * 4]
        self.config.update(n=4, target_size=2)
        self.preview = {"config": copy.deepcopy(self.config), "initial": copy.deepcopy(self.initial),
                        "summary": {"status": "preview", "initial_count": 5, "target_count": 4, "filled": 1}}
        self.algorithms = {"parallel": object, "hungarian": object, "bcv2": object, "bc": object}
        self.simulation = {"summary": {"status": "success", "filled": 4, "target_count": 4,
                                       "executed_batches": 1, "simulated_time": 0.0001}, "frames": []}

    def test_freezes_same_initial_and_seed_without_mutating_input(self):
        original = copy.deepcopy(self.config)
        seen = []
        def simulate(config):
            seen.append(copy.deepcopy(config))
            config["initial_matrix"][0][0] = 0
            return self.simulation
        with patch.object(comparison.simulator, "ALGORITHMS", self.algorithms), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", side_effect=simulate):
            result = comparison.compare_algorithms(self.config)
        self.assertEqual(self.config, original)
        self.assertEqual(result["config"], original)
        self.assertEqual(result["config"]["initial_mode"], "random")
        self.assertEqual(result["initial_matrix"], self.initial)
        self.assertEqual(len(seen), len(self.algorithms))
        for candidate in seen:
            self.assertEqual(candidate["initial_mode"], "manual")
            self.assertEqual(candidate["initial_matrix"], self.initial)
            self.assertEqual(candidate["seed"], original["seed"])

    def test_metrics_exclude_empty_sources_zero_distance_and_all_failures(self):
        moves = [
            {"from": [0, 0], "to": [1, 1], "event": 0, "flag": 0},
            {"from": [1, 1], "to": [1, 1], "event": 0, "flag": 0},
            {"from": [0, 1], "to": [3, 1], "event": 0, "flag": 0},
            {"from": [1, 0], "to": [3, 0], "event": 1, "flag": 1},
            {"from": [0, 2], "to": [3, 2], "event": 6, "flag": 2},
            {"from": [0, 3], "to": [3, 3], "event": 2, "flag": 2},
        ]
        data = copy.deepcopy(self.simulation)
        data["frames"] = [{"before": self.initial, "moves": moves}]
        with patch.object(comparison.simulator, "ALGORITHMS", {"parallel": object}), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", return_value=data):
            result = comparison.compare_algorithms(self.config)
        row = result["rows"][0]
        self.assertEqual(row["successful_moves"], 1)
        self.assertAlmostEqual(row["successful_distance_um"], math.sqrt(2) * 5)
        self.assertAlmostEqual(row["simulated_time_us"], 100)
        self.assertEqual(row["fill_fraction"], 1)
        self.assertEqual(len(result["table_rows"][0]), len(comparison.TABLE_HEADERS))

    def test_skips_unsupported_patterns_and_keeps_other_algorithms(self):
        self.preview["config"]["pattern"] = "checkerboard"
        with patch.object(comparison.simulator, "ALGORITHMS", self.algorithms), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", return_value=self.simulation) as simulate:
            result = comparison.compare_algorithms(self.config)
        self.assertEqual(simulate.call_count, 2)
        self.assertEqual([row["status"] for row in result["rows"]], ["success", "success", "skipped", "skipped"])
        self.assertEqual(result["table_rows"][-1][3:], ["—"] * 6)

    def test_parallel_limit_and_serial_fallback_are_recorded(self):
        self.preview["config"]["tweezer_count"] = 7
        seen = []
        def simulate(config):
            seen.append(copy.deepcopy(config))
            data = copy.deepcopy(self.simulation)
            data["summary"].update(tweezer_count=config["tweezer_count"], max_active_tweezers=1)
            return data
        with patch.object(comparison.simulator, "ALGORITHMS", {"parallel": object, "hungarian": object}), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", side_effect=simulate):
            result = comparison.compare_algorithms(self.config)
        self.assertEqual([candidate["tweezer_count"] for candidate in seen], [7, 1])
        self.assertEqual([row["tweezer_count"] for row in result["rows"]], [7, 1])
        self.assertEqual([row["max_active_tweezers"] for row in result["rows"]], [1, 1])

    def test_rejects_invalid_preview_without_starting_simulations(self):
        self.preview["summary"].update(status="invalid", message="参数无效")
        with patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate") as simulate:
            result = comparison.compare_algorithms({"n": 25})
        simulate.assert_not_called()
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["message"], "参数无效")

    def test_algorithm_exception_does_not_prevent_remaining_comparison(self):
        self.preview["config"]["noise"] = True
        with patch.object(comparison.simulator, "ALGORITHMS", {"parallel": object, "hungarian": object}), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", side_effect=[RuntimeError("example"), self.simulation]):
            result = comparison.compare_algorithms(self.config)
        self.assertEqual([row["status"] for row in result["rows"]], ["algorithm_error", "success"])
        self.assertIsNone(result["rows"][0]["successful_distance_um"])
        self.assertIn("一次试验", result["footnote"])

    def test_worker_failure_before_initial_does_not_invent_zero_measurements(self):
        failed = {"summary": {"status": "algorithm_error", "target_count": 0, "filled": 0,
                               "simulated_time": 0, "losses": 0}, "initial": [], "frames": []}
        with patch.object(comparison.simulator, "ALGORITHMS", {"parallel": object}), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate", return_value=failed):
            result = comparison.compare_algorithms(self.config)
        row = result['rows'][0]
        self.assertEqual(row['target_count'], 4)
        self.assertIsNone(row['filled'])
        self.assertIsNone(row['simulated_time_us'])
        self.assertIsNone(row['losses'])

    def test_expired_deadline_reports_zero_executed_algorithms(self):
        with patch.object(comparison.simulator, "ALGORITHMS", {"parallel": object}), \
             patch.object(comparison.simulator, "preview", return_value=self.preview), \
             patch.object(comparison.simulator, "simulate") as simulate:
            result = comparison.compare_algorithms(self.config, deadline=0)
        simulate.assert_not_called()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['rows'][0]['status'], 'not_run')
        self.assertIn('0 种', result['message'])


if __name__ == "__main__":
    unittest.main()

import copy
import csv
import json
import tempfile
import unittest
from unittest.mock import patch

import benchmark
import simulator


def sample(status, filled, duration, losses=0):
    return {'key': 'parallel', 'algorithm': '并行 Hungarian', 'status': status, 'status_text': status,
            'filled': filled, 'target_count': 4, 'fill_fraction': None if filled is None else filled / 4,
            'simulated_time_us': duration, 'losses': losses, 'tweezer_count': 4}


class BenchmarkTests(unittest.TestCase):
    def test_denominator_includes_insufficient_blocked_errors(self):
        records = [sample('success', 4, 100), sample('insufficient', 2, 0),
                   sample('blocked', 3, 20, 1), sample('algorithm_error', None, None, None)]
        row = benchmark.aggregate(records)[0]
        self.assertEqual(row[1:4], [4, '1/4 (25.0%)', '75.0%（有效 3/4）'])
        self.assertEqual(row[5:], [100, 1, '1 / 1 / 1'])
        self.assertIn('有效 3/4', row[4])

    def test_physical_success_uses_fill_even_with_native_failure_status(self):
        row = benchmark.aggregate([sample('blocked', 4, 80)])[0]
        self.assertEqual(row[2], '1/1 (100.0%)')
        self.assertEqual(row[-1], '0 / 0 / 0')

    def test_seeds_wrap_and_manual_initial_never_mutates(self):
        config = dict(simulator.DEFAULT_CONFIG, seed=2**32-1, n=4, target_size=2, initial_mode='manual', initial_matrix=[[1]*4 for _ in range(4)])
        before = copy.deepcopy(config)
        seen = []
        def compare(cfg, **kwargs):
            seen.append(copy.deepcopy(cfg))
            cfg['initial_matrix'][0][0] = 0
            return {'status':'complete', 'rows':[sample('success', 4, 10)]}
        with patch.object(benchmark, 'compare_algorithms', side_effect=compare):
            result = benchmark.benchmark_algorithms(config, 3)
        self.assertEqual([r['seed'] for r in seen], [2**32-1, 0, 1])
        self.assertTrue(all(r['initial_matrix'] == before['initial_matrix'] for r in seen))
        self.assertEqual(config, before)
        self.assertEqual(result['rows'][0][1], 3)

    def test_invalid_repetitions_do_not_run(self):
        for trials in [False, 0, 21, float('nan'), 1.5, '2', 10**1000]:
            with patch.object(benchmark, 'compare_algorithms') as compare:
                result = benchmark.benchmark_algorithms(simulator.DEFAULT_CONFIG, trials)
            self.assertEqual(result['status'], 'invalid')
            compare.assert_not_called()

    def test_partial_deadline_preserves_results_excludes_unexecuted(self):
        with patch.object(benchmark, 'compare_algorithms', return_value={'status':'partial', 'rows':[
            sample('success', 4, 100), dict(sample('not_run', None, None), key='hungarian')]}):
            result = benchmark.benchmark_algorithms(simulator.DEFAULT_CONFIG, 5)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['rows'][0][1], 1)
        self.assertEqual(result['rows'][1][1], 0)
        self.assertIn('样本数可能不同', result['message'])

    def test_csv_contains_each_trial_seed_and_reproducible_config(self):
        result = {'config': simulator.DEFAULT_CONFIG, 'records':[dict(sample('success', 4, 100), seed=43, trial=2)]}
        with tempfile.TemporaryDirectory() as directory:
            path = benchmark.export_csv(result, directory)
            with open(path, encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['seed'], '43')
        cfg = json.loads(rows[0]['config_json'])
        self.assertEqual(cfg['seed'], 43)
        self.assertEqual(cfg['algorithm'], 'parallel')
        self.assertEqual(cfg['pickup_time_us'], 0)

    def test_random_trials_use_matching_initials_across_algorithms(self):
        configs = []
        def simulate(config):
            configs.append(copy.deepcopy(config))
            return {'summary': {'status':'success', 'target_count':4, 'filled':4, 'simulated_time':0, 'losses':0}, 'frames':[]}
        with patch.object(simulator, 'simulate', side_effect=simulate):
            result = benchmark.benchmark_algorithms(dict(simulator.DEFAULT_CONFIG, n=4, target_size=2), 2)
        self.assertEqual(len(configs), 12)
        self.assertTrue(all(c['initial_matrix'] == configs[0]['initial_matrix'] for c in configs[:6]))
        self.assertTrue(all(c['initial_matrix'] == configs[6]['initial_matrix'] for c in configs[6:]))
        self.assertNotEqual(configs[0]['initial_matrix'], configs[6]['initial_matrix'])
        self.assertEqual([r['seed'] for r in result['records']], [42]*6+[43]*6)


if __name__ == '__main__':
    unittest.main()

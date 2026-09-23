import json
from pathlib import Path
import unittest

from cost_router.core import bill, load_trace, route, normalize

ROOT = Path(__file__).resolve().parents[1]


def row(**overrides):
    d = dict(id='a', model='gpt-6-sol', input_tokens=10000,
             cached_input_tokens=6000, cache_write_input_tokens=2000,
             output_tokens=1000, reasoning_output_tokens=400,
             cache_write_ttl='5m', tool_cost_usd='0', kind='extract')
    d.update(overrides)
    return normalize(d)


class BillingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices = json.loads((ROOT / 'prices/2026-09-24.json').read_text())

    def test_handworked_cache_and_reasoning(self):
        b = bill([row()], self.prices, 'gpt-6-sol')
        self.assertEqual(b['total_usd'], '0.0202')
        self.assertEqual(b['rounds'][0]['charges_usd'], dict(input='0.004', cached_input='0.0012', cache_write_input='0.005', output='0.006', reasoning_output='0.004', tools='0'))

    def test_handworked_retry(self):
        rows = [row(id='failure', status='failed'), row(id='retry', retry=True)]
        b = bill(rows, self.prices, 'gpt-6-sol')
        self.assertEqual(b['total_usd'], '0.0404')
        self.assertEqual(b['charges_usd'], dict(input='0.008', cached_input='0.0024', cache_write_input='0.01', output='0.012', reasoning_output='0.008', tools='0'))

    def test_handworked_fast_double(self):
        self.assertEqual(bill([row()], self.prices, 'claude-opus-5-5')['total_usd'], '0.0392')
        self.assertEqual(bill([row()], self.prices, 'claude-opus-5-5:fast')['total_usd'], '0.0784')

    def test_handworked_long_context(self):
        r = row(input_tokens=300000, cached_input_tokens=200000, cache_write_input_tokens=50000, output_tokens=10000, reasoning_output_tokens=4000)
        b = bill([r], self.prices, 'gpt-6-sol')
        self.assertEqual(b['total_usd'], '0.68')
        self.assertEqual(b['charges_usd'], dict(input='0.2', cached_input='0.08', cache_write_input='0.25', output='0.09', reasoning_output='0.06', tools='0'))

    def test_long_boundary(self):
        for n, expected in [(272000, '0.544'), (272001, '1.088004')]:
            r = row(input_tokens=n, cached_input_tokens=0, cache_write_input_tokens=0, output_tokens=0, reasoning_output_tokens=0)
            self.assertEqual(bill([r], self.prices, 'gpt-6-sol')['total_usd'], expected)

    def test_one_hour_write(self):
        b = bill([row(cache_write_ttl='1h')], self.prices, 'claude-opus-5-5')
        self.assertEqual(b['total_usd'], '0.0452')
        self.assertEqual(b['charges_usd'], dict(input='0.008', cached_input='0.0012', cache_write_input='0.016', output='0.012', reasoning_output='0.008', tools='0'))
        self.assertEqual(bill([row(cache_write_ttl='1h')], self.prices, 'gpt-6-sol')['total_usd'], 'unknown')

    def test_missing_tools_not_zero(self):
        self.assertEqual(bill([row(tool_cost_usd=None)], self.prices, 'gpt-6-sol')['total_usd'], 'unknown')

    def test_missing_cache_is_not_zero(self):
        r = row(cache_write_input_tokens=None)
        b = bill([r], self.prices, 'gpt-6-sol')
        self.assertEqual(b['total_usd'], 'unknown')
        self.assertIn('cache_write_input_tokens', ' '.join(b['unknown']))

    def test_missing_reasoning_still_bills_inclusive_output(self):
        b = bill([row(reasoning_output_tokens=None)], self.prices, 'gpt-6-sol')
        self.assertEqual(b['total_usd'], '0.0202')
        self.assertEqual(b['rounds'][0]['charges_usd']['reasoning_output'], 'included_in_output')

    def test_aggregate_context_not_inferred_from_sum(self):
        r = row(granularity='aggregate')
        self.assertEqual(bill([r], self.prices, 'gpt-6-sol')['total_usd'], 'unknown')
        self.assertEqual(bill([r], self.prices, 'claude-opus-5-5')['total_usd'], '0.0392')

    def test_invalid_counts(self):
        for kwargs in [dict(input_tokens=-1), dict(input_tokens=1), dict(reasoning_output_tokens=1001), dict(output_tokens=1.5), dict(retry='maybe')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                row(**kwargs)

    def test_unknown_model(self):
        self.assertEqual(bill([row()], self.prices, 'claude-sonnet-5-5')['total_usd'], 'unknown')

    def test_exclusive_generic_input(self):
        r = row(input_tokens=2000, input_semantics='exclusive')
        self.assertEqual(bill([r], self.prices, 'gpt-6-sol')['total_usd'], '0.0202')

    def test_route_no_quality_claim(self):
        r = route([row()], self.prices, 'latency<=30s,quality>=baseline')
        self.assertEqual(r['strategy'][0]['selected'], 'gpt-6-sol')
        self.assertEqual(r['strategy'][0]['scenario'], 'gpt-6-luna')
        self.assertEqual(r['strategy'][0]['scenario_savings_usd'], '0.01919')
        self.assertEqual(r['slo_status'], 'unknown')

    def test_route_evidence_and_deadline(self):
        e = {'gpt-6-luna': {'quality_vs_baseline': 1, 'latency_seconds': 3, 'source': 'fixture-eval', 'kind': 'extract'}}
        r = route([row(evidence=e)], self.prices, 'latency<=5s,quality>=baseline')
        self.assertEqual(r['strategy'][0]['selected'], 'gpt-6-luna')
        self.assertEqual(r['savings_usd'], '0.01919')
        self.assertEqual(r['slo_status'], 'supported_by_supplied_evidence')
        r = route([row(evidence=e), row(id='b', evidence=e)], self.prices, 'latency<=5s,quality>=baseline')
        self.assertNotEqual(r['slo_status'], 'supported_by_supplied_evidence')

    def test_fast_only_with_evidence(self):
        e = {'claude-opus-5-5:fast': {'quality_vs_baseline': 1, 'latency_seconds': 1, 'source': 'fixture-eval', 'kind': 'extract'}}
        r = route([row(model='claude-opus-5-5', evidence=e)], self.prices, 'latency<=2s,quality>=baseline')
        self.assertEqual(r['strategy'][0]['selected'], 'claude-opus-5-5:fast')
        self.assertEqual(r['savings_usd'], '-0.0392')

    def test_per_round_limits(self):
        e = {'gpt-6-luna': {'quality_vs_baseline': 1, 'latency_seconds': 3, 'source': 'fixture-eval', 'kind': 'extract'}}
        for constraint in [dict(latency_limit_seconds=2), dict(quality_min_ratio='1.1')]:
            result = route([row(evidence=e, **constraint)], self.prices, 'latency<=30s,quality>=baseline')
            self.assertEqual(result['strategy'][0]['selected'], 'gpt-6-sol')

    def test_failed_without_usage_makes_total_unknown(self):
        rows = load_trace(ROOT / 'tests/fixtures/exec.jsonl')
        self.assertEqual(bill(rows, self.prices, 'claude-opus-5-5')['total_usd'], 'unknown')

    def test_fast_cache_each_component_doubles(self):
        standard = bill([row()], self.prices, 'claude-opus-5-5')['rounds'][0]['charges_usd']
        fast = bill([row()], self.prices, 'claude-opus-5-5:fast')['rounds'][0]['charges_usd']
        from decimal import Decimal
        for k, v in standard.items():
            self.assertEqual(Decimal(fast[k]), 2 * Decimal(v))

    def test_global_route_chooses_feasible_combination(self):
        e = {
            'gpt-6-luna': {'quality_vs_baseline': 1, 'latency_seconds': 4, 'source': 'fixture', 'kind': 'extract'},
            'gpt-6-sol': {'quality_vs_baseline': 1, 'latency_seconds': 1, 'source': 'fixture', 'kind': 'extract'}}
        result = route([row(evidence=e), row(id='b', evidence=e)], self.prices, 'latency<=5s,quality>=baseline')
        self.assertEqual(result['routed_total_usd'], '0.02121')
        self.assertEqual(result['latency_seconds'], '5')

    def test_evidence_for_wrong_kind_rejected(self):
        e = {'gpt-6-luna': {'quality_vs_baseline': 1, 'latency_seconds': 1, 'source': 'fixture', 'kind': 'review'}}
        result = route([row(evidence=e)], self.prices, 'latency<=30s,quality>=baseline')
        self.assertEqual(result['strategy'][0]['selected'], 'gpt-6-sol')

    def test_unknown_cache_ttl(self):
        self.assertEqual(bill([row(cache_write_ttl='unknown')], self.prices, 'claude-opus-5-5')['total_usd'], 'unknown')

    def test_context_capacity(self):
        self.assertEqual(bill([row(input_tokens=1100000)], self.prices, 'gpt-6-sol')['total_usd'], 'unknown')

    def test_bad_slo_rejected(self):
        with self.assertRaises(ValueError):
            route([row()], self.prices, 'latency<=Ns,quality>=baseline')

    def test_price_provenance(self):
        for m in self.prices['models'].values():
            for rates in m['rates'].values():
                for f in rates.values():
                    self.assertTrue(f['source_url'].startswith('https://'))
                    self.assertIn('T', f['fetched_at'])


class ImportTests(unittest.TestCase):
    def test_exec_retry_and_no_usage_failure(self):
        rows = load_trace(ROOT / 'tests/fixtures/exec.jsonl')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['granularity'], 'aggregate')
        self.assertTrue(rows[1]['retry'])
        self.assertIsNone(rows[2]['input_tokens'])

    def test_csv_matches_jsonl(self):
        self.assertEqual(load_trace(ROOT / 'samples/synthetic.csv'), load_trace(ROOT / 'samples/synthetic.jsonl'))

    def test_real_sample_import(self):
        rows = load_trace(ROOT / 'samples/local-usage.jsonl')
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]['input_tokens'], 24286)
        self.assertEqual(rows[0]['cached_input_tokens'], 12928)
        self.assertEqual(rows[0]['model'], 'gpt-6-astra')

    def test_native_duplicate_not_billed_twice(self):
        rows = load_trace(ROOT / 'tests/fixtures/native-duplicate.jsonl')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['input_tokens'], 100)

    def test_cumulative_deltas_not_double_counted(self):
        rows = load_trace(ROOT / 'tests/fixtures/cumulative.jsonl')
        self.assertEqual([r['input_tokens'] for r in rows], [100, 150])
        self.assertEqual([r['output_tokens'] for r in rows], [10, 20])

    def test_malformed_line_rejected(self):
        with self.assertRaisesRegex(ValueError, 'malformed.jsonl:1'):
            load_trace(ROOT / 'tests/fixtures/malformed.jsonl')

    def test_empty_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no usage'):
            load_trace(ROOT / 'tests/fixtures/empty.jsonl')


if __name__ == '__main__':
    unittest.main()

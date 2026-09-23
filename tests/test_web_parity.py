"""One cross-runtime contract test: same inputs, full Python and JS output."""
import json
from pathlib import Path
import subprocess
import unittest
from cost_router.core import bill, load_trace, normalize, route

ROOT = Path(__file__).resolve().parents[1]

class WebParityTests(unittest.TestCase):
    def test_python_javascript_parity(self):
        prices = json.loads((ROOT / 'prices/2026-09-24.json').read_text())
        cases = []
        for path in [ROOT / 'samples/synthetic.jsonl', ROOT / 'samples/synthetic.csv',
                     ROOT / 'samples/local-usage.jsonl', ROOT / 'samples/fleet-import.snapshot.jsonl',
                     *sorted((ROOT / 'tests/fixtures').glob('*.jsonl'))]:
            case = {'text': path.read_text(), 'format': path.suffix[1:]}
            try:
                rows = load_trace(path)
                case['expected'] = {'rows': rows, 'bills': [bill(rows, prices, m) for m in prices['models']],
                                    'route': route(rows, prices, 'latency<=30s,quality>=baseline')}
            except ValueError:
                case['error'] = True
            cases.append(case)
        base = json.loads((ROOT / 'samples/synthetic.jsonl').read_text().splitlines()[0])
        evidence = {'gpt-6-luna': {'quality_vs_baseline': 1, 'latency_seconds': 4, 'source': 'fixture', 'kind': 'extract'},
                    'gpt-6-sol': {'quality_vs_baseline': 1, 'latency_seconds': 1, 'source': 'fixture', 'kind': 'extract'}}
        for overrides in [{'input_tokens': 300000}, {'cache_write_ttl': '1h'}, {'cache_write_ttl': 'unknown'},
                          {'reasoning_output_tokens': None}, {'tool_cost_usd': None}, {'cached_input_tokens': None},
                          {'input_tokens': 1100000}, {'evidence': evidence}, {'granularity': 'aggregate'},
                          {'input_tokens': 2000, 'input_semantics': 'exclusive'}, {'input_tokens': -1}]:
            raw = dict(base, **overrides)
            case = {'text': json.dumps(raw), 'format': 'jsonl'}
            try:
                rows = [normalize(raw)]
                case['expected'] = {'rows': rows, 'bills': [bill(rows, prices, m) for m in prices['models']],
                                    'route': route(rows, prices, 'latency<=30s,quality>=baseline')}
            except ValueError:
                case['error'] = True
            cases.append(case)
        js = """
const fs=require('node:fs'), assert=require('node:assert/strict'), vm=require('node:vm');
const C=require('./web/calc.js'), {prices,cases}=JSON.parse(fs.readFileSync(0,'utf8'));
for (const c of cases) {
  if (c.error) { assert.throws(()=>C.loadTrace(c.text,c.format)); continue; }
  const rows=C.loadTrace(c.text,c.format);
  assert.deepEqual({rows,bills:Object.keys(prices.models).map(m=>C.bill(rows,prices,m)),route:C.route(rows,prices)},c.expected);
}
const bundle={window:{}}; vm.runInNewContext(fs.readFileSync('web/data.js','utf8'),bundle);
assert.equal(JSON.stringify(bundle.window.COST_PRICES),JSON.stringify(prices));
assert.equal(bundle.window.COST_SAMPLE,fs.readFileSync('samples/synthetic.jsonl','utf8'));
console.log('calc_parity=pass cases='+cases.length);
"""
        result = subprocess.run(['node', '-e', js], input=json.dumps({'prices': prices, 'cases': cases}),
                                text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('calc_parity=pass', result.stdout)

if __name__ == '__main__':
    unittest.main()

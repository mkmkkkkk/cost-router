"""Independent arithmetic receipt check: deliberately does not import cost_router."""
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rates = {
    'gpt-6-sol': ('2', '.2', '2.5', '10'),
    'gpt-6-luna': ('.1', '.01', '.125', '.5'),
    'claude-opus-5-5': ('4', '.2', '5', '20'),
    'claude-opus-5-5:fast': ('8', '.4', '10', '40'),
}
checks = 0
for stem, source in [('synthetic', 'samples/synthetic.jsonl'), ('real', 'samples/local-usage.jsonl'), ('fleet', 'samples/fleet-import.snapshot.jsonl')]:
    events = [json.loads(x) for x in (root / source).read_text().splitlines()]
    usages = events if stem == 'synthetic' else [e['payload']['usage'] for e in events if e['type'] == 'token_usage_record']
    if stem == 'fleet':
        usages = [e['usage'] for e in events]
    receipt = json.loads((root / f'receipts/{stem}-bill.json').read_text())
    for model, strings in rates.items():
        if stem == 'fleet' and model.startswith('gpt'):
            assert receipt[model]['total_usd'] == 'unknown'
            assert receipt[model]['rounds'][0]['tier'] == 'unknown'
            print(f'fleet {model} total=unknown aggregate_context_boundary_missing')
            continue
        subtotal = D(0)
        assert len(usages) == len(receipt[model]['rounds'])
        for u, billed in zip(usages, receipt[model]['rounds']):
            inp, cache, write, out = map(D, strings)
            if model.startswith('gpt') and u['input_tokens'] > 272000:
                inp *= 2; cache *= 2; write *= 2; out *= D('1.5')
            i, c, w, o, q = [u[k] for k in ['input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens', 'reasoning_output_tokens']]
            values = dict(input=(i-c-w)*inp/D(1000000), cached_input=c*cache/D(1000000),
                          cache_write_input=w*write/D(1000000), output=(o-q)*out/D(1000000), reasoning_output=q*out/D(1000000))
            for key, value in values.items():
                assert D(billed['charges_usd'][key]) == value, (stem, model, key)
                checks += 1
            subtotal += sum(values.values())
        assert D(receipt[model]['known_subtotal_usd']) == subtotal
        assert receipt[model]['total_usd'] == 'unknown' if stem != 'synthetic' else D(receipt[model]['total_usd']) == subtotal
        print(f'{stem} {model} rounds={len(usages)} independently_recomputed_usd={subtotal} total={receipt[model]["total_usd"]}')
for file in ['README.md', 'prices/2026-09-24.json', 'samples/local-usage.jsonl', 'docs/handworked.md', 'receipts/tests-green.txt']:
    data = (root / file).read_bytes()
    assert data
    print(f'readback {file} bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}')
print(f'INDEPENDENT_CHECK_OK item_assertions={checks}')

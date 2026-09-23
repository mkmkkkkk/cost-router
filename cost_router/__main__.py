import argparse
import json
import sys
from pathlib import Path
from .core import bill, load_trace, price_stats, route


def main():
    parser = argparse.ArgumentParser(description='Offline agent trace billing and explainable routing')
    parser.add_argument('command', choices=['bill', 'route'])
    parser.add_argument('trace', type=Path)
    parser.add_argument('--prices', type=Path, default=Path(__file__).resolve().parents[1] / 'prices/2026-09-24.json')
    parser.add_argument('--models', default='all', help='all, original, or comma-separated model IDs')
    parser.add_argument('--slo', default='latency<=30s,quality>=baseline')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        prices = json.loads(args.prices.read_text())
        rows = load_trace(args.trace)
        if args.command == 'bill':
            models = list(prices['models']) if args.models == 'all' else args.models.split(',')
            result = {m: bill(rows, prices, m) for m in models}
        else:
            result = route(rows, prices, args.slo)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'error: {exc}\n')
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    k, total = price_stats(prices)
    print(f"snapshot={prices['snapshot_date']} models={len(prices['models'])} price_fields_known={k}/{total} rows={len(rows)}")
    if args.command == 'bill':
        print('USD ' + ' | '.join(f"{m}={b['total_usd']} (known={b['known_subtotal_usd']})" for m, b in result.items()))
        for m, b in result.items():
            for r in b['rounds']:
                items = ' '.join(f'{k}={v}' for k, v in r['charges_usd'].items())
                print(f"{m} {r['id']} tier={r['tier']} retry={r['retry']} status={r['status']} {items} total={r['total_usd']}")
            print(f"unknown[{m}]: " + ('; '.join(b['unknown']) or 'none'))
        print('assumption: same token counts/cache/retries; API cost scenarios, not subscription invoices')
    else:
        for s in result['strategy']:
            print(f"{s['id']} [{s['kind']}] {s['selected']}: {s['reason']}; scenario={s['scenario']} scenario_savings_usd={s['scenario_savings_usd']} (cost only)")
        print(f"baseline={result['baseline_total_usd']} routed={result['routed_total_usd']} savings_usd={result['savings_usd']} slo={result['slo_status']} latency_seconds={result['latency_seconds']}")
        print('unknown: ' + ('; '.join(result['unknown']) or 'none'))
        print('assumption: sequential task; supplied evidence; fixed tokens/cache/retries; cache invalidation not measured')


if __name__ == '__main__':
    main()

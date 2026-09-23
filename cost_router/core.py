"""Offline, Decimal-based task repricing. No network or model calls."""
import csv
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

UNKNOWN = 'unknown'
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
PRICE_FIELDS = ('input', 'cached_input', 'cache_write_input', 'cache_write_1h_input',
                'output', 'reasoning_output')


def money(value):
    return format(value.normalize(), 'f') if value else '0'


def number(value):
    if value is None or value == '' or value == UNKNOWN:
        return None
    if isinstance(value, bool):
        raise ValueError('boolean is not a number')
    try:
        n = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'invalid number: {value}') from exc
    if not n.is_finite() or n < 0:
        raise ValueError('numbers must be finite and nonnegative')
    return n


def boolean(value):
    if value in (None, '', UNKNOWN):
        return None
    if value is True or value == 'true':
        return True
    if value is False or value == 'false':
        return False
    raise ValueError('retry must be true, false or unknown')


def normalize(raw):
    r = dict(raw)
    for key in TOKEN_FIELDS:
        n = number(r.get(key))
        if n is not None and n != n.to_integral_value():
            raise ValueError(f'{key} must be an integer')
        r[key] = int(n) if n is not None else None
    r['id'] = str(r.get('id', 'unknown'))
    r['model'] = r.get('model') or UNKNOWN
    mode = r.get('mode') or 'standard'
    if mode not in ('standard', 'fast', UNKNOWN):
        raise ValueError('mode must be standard, fast or unknown')
    if mode == 'fast' and ':' not in r['model']:
        r['model'] += ':fast'
    elif mode == UNKNOWN and ':' not in r['model']:
        r['model'] += ':unknown'
    r.pop('mode', None)
    r['retry'] = boolean(r.get('retry'))
    for field in ('latency_limit_seconds', 'quality_min_ratio'):
        n = number(r.get(field))
        r[field] = money(n) if n is not None else None
    r['status'] = r.get('status') or UNKNOWN
    r['kind'] = r.get('kind') or UNKNOWN
    r['granularity'] = r.get('granularity') or 'request'
    if r['granularity'] not in ('request', 'aggregate'):
        raise ValueError('granularity must be request or aggregate')
    semantics = r.pop('input_semantics', 'inclusive') or 'inclusive'
    if semantics not in ('inclusive', 'exclusive'):
        raise ValueError('input_semantics must be inclusive or exclusive')
    i, c, w = (r[k] for k in TOKEN_FIELDS[:3])
    if semantics == 'exclusive':
        r['input_tokens'] = i + c + w if None not in (i, c, w) else None
        i = r['input_tokens']
    if i is not None and sum(v or 0 for v in (c, w)) > i:
        raise ValueError('cache reads + writes exceed inclusive input')
    o, q = r['output_tokens'], r['reasoning_output_tokens']
    if o is not None and q is not None and q > o:
        raise ValueError('reasoning_output_tokens exceeds inclusive output_tokens')
    r['cache_write_ttl'] = r.get('cache_write_ttl') or UNKNOWN
    if r['cache_write_ttl'] not in ('5m', '1h', 'provider_default', UNKNOWN):
        raise ValueError('unsupported cache_write_ttl')
    for field in ('tool_cost_usd', 'evidence'):
        value = r.get(field)
        if isinstance(value, str) and value.startswith('{'):
            value = json.loads(value)
        if field == 'tool_cost_usd':
            if isinstance(value, dict):
                value = {k: money(n) if (n := number(v)) is not None else None for k, v in value.items()}
            else:
                n = number(value)
                value = money(n) if n is not None else None
        else:
            value = value or {}
            if not isinstance(value, dict):
                raise ValueError('evidence must be an object')
        r[field] = value
    return r


def load_trace(path):
    """Prefer request records over duplicate cumulative usage in native sessions."""
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as f:
            events = list(csv.DictReader(f))
    else:
        events = []
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip():
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError('record must be an object')
                    events.append(event)
                except ValueError as exc:
                    raise ValueError(f'{path.name}:{line_no}: {exc}') from exc
    has_records = any(e.get('type') == 'token_usage_record' for e in events)
    model = UNKNOWN
    mode = 'standard'
    session = 'unknown'
    rows, seen = [], {}
    previous_total = None
    for pos, e in enumerate(events, 1):
        t, p = e.get('type'), e.get('payload', {})
        if t == 'session_meta':
            session = p.get('id', 'unknown')
            previous_total = None
        if t == 'turn_context':
            model = p.get('model', UNKNOWN)
            mode = p.get('mode', p.get('speed', 'standard'))
        raw = None
        if t == 'token_usage_record':
            key = (p.get('session_id', session), p.get('response_id', f'line-{pos}'))
            if key in seen:
                if seen[key] != p.get('usage'):
                    raise ValueError('conflicting duplicate response usage')
                continue
            seen[key] = p.get('usage')
            raw = dict(p.get('usage') or {}, id=f'{key[0]}:{key[1]}',
                       model=p.get('model', model), mode=p.get('mode', mode), granularity='request')
        elif t in ('turn.completed', 'turn.failed') and not has_records:
            raw = dict(e.get('usage') or {}, id=e.get('turn_id', f'line-{pos}'),
                       model=e.get('model', model), mode=e.get('mode', mode),
                       retry=e.get('retry'), status='failed' if t == 'turn.failed' else 'completed',
                       granularity=e.get('granularity', 'aggregate'))
            for k in ('cache_write_ttl', 'tool_cost_usd', 'kind', 'evidence'):
                if k in e:
                    raw[k] = e[k]
        elif t == 'event_msg' and p.get('type') == 'token_count' and not has_records:
            info = p.get('info') or {}
            total = info.get('total_token_usage')
            if total:
                if total == previous_total:
                    continue
                delta = {}
                for k in TOKEN_FIELDS:
                    current, prior = total.get(k), (previous_total or {}).get(k, 0)
                    delta[k] = current - prior if current is not None and prior is not None else None
                    if delta[k] is not None and delta[k] < 0:
                        raise ValueError('cumulative usage reset; split sessions before importing')
                previous_total = total
                raw = dict(delta, id=f'line-{pos}', model=model, mode=mode, granularity='aggregate')
        elif not t:
            raw = dict(e)
            raw.setdefault('id', f'line-{pos}')
        if raw is not None:
            rows.append(normalize(raw))
    if not rows:
        raise ValueError('no usage records found; empty traces cannot mean zero cost')
    return rows


def price_stats(prices):
    fields = [f for m in prices['models'].values() for r in m['rates'].values() for f in r.values()]
    return sum(f['value'] != UNKNOWN for f in fields), len(fields)


def bill_round(r, prices, target):
    unknown, notes, charges = [], [], {}
    m = prices['models'].get(target)
    tier = UNKNOWN
    if m:
        if m['long_context_threshold']['value'] is None:
            tier = 'short'
        elif r['granularity'] == 'aggregate':
            unknown.append('context: aggregate usage lacks per-request context lengths')
        elif r['input_tokens'] is None:
            unknown.append('context: input_tokens unknown')
        else:
            tier = 'long' if r['input_tokens'] > m['long_context_threshold']['value'] else 'short'
        if r['granularity'] == 'request' and r['input_tokens'] is not None and r['output_tokens'] is not None:
            if r['input_tokens'] + r['output_tokens'] > m['context_window']['value']:
                unknown.append('context_window: trace exceeds supported context; replay infeasible')
    else:
        unknown.append(f'model price: {target}')
    rates = m['rates'][tier] if m and tier != UNKNOWN else {}

    def charge(label, count, price_field):
        rate = rates.get(price_field, {}).get('value', UNKNOWN)
        if count == 0:
            charges[label] = '0'
        elif count is None or rate == UNKNOWN:
            charges[label] = UNKNOWN
            unknown.append(f'{label}: usage or {price_field} price unknown')
        else:
            charges[label] = money(Decimal(count) * Decimal(rate) / Decimal(1000000))

    i, c, w, o, q = (r[k] for k in TOKEN_FIELDS)
    if c is None:
        unknown.append('cached_input_tokens')
    if w is None:
        unknown.append('cache_write_input_tokens')
    ordinary = i - c - w if None not in (i, c, w) else None
    charge('input', ordinary, 'input')
    charge('cached_input', c, 'cached_input')
    write_field = 'cache_write_1h_input' if r['cache_write_ttl'] == '1h' else 'cache_write_input'
    if w and m and m['provider'] == 'anthropic' and r['cache_write_ttl'] not in ('5m', '1h'):
        charge('cache_write_input', None, write_field)
        unknown.append('cache_write_ttl: Anthropic needs 5m or 1h')
    else:
        charge('cache_write_input', w, write_field)
    if q is None:
        charge('output', o, 'output')
        charges['reasoning_output'] = 'included_in_output'
        notes.append('reasoning split unknown; inclusive output charged once')
    else:
        charge('output', o - q if o is not None else None, 'output')
        charge('reasoning_output', q, 'reasoning_output')
    tool = r['tool_cost_usd']
    if isinstance(tool, dict):
        tool = tool.get(target)
    charges['tools'] = tool if tool is not None else UNKNOWN
    if tool is None:
        unknown.append('tools: fee inventory/cost missing')
    subtotal = sum((Decimal(v) for v in charges.values() if v not in (UNKNOWN, 'included_in_output')), Decimal(0))
    return dict(id=r['id'], original_model=r['model'], model=target, kind=r['kind'],
                retry=r['retry'], status=r['status'], tier=tier, usage={k:r[k] for k in TOKEN_FIELDS},
                rates_usd_per_million={k:v['value'] for k,v in rates.items()},
                charges_usd=charges, known_subtotal_usd=money(subtotal),
                total_usd=UNKNOWN if unknown else money(subtotal), unknown=unknown, notes=notes)


def bill(rows, prices, target='original'):
    rounds = [bill_round(r, prices, r['model'] if target == 'original' else target) for r in rows]
    unknown = [f"{r['id']}: {u}" for r in rounds for u in r['unknown']]
    subtotal = sum((Decimal(r['known_subtotal_usd']) for r in rounds), Decimal(0))
    items = {}
    for label in ('input', 'cached_input', 'cache_write_input', 'output', 'reasoning_output', 'tools'):
        values = [r['charges_usd'][label] for r in rounds]
        items[label] = UNKNOWN if UNKNOWN in values else (
            'included_in_output' if 'included_in_output' in values else money(sum(map(Decimal, values), Decimal(0))))
    return dict(model=target, currency='USD', scope='direct API global token replay; not subscription charges',
                assumptions=['same recorded token counts, cache hits and attempts across models; counterfactual only'],
                rounds=rounds, charges_usd=items, known_subtotal_usd=money(subtotal),
                total_usd=UNKNOWN if unknown else money(subtotal), unknown=unknown)


def route(rows, prices, slo):
    match = re.fullmatch(r'latency<=([0-9]+(?:\.[0-9]+)?)s,quality>=baseline', slo.replace(' ', ''))
    if not match or Decimal(match[1]) <= 0:
        raise ValueError('SLO format: latency<=30s,quality>=baseline (task-wide sequential latency)')
    deadline = Decimal(match[1])
    baseline = bill(rows, prices, 'original')
    strategies, options = [], []
    for r in rows:
        costs = {m: bill_round(r, prices, m) for m in prices['models']}
        complete = {m: Decimal(b['total_usd']) for m, b in costs.items() if b['total_usd'] != UNKNOWN}
        cheapest = min(complete, key=lambda m: (complete[m], m)) if complete else UNKNOWN
        orig = bill_round(r, prices, r['model'])['total_usd']
        eligible = []
        for m, cost in complete.items():
            evidence = r['evidence'].get(m, {})
            if not isinstance(evidence, dict):
                raise ValueError('model evidence must be an object')
            q = number(evidence.get('quality_vs_baseline'))
            latency = number(evidence.get('latency_seconds'))
            quality_floor = max(Decimal(1), number(r['quality_min_ratio']) or Decimal(1))
            limit = number(r['latency_limit_seconds'])
            if (q is not None and q >= quality_floor and latency is not None
                    and (limit is None or latency <= limit) and evidence.get('source')
                    and evidence.get('kind') == r['kind'] and r['kind'] != UNKNOWN):
                eligible.append((m, cost, latency, evidence['source']))
        options.append(eligible)
        strategies.append(dict(id=r['id'], kind=r['kind'], selected=r['model'],
                               reason='retain original: no task-feasible quality and latency evidence',
                               scenario=cheapest,
                               scenario_savings_usd=money(Decimal(orig)-complete[cheapest]) if orig != UNKNOWN and cheapest != UNKNOWN else UNKNOWN,
                               scenario_note='cost scenario only; does not establish safe downgrade'))
    # Pareto frontier over total latency and cost; every failed/retry attempt participates.
    frontier = [(Decimal(0), Decimal(0), [])]
    for candidates in options:
        expanded = [(lat + l, cost + c, path + [(m, source)])
                    for lat, cost, path in frontier for m, c, l, source in candidates if lat+l <= deadline]
        frontier, best_cost = [], None
        for state in sorted(expanded, key=lambda s: (s[0], s[1])):
            if best_cost is None or state[1] < best_cost:
                frontier.append(state)
                best_cost = state[1]
    total_latency = UNKNOWN
    if frontier:
        lat, _, path = min(frontier, key=lambda s: (s[1], s[0]))
        total_latency = money(lat)
        for s, (m, source) in zip(strategies, path):
            s.update(selected=m, reason=f'lowest total cost meeting task SLO in supplied evidence: {source}')
    selected_rounds = [bill_round(r, prices, s['selected']) for r, s in zip(rows, strategies)]
    totals = [r['total_usd'] for r in selected_rounds]
    selected_total = UNKNOWN if UNKNOWN in totals else money(sum(map(Decimal, totals), Decimal(0)))
    savings = money(Decimal(baseline['total_usd']) - Decimal(selected_total)) if UNKNOWN not in (baseline['total_usd'], selected_total) else UNKNOWN
    unknown = sorted(set(u for r in selected_rounds for u in r['unknown']))
    if not frontier:
        unknown.append('quality/latency: no evidence-backed complete route within task deadline')
    return dict(slo=slo, slo_status='supported_by_supplied_evidence' if frontier else UNKNOWN,
                latency_seconds=total_latency, strategy=strategies,
                baseline_total_usd=baseline['total_usd'], routed_total_usd=selected_total, savings_usd=savings,
                assumptions=['sequential task; same token/cache/retry counts; evidence supplied by caller, not independently verified',
                             'switching providers/modes can invalidate caches; savings are replay scenarios, not realized savings'],
                unknown=unknown)

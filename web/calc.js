/* Pure browser/Node port of cost_router/core.py. Decimal arithmetic uses BigInt. */
(function (root) {
'use strict';
const UNKNOWN = 'unknown', INCLUDED = 'included_in_output';
const TOKENS = ['input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens'];
function dec(v) {
  const m = String(v).match(/^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);
  if (!m || !(m[2] || m[3])) throw Error('invalid number: ' + v);
  let n = BigInt((m[1] || '') + ((m[2] || '0') + (m[3] || ''))), s = (m[3] || '').length - Number(m[4] || 0);
  if (Math.abs(s) > 1000) throw Error('number exponent too large');
  if (s < 0) { n *= 10n ** BigInt(-s); s = 0; }
  return [n,s];
}
function money([n,s]) {
  const neg = n < 0n; let t = (neg ? -n : n).toString().padStart(s + 1,'0');
  if (s) t = (t.slice(0,-s) + '.' + t.slice(-s)).replace(/0+$/,'').replace(/\.$/,'');
  return (neg ? '-' : '') + t;
}
function add(a,b) { const [x,s] = dec(a), [y,t] = dec(b), z = Math.max(s,t); return money([x*10n**BigInt(z-s)+y*10n**BigInt(z-t),z]); }
function sub(a,b) { const [n,s] = dec(b); return add(a,money([-n,s])); }
function cmp(a,b) { const [n] = dec(sub(a,b)); return n < 0n ? -1 : n > 0n ? 1 : 0; }
const sum = values => values.reduce(add,'0');
function number(v) {
  if (v == null || v === '' || v === UNKNOWN) return null;
  if (typeof v === 'boolean') throw Error('boolean is not a number');
  const d = dec(v); if (d[0] < 0n) throw Error('numbers must be finite and nonnegative');
  return money(d);
}
function normalize(raw) {
  const r = {...raw};
  for (const k of TOKENS) { const n = number(r[k]); if (n !== null && (n.includes('.') || !Number.isSafeInteger(Number(n)))) throw Error(k + ' must be a safe integer'); r[k] = n === null ? null : Number(n); }
  r.id = String(r.id ?? UNKNOWN); r.model = r.model || UNKNOWN;
  const mode = r.mode || 'standard'; if (!['standard','fast',UNKNOWN].includes(mode)) throw Error('mode must be standard, fast or unknown');
  if (mode !== 'standard' && !r.model.includes(':')) r.model += ':' + mode;
  delete r.mode;
  const b = r.retry; if (b == null || b === '' || b === UNKNOWN) r.retry = null;
  else if (b === true || b === 'true') r.retry = true;
  else if (b === false || b === 'false') r.retry = false; else throw Error('retry must be true, false or unknown');
  for (const k of ['latency_limit_seconds','quality_min_ratio']) r[k] = number(r[k]);
  r.status ||= UNKNOWN; r.kind ||= UNKNOWN; r.granularity ||= 'request';
  if (!['request','aggregate'].includes(r.granularity)) throw Error('granularity must be request or aggregate');
  const semantics = r.input_semantics || 'inclusive'; delete r.input_semantics;
  if (!['inclusive','exclusive'].includes(semantics)) throw Error('input_semantics must be inclusive or exclusive');
  let [i,c,w,o,q] = TOKENS.map(k => r[k]);
  if (semantics === 'exclusive') { i = [i,c,w].includes(null) ? null : i+c+w; r.input_tokens = i; }
  if (i !== null && (c || 0)+(w || 0) > i) throw Error('cache reads + writes exceed inclusive input');
  if (o !== null && q !== null && q > o) throw Error('reasoning_output_tokens exceeds inclusive output_tokens');
  r.cache_write_ttl ||= UNKNOWN;
  if (!['5m','1h','provider_default',UNKNOWN].includes(r.cache_write_ttl)) throw Error('unsupported cache_write_ttl');
  for (const k of ['tool_cost_usd','evidence']) {
    let v = r[k]; if (typeof v === 'string' && v.startsWith('{')) v = JSON.parse(v);
    if (k === 'tool_cost_usd') v = v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).map(([key,x])=>[key,number(x)])) : number(v);
    else { v ||= {}; if (typeof v !== 'object' || Array.isArray(v)) throw Error('evidence must be an object'); }
    r[k] = v;
  }
  return r;
}
function csv(text) {
  const rows = []; let row = [], field = '', quoted = false;
  text = text.replace(/^\uFEFF/,'');
  for (let i=0; i<text.length; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i+1] === '"') { field += '"'; i++; } else quoted = !quoted; }
    else if (!quoted && (c === ',' || c === '\n' || c === '\r')) {
      row.push(field); field = '';
      if (c !== ',') { if (row.some(x=>x!=='')) rows.push(row); row=[]; if (c==='\r' && text[i+1]==='\n') i++; }
    } else field += c;
  }
  if (quoted) throw Error('unterminated CSV quote');
  if (field || row.length) { row.push(field); rows.push(row); }
  const keys = rows.shift() || [];
  return rows.map(r=>Object.fromEntries(keys.map((k,i)=>[k,r[i] ?? ''])));
}
function loadTrace(text, format) {
  const events = format === 'csv' ? csv(text) : text.split(/\r?\n/).flatMap((line,i)=> {
    if (!line.trim()) return [];
    try { const e=JSON.parse(line); if (!e || typeof e!=='object' || Array.isArray(e)) throw Error('record must be an object'); return [e]; }
    catch (e) { throw Error('line '+(i+1)+': '+e.message); }
  });
  const records = events.some(e=>e.type==='token_usage_record'), rows=[], seen=new Map();
  let model=UNKNOWN, mode='standard', session=UNKNOWN, previous=null;
  events.forEach((e,i)=> {
    const t=e.type,p=e.payload || {},pos=i+1; let raw=null;
    if (t==='session_meta') { session=p.id ?? UNKNOWN; previous=null; }
    if (t==='turn_context') { model=p.model ?? UNKNOWN; mode=p.mode ?? p.speed ?? 'standard'; }
    if (t==='token_usage_record') {
      const key=JSON.stringify([p.session_id ?? session,p.response_id ?? `line-${pos}`]);
      if (seen.has(key)) { if (!equal(seen.get(key),p.usage)) throw Error('conflicting duplicate response usage'); return; }
      seen.set(key,p.usage);
      raw={...(p.usage || {}),id:`${p.session_id ?? session}:${p.response_id ?? `line-${pos}`}`,model:p.model ?? model,mode:p.mode ?? mode,granularity:'request'};
    } else if (['turn.completed','turn.failed'].includes(t) && !records) {
      raw={...(e.usage || {}),id:e.turn_id ?? `line-${pos}`,model:e.model ?? model,mode:e.mode ?? mode,retry:e.retry,status:t==='turn.failed'?'failed':'completed',granularity:e.granularity ?? 'aggregate'};
      for (const k of ['cache_write_ttl','tool_cost_usd','kind','evidence']) if (k in e) raw[k]=e[k];
    } else if (t==='event_msg' && p.type==='token_count' && !records) {
      const total=p.info?.total_token_usage;
      if (total && Object.keys(total).length) {
        if (equal(total,previous)) return;
        raw={}; for (const k of TOKENS) { const a=total[k],b=previous ? previous[k] : 0; raw[k]=a==null || b==null ? null : a-b; if (raw[k]<0) throw Error('cumulative usage reset; split sessions before importing'); }
        previous=total; Object.assign(raw,{id:`line-${pos}`,model,mode,granularity:'aggregate'});
      }
    } else if (!t) raw={id:`line-${pos}`,...e};
    if (raw) rows.push(normalize(raw));
  });
  if (!rows.length) throw Error('no usage records found; empty traces cannot mean zero cost');
  return rows;
}
function equal(a,b) { if (a===b) return true; if (!a || !b || typeof a!=='object' || typeof b!=='object') return false; const keys=Object.keys(a); return keys.length===Object.keys(b).length && keys.every(k=>equal(a[k],b[k])); }
function billRound(r,prices,target) {
  const unknown=[],notes=[],charges={},m=prices.models[target]; let tier=UNKNOWN;
  if (m) {
    if (m.long_context_threshold.value===null) tier='short';
    else if (r.granularity==='aggregate') unknown.push('context: aggregate usage lacks per-request context lengths');
    else if (r.input_tokens===null) unknown.push('context: input_tokens unknown');
    else tier=r.input_tokens>m.long_context_threshold.value?'long':'short';
    if (r.granularity==='request' && r.input_tokens!==null && r.output_tokens!==null && r.input_tokens+r.output_tokens>m.context_window.value) unknown.push('context_window: trace exceeds supported context; replay infeasible');
  } else unknown.push('model price: '+target);
  const rates=m && tier!==UNKNOWN ? m.rates[tier] : {};
  function charge(label,count,field) {
    const rate=rates[field]?.value ?? UNKNOWN;
    if (count===0) charges[label]='0';
    else if (count===null || rate===UNKNOWN) { charges[label]=UNKNOWN; unknown.push(`${label}: usage or ${field} price unknown`); }
    else { const [n,s]=dec(rate); charges[label]=money([BigInt(count)*n,s+6]); }
  }
  const [i,c,w,o,q]=TOKENS.map(k=>r[k]);
  if (c===null) unknown.push('cached_input_tokens'); if (w===null) unknown.push('cache_write_input_tokens');
  charge('input',[i,c,w].includes(null)?null:i-c-w,'input'); charge('cached_input',c,'cached_input');
  const write=r.cache_write_ttl==='1h'?'cache_write_1h_input':'cache_write_input';
  if (w && m?.provider==='anthropic' && !['5m','1h'].includes(r.cache_write_ttl)) { charge('cache_write_input',null,write); unknown.push('cache_write_ttl: Anthropic needs 5m or 1h'); }
  else charge('cache_write_input',w,write);
  if (q===null) { charge('output',o,'output'); charges.reasoning_output=INCLUDED; notes.push('reasoning split unknown; inclusive output charged once'); }
  else { charge('output',o===null?null:o-q,'output'); charge('reasoning_output',q,'reasoning_output'); }
  const tool=r.tool_cost_usd && typeof r.tool_cost_usd==='object'?r.tool_cost_usd[target]:r.tool_cost_usd;
  charges.tools=tool ?? UNKNOWN; if (tool==null) unknown.push('tools: fee inventory/cost missing');
  const subtotal=sum(Object.values(charges).filter(v=>![UNKNOWN,INCLUDED].includes(v)));
  return {id:r.id,original_model:r.model,model:target,kind:r.kind,retry:r.retry,status:r.status,tier,usage:Object.fromEntries(TOKENS.map(k=>[k,r[k]])),rates_usd_per_million:Object.fromEntries(Object.entries(rates).map(([k,v])=>[k,v.value])),charges_usd:charges,known_subtotal_usd:subtotal,total_usd:unknown.length?UNKNOWN:subtotal,unknown,notes};
}
function bill(rows,prices,target='original') {
  const rounds=rows.map(r=>billRound(r,prices,target==='original'?r.model:target));
  const unknown=rounds.flatMap(r=>r.unknown.map(u=>`${r.id}: ${u}`)),subtotal=sum(rounds.map(r=>r.known_subtotal_usd)),items={};
  for (const k of ['input','cached_input','cache_write_input','output','reasoning_output','tools']) { const values=rounds.map(r=>r.charges_usd[k]); items[k]=values.includes(UNKNOWN)?UNKNOWN:values.includes(INCLUDED)?INCLUDED:sum(values); }
  return {model:target,currency:'USD',scope:'direct API global token replay; not subscription charges',assumptions:['same recorded token counts, cache hits and attempts across models; counterfactual only'],rounds,charges_usd:items,known_subtotal_usd:subtotal,total_usd:unknown.length?UNKNOWN:subtotal,unknown};
}
function route(rows,prices,slo='latency<=30s,quality>=baseline') {
  const match=slo.replace(/ /g,'').match(/^latency<=([0-9]+(?:\.[0-9]+)?)s,quality>=baseline$/);
  if (!match || cmp(match[1],0)<=0) throw Error('SLO format: latency<=30s,quality>=baseline (task-wide sequential latency)');
  const deadline=match[1],baseline=bill(rows,prices),options=[],strategies=[];
  for (const r of rows) {
    const complete=Object.entries(prices.models).map(([m])=>[m,billRound(r,prices,m).total_usd]).filter(([,v])=>v!==UNKNOWN);
    const cheapest=[...complete].sort((a,b)=>cmp(a[1],b[1]) || (a[0]<b[0]?-1:a[0]>b[0]?1:0))[0]?.[0] ?? UNKNOWN;
    const orig=billRound(r,prices,r.model).total_usd,eligible=[];
    for (const [m,cost] of complete) {
      const e=r.evidence[m] ?? {}; if (typeof e!=='object' || e===null || Array.isArray(e)) throw Error('model evidence must be an object');
      const q=number(e.quality_vs_baseline),lat=number(e.latency_seconds),floor=cmp(r.quality_min_ratio || 1,1)>0?r.quality_min_ratio:'1',limit=number(r.latency_limit_seconds);
      if (q!==null && cmp(q,floor)>=0 && lat!==null && (limit===null || cmp(lat,limit)<=0) && e.source && e.kind===r.kind && r.kind!==UNKNOWN) eligible.push([m,cost,lat,e.source]);
    }
    options.push(eligible); strategies.push({id:r.id,kind:r.kind,selected:r.model,reason:'retain original: no task-feasible quality and latency evidence',scenario:cheapest,scenario_savings_usd:orig!==UNKNOWN && cheapest!==UNKNOWN?sub(orig,complete.find(([m])=>m===cheapest)[1]):UNKNOWN,scenario_note:'cost scenario only; does not establish safe downgrade'});
  }
  let frontier=[['0','0',[]]];
  for (const candidates of options) {
    const expanded=frontier.flatMap(([lat,cost,path])=>candidates.filter(([,c,l])=>cmp(add(lat,l),deadline)<=0).map(([m,c,l,source])=>[add(lat,l),add(cost,c),[...path,[m,source]]]));
    frontier=[]; let best=null;
    for (const state of expanded.sort((a,b)=>cmp(a[0],b[0]) || cmp(a[1],b[1]))) if (best===null || cmp(state[1],best)<0) { frontier.push(state); best=state[1]; }
  }
  let latency=UNKNOWN;
  if (frontier.length) { const [lat,,path]=[...frontier].sort((a,b)=>cmp(a[1],b[1]) || cmp(a[0],b[0]))[0]; latency=lat; path.forEach(([m,source],i)=>Object.assign(strategies[i],{selected:m,reason:'lowest total cost meeting task SLO in supplied evidence: '+source})); }
  const selected=rows.map((r,i)=>billRound(r,prices,strategies[i].selected)),totals=selected.map(r=>r.total_usd),total=totals.includes(UNKNOWN)?UNKNOWN:sum(totals);
  const unknown=[...new Set(selected.flatMap(r=>r.unknown))].sort(); if (!frontier.length) unknown.push('quality/latency: no evidence-backed complete route within task deadline');
  return {slo,slo_status:frontier.length?'supported_by_supplied_evidence':UNKNOWN,latency_seconds:latency,strategy:strategies,baseline_total_usd:baseline.total_usd,routed_total_usd:total,savings_usd:[baseline.total_usd,total].includes(UNKNOWN)?UNKNOWN:sub(baseline.total_usd,total),assumptions:['sequential task; same token/cache/retry counts; evidence supplied by caller, not independently verified','switching providers/modes can invalidate caches; savings are replay scenarios, not realized savings'],unknown};
}
const api={normalize,loadTrace,billRound,bill,route,sum,UNKNOWN};
if (typeof module!=='undefined') module.exports=api; else root.CostCalc=api;
})(globalThis);

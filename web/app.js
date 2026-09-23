'use strict';
const $ = id => document.getElementById(id), C = CostCalc, prices = window.COST_PRICES;
const names = ['GPT-6 Sol','GPT-6 Luna','Opus 5.5','Opus 5.5 Fast'];
const models = Object.keys(prices.models);
const escapeHTML = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cell = value => `<td${value==='unknown'?' class="unknown"':''}>${escapeHTML(value==='unknown'?'unknown':'$'+value)}</td>`;
// Sum per-request inclusive output: mixed known/unknown reasoning splits remain billable once.
function inclusiveOutput(b) {
  const values=b.rounds.map(r=> { const a=r.charges_usd.output,q=r.charges_usd.reasoning_output; return a==='unknown'||q==='unknown'?'unknown':C.sum([a,q==='included_in_output'?'0':q]); });
  return values.includes('unknown')?'unknown':C.sum(values);
}
function calculate() {
  try {
    const text=$('trace').value,format=text.trimStart().startsWith('{')?'jsonl':'csv';
    const rows=C.loadTrace(text,format),bills=models.map(m=>C.bill(rows,prices,m)),r=C.route(rows,prices);
    const fields=[['input',b=>b.charges_usd.input],['cache read',b=>b.charges_usd.cached_input],['cache write',b=>b.charges_usd.cache_write_input],['output（含 reasoning）',inclusiveOutput],['工具费用',b=>b.charges_usd.tools],['已知小计',b=>b.known_subtotal_usd],['完整总额',b=>b.total_usd]];
    $('results').innerHTML='<table><caption class="hint muted">同一轨迹重放 · '+rows.length+' 次记录（含失败/重试）</caption><thead><tr><th scope="col">USD</th>'+names.map(n=>'<th scope="col">'+n+'</th>').join('')+'</tr></thead><tbody>'+fields.map(([label,get])=>'<tr><th scope="row">'+label+'</th>'+bills.map(b=>cell(get(b))).join('')+'</tr>').join('')+'</tbody></table>';
    $('issues').innerHTML=bills.map((b,i)=>'<p><strong>'+names[i]+'</strong><br>'+ (b.unknown.length?b.unknown.map(escapeHTML).join('<br>'):'无 unknown 项')+'</p><details><summary>逐请求收据</summary>'+b.rounds.map(x=>'<p>'+escapeHTML(x.id)+' · '+escapeHTML(x.tier)+' · '+escapeHTML(x.status)+' · retry='+escapeHTML(x.retry)+'<br>'+escapeHTML(JSON.stringify(x.charges_usd))+'</p>').join('')+'</details>').join('');
    $('issues').className='unknown';
    const supported=r.slo_status!=='unknown',selected=[...new Set(r.strategy.map(s=>s.selected))].join(' / ');
    const complete=bills.filter(b=>b.total_usd!=='unknown').sort((a,b)=>Number(a.total_usd)-Number(b.total_usd));
    const cheapest=complete[0];
    const lines=[supported?'证据支持的选择：'+selected+'；任务时延 '+r.latency_seconds+'s。':'建议保留原模型：'+selected+'；质量/时延证据不足以支持完整路由。',cheapest?'固定轨迹最低完整成本：'+cheapest.model+'，$'+cheapest.total_usd+'；仅作成本情景。':'成本情景 unknown：四档均缺完整账单，先查看缺失项。',supported?'相对原账单差额：'+(r.savings_usd==='unknown'?'unknown':'$'+r.savings_usd)+'；以日志所附证据为前提。':'下一步：补齐 unknown 字段及同任务类型的质量、时延、来源证据，再判断能否切换。'];
    $('route').innerHTML=lines.map(x=>'<p>'+escapeHTML(x)+'</p>').join('');
    $('status').textContent='已计算 '+rows.length+' 条记录'+($('trace').value===window.COST_SAMPLE?' · 合成示例，非真实账单':''); $('status').className='';
  } catch(e) {
    $('status').textContent='无法计算：'+e.message; $('status').className='error';
    $('results').textContent='没有可用账单'; $('route').textContent='输入有效轨迹后再给出建议。'; $('issues').textContent='';
  }
}
function sourceTree(value,path='') {
  if (!value || typeof value!=='object') return '';
  if ('source_url' in value) {
    const links=Object.entries(value).filter(([k])=>k.endsWith('_url')).map(([k,url])=>/^https:\/\//.test(url)?`<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(k)}: ${escapeHTML(url)}</a>`:escapeHTML(url)).join('<br>');
    return '<p><strong>'+escapeHTML(path)+'</strong> = '+escapeHTML(value.value ?? 'null')+'<br>'+links+'<br>抓取 '+escapeHTML(value.fetched_at)+'<br>'+escapeHTML(value.note || '')+'</p>';
  }
  return Object.entries(value).map(([k,v])=>sourceTree(v,path?path+'.'+k:k)).join('');
}
$('sources').innerHTML=sourceTree(prices);
$('sample').addEventListener('click',()=> { $('trace').value=window.COST_SAMPLE; calculate(); });
$('trace').addEventListener('input',calculate);
let fileReadVersion=0;
async function readFile(file) {
  if (!file) return; const version=++fileReadVersion;
  $('status').textContent='正在本地读取 '+file.name+'…';
  try { const text=await file.text(); if (version!==fileReadVersion) return; $('trace').value=text; calculate(); }
  catch(e) { $('trace').value=''; calculate(); $('status').textContent='读取失败：'+e.message; }
}
$('file').addEventListener('change',e=>readFile(e.target.files[0]));
$('drop').addEventListener('dragover',e=>{e.preventDefault();$('drop').classList.add('active');});
$('drop').addEventListener('dragleave',()=> $('drop').classList.remove('active'));
$('drop').addEventListener('drop',e=> { e.preventDefault(); $('drop').classList.remove('active'); readFile(e.dataTransfer.files[0]); });
$('trace').value=window.COST_SAMPLE;
calculate();

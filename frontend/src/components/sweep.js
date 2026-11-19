import {store} from '../stores/business.js';import {sweeps} from '../api/business.js';import {esc,json} from '../utils/html.js';import {table} from '../components/common/table.js';import {SWEEP_STATUSES} from '../constants/enums.js';import {feedback} from '../components/common/feedback.js';

let selected=null;
const isRange=st=>st.op==='filter'&&(st.compare==='gte'||st.compare==='lte');
const stepsFor=t=>(t.snapshot?.plan?.steps||[]).map((st,i)=>({st,i})).filter(x=>isRange(x.st));
const detailOf=id=>store.sweepDetails?.[id]||store.sweeps.find(s=>s.id===id);
function range(a,b=a){
 const lo=a.lower,hi=b.upper;
 if(lo===null&&hi===null)return '任意阈值';
 if(lo===null)return `阈值 ${b.upper_inclusive?'≤':'<'} ${hi}`;
 if(hi===null)return `阈值 ${a.lower_inclusive?'≥':'>'} ${lo}`;
 return `${lo} ${a.lower_inclusive?'≤':'<'} 阈值 ${b.upper_inclusive?'≤':'<'} ${hi}`;
}
function meaning(interval,compare){
 if(interval.lower===null&&interval.upper===null)return '代表阈值 0（任意），区间内分组不变';
 return `代表阈值 ${interval.threshold}（原比较 ${compare==='gte'?'≥':'≤'}），区间内分组不变`;
}
function groupLabel(s,g){
 const first=s.intervals[g.member_indexes[0]],last=s.intervals[g.member_indexes[g.member_indexes.length-1]];
 return range(first,last);
}
function groupNote(s,g){
 const first=s.intervals[g.member_indexes[0]];
 const merged=g.member_indexes.length>1?` · 由 ${g.member_indexes.length} 个相邻区间合并`:'';
 return `${meaning(first,s.compare)}${merged}`;
}
function pendingRuns(s){
 const runs=[];
 for(const interval of (s.intervals||[]).filter(i=>i.status==='pending')){
  const last=runs[runs.length-1];
  if(last&&last.end===interval.index-1)last.end=interval.index;else runs.push({start:interval.index,end:interval.index});
 }
 return runs.map(r=>({first:s.intervals[r.start],last:s.intervals[r.end],count:r.end-r.start+1}));
}
function rowsHtml(s){
 const done=(s.groups||[]).map(g=>[`<code>${esc(groupLabel(s,g))}</code><small>${esc(groupNote(s,g))}</small>`,`<b>${g.output_rows}</b><small>行</small>`,`<code class="checksum">${esc(g.checksum)}</code>`,`<button class="quiet" data-sweep-group="${g.root_index}">完整结果</button>`]);
 const pending=pendingRuns(s).map(r=>[`<code>${esc(range(r.first,r.last))}</code><small>尚未计算${r.count>1?` · ${r.count} 段`:''}</small>`,'<span class="status">待算</span>','—','—']);
 const failed=(s.intervals||[]).filter(i=>i.status==='failed').map(i=>[`<code>${esc(range(i))}</code><small>${esc(i.error||'超出执行限制')}</small>`,'<span class="status failed">超限</span>','—',`<button class="quiet" data-sweep-resume="${s.id}">重试</button>`]);
 return table(['阈值区间','输出行数','结果 SHA-256','动作'],[...done,...pending,...failed])+'<div class="sweep-output" id="sweep-output"></div>';
}
function card(s){
 if(!s)return '<p class="muted">这份存档还没有阈值扫描。选择一道筛选，只更换它的阈值。</p>';
 const left=(s.pending_count||0)+(s.failed_count||0);
 return `<div class="sweep-head"><div><h3>${esc(s.name)} <span class="status ${s.status}">${SWEEP_STATUSES[s.status]||s.status}</span></h3><p class="muted">第 ${s.step_index+1} 步 <code>${esc(s.field)} ${esc(s.compare)}</code> · 已确认 ${s.published_count+(s.merged_count||0)} / ${s.total_intervals} 段${s.pending_count?` · 待算 ${s.pending_count}`:''}${s.failed_count?` · 失败 ${s.failed_count}`:''}</p></div>${left?`<button class="quiet" data-sweep-resume="${s.id}">中断续跑 ↻</button>`:''}</div>${s.error?`<div class="feedback error">${esc(s.error)}</div>`:''}${rowsHtml(s)}`;
}

export function sweepSection(t){
 const mine=store.sweeps.filter(s=>s.trace_id===t.id);
 if(selected&&!mine.some(s=>s.id===selected))selected=null;
 const current=mine.find(s=>s.id===selected)||mine[0]||null;
 if(current)selected=current.id;
 const choices=mine.length>1?`<label>已建扫描<select data-sweep-select>${mine.map(s=>`<option value="${s.id}" ${s.id===current?.id?'selected':''}>${esc(s.name)} · ${SWEEP_STATUSES[s.status]||s.status}</option>`).join('')}</select></label>`:'';
 const steps=stepsFor(t);
 const picker=`<details><summary>新建阈值扫描</summary><form id="sweep-form"><label>数值范围筛选步骤<select name="step_index">${steps.map(x=>`<option value="${x.i}">第 ${x.i+1} 步 · ${esc(x.st.field)} ${esc(x.st.compare)} ${esc(x.st.value)}</option>`).join('')}</select></label><label>扫描名称（可留空）<input name="name" maxlength="160" placeholder="留空则自动命名"></label><button type="submit">按原规则扫描阈值</button></form></details>`;
 return `<section class="sweep"><span class="eyebrow">THRESHOLD SWEEP / 只换一道阈值</span><h2>阈值—分组对照</h2><p class="muted">从这份存档的不可变快照出发，比较方式、重复键倍数、连接后聚合与超限规则都保持原样，只改所选数值范围筛选的阈值。共用前缀只算一次；相邻且完整结果相同的区间合并，已发布的边界不再改写。</p>${choices}${card(detailOf(current?.id))}${steps.length?picker:''}</section>`;
}

function rerender(t){const old=document.querySelector('.sweep');if(!old)return;const box=document.createElement('div');box.innerHTML=sweepSection(t);old.replaceWith(box.firstElementChild);mountSweep(t);}

export function mountSweep(t){
 const host=document.querySelector('.sweep');
 if(!host)return;
 const readOnly=store.user?.role==='viewer';
 const mine=store.sweeps.filter(s=>s.trace_id===t.id);
 const id=selected&&mine.some(s=>s.id===selected)?selected:(mine[0]?.id??null);
 const load=async value=>{const d=await sweeps.detail(value);store.sweepDetails={...(store.sweepDetails||{}),[value]:d};const at=store.sweeps.findIndex(s=>s.id===value);if(at>=0)store.sweeps[at]={...store.sweeps[at],...d};};
 document.querySelectorAll('[data-sweep-select]').forEach(sel=>sel.onchange=async()=>{selected=Number(sel.value);try{await load(selected);}catch(e){feedback(e.message,true);}rerender(t);});
 const cached=id?store.sweepDetails?.[id]:null;
 if(id&&(!cached||cached.status==='queued'||cached.status==='running'))load(id).then(()=>{if(!document.querySelector('.sweep-output:not(:empty)'))rerender(t);}).catch(e=>feedback(e.message,true));
 document.querySelectorAll('[data-sweep-group]').forEach(btn=>btn.onclick=()=>{
  const s=detailOf(id);const out=document.getElementById('sweep-output');if(!s||!out)return;
  const g=(s.groups||[]).find(x=>x.root_index===Number(btn.dataset.sweepGroup));if(!g)return;
  out.innerHTML=`<h3>完整结果 <small>${esc(groupLabel(s,g))}</small></h3><div class="operator-strip">${g.operators.map(o=>`<div><span>${esc(o.op)}</span><b>${o.input_rows} → ${o.output_rows}</b><small>${esc(String(o.checksum).slice(0,12))}…</small></div>`).join('')}</div><pre>${json(g.preview)}</pre><code class="checksum">${esc(g.checksum)}</code>`;
 });
 document.querySelectorAll('[data-sweep-resume]').forEach(btn=>btn.onclick=async()=>{
  try{const r=await sweeps.resume(btn.dataset.sweepResume);await load(r.id);feedback('已从原游标续算；已确认区间不会重复发布。');rerender(t);}catch(e){feedback(e.message,true);}
 });
 if(readOnly)host.querySelectorAll('form button[type=submit], [data-sweep-resume]').forEach(b=>{b.disabled=true;b.title='观察员只读';});
 document.getElementById('sweep-form')?.addEventListener('submit',async e=>{
  e.preventDefault();const f=new FormData(e.target);
  try{const r=await sweeps.run({trace_id:t.id,step_index:Number(f.get('step_index')),name:String(f.get('name')||'')});await load(r.id);const at=store.sweeps.findIndex(s=>s.id===r.id);if(at<0)store.sweeps=[{...r},...store.sweeps];selected=r.id;feedback('阈值扫描已排队；已发布的区间先显示，其余标为待算。');rerender(t);}catch(err){feedback(err.message,true);}
 });
}

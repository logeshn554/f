'use strict';
let state=null, view='live', loading=false, lastSuccess=0, hover=null;
const $=id=>document.getElementById(id);
const money=n=>Number.isFinite(n)?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const num=(n,d=2)=>Number.isFinite(n)?n.toFixed(d):'—';
const pct=n=>Number.isFinite(n)?(n>0?'+':'')+n.toFixed(2)+'%':'—';
const stamp=t=>t?new Date(t*1000).toISOString().replace('T',' ').slice(0,19):'—';
function text(id,value){$(id).textContent=value;}
function color(id,n){$(id).classList.toggle('green',n>0);$(id).classList.toggle('red',n<0);}
function node(tag,content,cls){const e=document.createElement(tag);if(content!==undefined)e.textContent=content;if(cls)e.className=cls;return e;}
function toast(s){text('toast',s);$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,6000);}
function cell(row,value,cls){row.append(node('td',value,cls));}
function status(){
  if(!state)return;
  const age=state.quote?Date.now()/1000-state.quote.time:Infinity;
  const localStale=Date.now()-lastSuccess>15000;
  const status=localStale?'OFFLINE':age>30&&state.status==='LIVE'?'STALE':state.status;
  text('connection',status);$('connection').className='connection '+(status==='LIVE'?'live':['BLOCKED','STALE','OFFLINE','STOPPED'].includes(status)?'blocked':'');
  text('clock',new Date().toISOString().slice(11,19)+' UTC');
  const caution='Research has not established a profitable edge. The 90% target is unproven.';
  let message=status==='OFFLINE'?'Local engine is unreachable. Displaying the last received state; no live status is implied.':state.error?state.error+' · Paper fills are blocked.':state.controls.flatten?'Paper close queued. Waiting for a valid quote.':status==='HALTED'?'Risk limit reached. New entries are disabled.':status==='PAUSED'?'New entries paused. Open positions continue to be managed.':caution;
  if(state.gap_warning&&!state.error)message+=' '+state.gap_warning;
  text('notice',message);$('notice').classList.toggle('error',['BLOCKED','STALE','OFFLINE','STOPPED'].includes(status));
  text('footerstatus',state.checked_at?'Last cycle '+state.checked_at.slice(11,19)+' UTC · '+num(state.cycle_ms,0)+' ms':'Waiting for engine');
  text('quotetime',state.quote?'Quote '+stamp(state.quote.time).slice(11)+' UTC · age '+Math.max(0,age).toFixed(0)+'s':'No quote yet');
}
function render(data){
  state=data;
  text('region',data.region.toUpperCase());
  const s=data.summary,q=data.quote,p=s?.position;
  $('pause').disabled=!s||!!s.halt||data.controls.flatten;
  text('pause',data.controls.paused?'Resume entries':'Pause entries');
  $('flatten').disabled=!p||data.controls.flatten;
  text('flatten',data.controls.flatten?'Close queued…':'Close paper position');
  if(s){text('equity',money(s.equity));text('return',pct(s.return_pct)+' from $100.00');color('return',s.return_pct);text('trades',String(s.closed_trades));text('winrate',s.closed_trades?num(s.win_rate_pct,1)+'% wins · forward paper only':'No closed paper trades yet');text('drawdown',num(s.max_observed_drawdown_pct)+'%');text('riskbudget',money(Math.min(s.equity,s.cash)*data.config.risk));}
  renderForwardEvidence(data.forward_evidence);
  if(q){text('price',money(q.bid));text('spread','Ask '+money(q.ask)+' · spread '+num(10000*(q.ask-q.bid)/((q.bid+q.ask)/2),2)+' bp');}
  if(data.signal){const sig=data.signal;text('signal',sig.label);$('signal').className=sig.side===1?'green':sig.side===-1?'red':'';text('bias','Best candidate: '+(sig.bias===1?'BUY':'SELL')+' · gates must pass');$('gates').replaceChildren(...sig.gates.map(g=>{const d=node('div',undefined,'gate'+(g.passed?' pass':''));d.append(node('span',g.passed?'✓':'—','state'),node('strong',g.name),node('small',g.detail));return d;}));text('entrywindow',data.entry_window_open?'Entry window open · quote and sizing guards still apply':'Next entry decision follows a completed 15m candle.');text('preview','Candidate SL distance '+money(sig.stop_distance)+' / ETH · TP distance '+money(sig.target_distance)+'. Sample-derived levels; not an open trade.');text('pathcount',sig.candidates+' historical contexts → '+sig.matched_paths+' separated paths · '+num(sig.effective_paths,1)+' effective samples');if(sig.plans)$('plantable').replaceChildren(...sig.plans.map(p=>{const tr=node('tr');cell(tr,p.label,p.side===1?'green':'red');cell(tr,money(p.mean_net_per_eth),p.mean_net_per_eth>0?'green':'red');cell(tr,money(p.utility),p.utility>0?'green':'red');cell(tr,num(p.sample_win_pct,1)+'% · uncalibrated');cell(tr,money(p.stop_distance));cell(tr,money(p.target_distance));return tr;}));}
  text('positionbadge',p?(p.side===1?'LONG':'SHORT')+' · '+p.contracts+' CONTRACT'+(p.contracts===1?'':'S'):'FLAT');
  if(p){const grid=node('div',undefined,'positiongrid');for(const [label,value,cls] of [['Entry',money(p.entry),''],['Stop loss',money(p.stop),'red'],['Take profit',money(p.target),'green'],['Quantity',num(p.qty,2)+' ETH','']]){const d=node('div');d.append(node('span',label),node('b',value,cls));grid.append(d);}$('position').replaceChildren(grid);}else $('position').replaceChildren(node('p','No paper position. The engine waits for a qualifying signal and a contract size within the $100 account’s risk budget.','muted'));
  const events=data.events||[];
  if(events.length){$('journal').replaceChildren(...events.map(e=>{const r=node('tr');cell(r,stamp(e.time||e.opened));cell(r,e.kind,e.kind==='EXIT'?(e.net_pnl>=0?'green':'red'):'cyan');cell(r,e.side===1?'BUY':e.side===-1?'SELL':'—');cell(r,e.kind==='ADJUST'?'SL '+money(e.after.stop)+' / TP '+money(e.after.target):money(e.price||e.entry));cell(r,e.contracts?e.contracts+' × 0.01 ETH':'—');cell(r,e.kind==='EXIT'?money(e.net_pnl):'—',e.kind==='EXIT'?(e.net_pnl>=0?'green':'red'):'');cell(r,e.reason||'Qualified signal');return r;}));}
  text('journalcount',events.length?events.length+' recent events':'Simulated fills and exit adjustments');
  text('equitycaption',data.equity?.length?'Observed equity · fees included · funding reserve '+money(s?.funding_reserve_debits):'No forward observations yet.');
  $('sources').replaceChildren(...data.sources.map(s=>{const a=node('a',s.title);a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';return a;}));
  renderResearch(data.research);status();draw();
}
function renderResearch(r){
  $('researchcontent').hidden=!r;if(!r)return;
  const h=r.holdout,c=r.cost_stress;
  text('researchnotice','Chronological replay test: '+pct(h.return_pct)+' across '+h.closed_trades+' trades. '+(!h.closed_trades?'No candidate passed the net-edge gates; a flat account is not evidence of profitability.':r.assessment.positive_holdout_and_stress?'Positive under these assumptions; still unvalidated.':'The strategy failed the positive-return check.')+' Previously viewed dataset.');
  text('hreturn',pct(h.return_pct));color('hreturn',h.return_pct);text('hrange',h.start.slice(0,10)+' → '+h.end.slice(0,10));text('hwin',num(h.win_rate_pct,1)+'%');text('hinterval',h.confidence_interval?'95% interval '+num(h.confidence_interval[0],1)+'–'+num(h.confidence_interval[1],1)+'%':'No closed trades');text('stressreturn',pct(c.return_pct));color('stressreturn',c.return_pct);text('targetstatus',r.assessment.target_supported?'Historical interval supports target; not a guarantee':'Not supported by this sample');text('barcount',r.bars.toLocaleString()+' 15m candles');
  $('periods').replaceChildren(...[['Development',r.development],['Holdout',h],['Double costs',c],...r.chronological_blocks.map((x,i)=>['Holdout block '+(i+1),x])].map(([label,x])=>{const tr=node('tr');cell(tr,label);cell(tr,pct(x.return_pct),x.return_pct>=0?'green':'red');cell(tr,String(x.closed_trades));cell(tr,num(x.win_rate_pct,1)+'%');cell(tr,num(x.profit_factor));cell(tr,num(x.max_observed_drawdown_pct)+'%');cell(tr,x.halt?'Triggered':'—');return tr;}));
  $('assumptions').replaceChildren(...r.assumptions.map(s=>node('li',s)));text('researchdate','Generated '+r.built_at.replace('T',' ').slice(0,19)+' UTC · strategy SHA-256 '+r.strategy_sha256.slice(0,16)+'…');
}
function renderForwardEvidence(ev){
  if(!ev)return;
  text('evidencehash',ev.model_hash?ev.model_hash.slice(0,8).toUpperCase():'NO HASH');
  text('evforecasts',String(ev.forecasts??0));
  text('evmatured',String(ev.matured??0));
  text('evpending',String(ev.pending??0));
  text('evcontainment',ev.containment_pct==null?'—':num(ev.containment_pct,1)+'%');
  const first=ev.first_recorded?stamp(ev.first_recorded):null,last=ev.last_recorded?stamp(ev.last_recorded):null;
  text('evtiming',first?'First '+first+' · latest '+last:'Waiting for the next eligible 15-minute candle.');
  text('evnote',ev.note||'Prospective forecast checks are not trade win rate.');
}
function canvas(id){const el=$(id),rect=el.getBoundingClientRect();if(rect.width<5||rect.height<5)return null;const ratio=window.devicePixelRatio||1;el.width=Math.round(rect.width*ratio);el.height=Math.round(rect.height*ratio);const ctx=el.getContext('2d');ctx.scale(ratio,ratio);return {ctx,w:rect.width,h:rect.height};}
function emptyChart(c,message){c.ctx.fillStyle='#8295ad';c.ctx.font='13px Segoe UI';c.ctx.fillText(message,20,c.h/2);}
function grid(c,min,max,left=12,right=80,bottom=28){const {ctx,w,h}=c;const height=h-bottom-12,width=w-left-right;const y=v=>12+(max-v)/(max-min)*height;ctx.font='11px Consolas,monospace';for(let i=0;i<=4;i++){const value=min+(max-min)*i/4,py=y(value);ctx.strokeStyle='#203044';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(w-right,py);ctx.stroke();ctx.fillStyle='#8194af';ctx.fillText(value.toFixed(2),w-right+9,py+4);}return {y,width,height,left,right,bottom};}
function drawPrice(){const c=canvas('pricechart');if(!c)return;const all=state?.candles||[],bars=all.slice(-80);if(!bars.length)return emptyChart(c,'Waiting for market data');const p=state.summary?.position,q=state.quote;const levels=[];if(q)levels.push({price:q.bid,label:'BID',color:'#8ea0b7'});if(p)levels.push({price:p.entry,label:'ENTRY',color:'#d4deed'},{price:p.stop,label:'SL',color:'#fa8a91'},{price:p.target,label:'TP',color:'#6ad4a5'});const values=bars.flatMap(b=>[b.low,b.high]).concat(levels.map(l=>l.price));let min=Math.min(...values),max=Math.max(...values);const margin=Math.max((max-min)*.12,1);min-=margin;max+=margin;const g=grid(c,min,max,12,88,30);const step=g.width/bars.length,x=i=>g.left+(i+.5)*step;const ctx=c.ctx;
  bars.forEach((b,i)=>{ctx.strokeStyle=ctx.fillStyle=b.close>=b.open?'#63cba6':'#de7889';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x(i),g.y(b.high));ctx.lineTo(x(i),g.y(b.low));ctx.stroke();ctx.fillRect(x(i)-Math.max(1,step*.3),Math.min(g.y(b.open),g.y(b.close)),Math.max(2,step*.6),Math.max(1.3,Math.abs(g.y(b.open)-g.y(b.close))));});
  levels.forEach(l=>{ctx.setLineDash([4,4]);ctx.strokeStyle=l.color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(g.left,g.y(l.price));ctx.lineTo(c.w-g.right,g.y(l.price));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#101925';ctx.fillRect(c.w-g.right+2,g.y(l.price)-10,86,22);ctx.fillStyle=l.color;ctx.font='11px Consolas,monospace';ctx.fillText(l.label+' '+l.price.toFixed(2),c.w-g.right+5,g.y(l.price)+4);});
  ctx.fillStyle='#8295ad';ctx.font='11px Consolas,monospace';for(let i=0;i<bars.length;i+=16)ctx.fillText(stamp(bars[i].time).slice(5,16),x(i),c.h-8);
  if(hover!==null){const i=Math.max(0,Math.min(bars.length-1,Math.floor((hover-g.left)/step))),b=bars[i];ctx.strokeStyle='#657d96';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x(i),10);ctx.lineTo(x(i),c.h-30);ctx.stroke();ctx.setLineDash([]);text('charttip',stamp(b.time).slice(5,16)+' UTC  O '+b.open.toFixed(2)+' H '+b.high.toFixed(2)+' L '+b.low.toFixed(2)+' C '+b.close.toFixed(2));$('charttip').hidden=false;}else $('charttip').hidden=true;
}
function drawLine(id,points){const c=canvas(id);if(!c)return;if(!points?.length)return emptyChart(c,'No observations yet');const vals=points.map(p=>p.equity),min=Math.min(100,...vals),max=Math.max(100,...vals),pad=Math.max((max-min)*.15,.03);const g=grid(c,min-pad,max+pad,12,70,24);const ctx=c.ctx;const x=i=>12+(points.length===1?g.width/2:i/(points.length-1)*g.width);ctx.beginPath();ctx.moveTo(x(0),g.y(points[0].equity));points.forEach((p,i)=>ctx.lineTo(x(i),g.y(p.equity)));ctx.strokeStyle=vals[vals.length-1]>=100?'#6ad4a5':'#fa8a91';ctx.lineWidth=2;ctx.stroke();if(points.length===1){ctx.beginPath();ctx.arc(x(0),g.y(vals[0]),3,0,2*Math.PI);ctx.fillStyle='#6cdbed';ctx.fill();}ctx.fillStyle='#8295ad';ctx.font='11px Consolas,monospace';ctx.fillText(stamp(points[0].time).slice(5,16),12,c.h-5);ctx.fillText(stamp(points[points.length-1].time).slice(5,16),Math.max(140,c.w-180),c.h-5);}
function drawFan(){const c=canvas('fanchart');if(!c)return;const bars=state?.candles?.slice(-16)||[],fan=state?.signal?.fan||[];if(!bars.length||!fan.length)return emptyChart(c,'Waiting for conditional scenarios');const values=bars.map(b=>b.close).concat(fan.flatMap(f=>[f.p10,f.p90]));const lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.12,1);const g=grid(c,lo-pad,hi+pad,12,85,30),ctx=c.ctx,x=i=>12+i/(bars.length+fan.length-1)*g.width;ctx.strokeStyle='#c6d4e6';ctx.lineWidth=2;ctx.beginPath();bars.forEach((b,i)=>i?ctx.lineTo(x(i),g.y(b.close)):ctx.moveTo(x(i),g.y(b.close)));ctx.stroke();const anchor=bars.length-1;ctx.beginPath();ctx.moveTo(x(anchor),g.y(bars[anchor].close));fan.forEach((f,i)=>ctx.lineTo(x(anchor+i+1),g.y(f.p90)));[...fan].reverse().forEach((f,j)=>ctx.lineTo(x(anchor+fan.length-j),g.y(f.p10)));ctx.closePath();ctx.fillStyle='#6cdbed25';ctx.fill();ctx.strokeStyle='#6cdbed';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(x(anchor),g.y(bars[anchor].close));fan.forEach((f,i)=>ctx.lineTo(x(anchor+i+1),g.y(f.p50)));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#8ea0b7';ctx.font='11px Consolas,monospace';ctx.fillText('Observed closes',14,c.h-8);ctx.fillText('Forecast origin',x(anchor)-35,c.h-8);ctx.fillText('+2h',c.w-118,c.h-8);}
function draw(){if(view==='live'){drawPrice();drawFan();drawLine('equitychart',state?.equity);}if(view==='research')drawLine('researchchart',state?.research?.holdout?.curve);}
async function refresh(){if(loading)return;loading=true;try{const r=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(6000)});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();lastSuccess=Date.now();render(d);}catch(e){if(state)status();else{text('connection','OFFLINE');text('notice','The local engine is not responding. Start ETH Guard and refresh this page.');} }finally{loading=false;}}
async function control(action){try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-Paper-Token':state.token},body:JSON.stringify({action})});const d=await r.json();if(!r.ok)throw Error(d.error);toast(action==='flatten'?'Paper close queued; entries paused.':action==='pause'?'New entries paused.':'New entries resumed.');await refresh();}catch(e){toast(e.message);}}
$('pause').addEventListener('click',()=>control(state.controls.paused?'resume':'pause'));
$('flatten').addEventListener('click',()=>control('flatten'));
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{view=button.dataset.tab;document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-selected',String(b===button));});document.querySelectorAll('.tabview').forEach(s=>s.hidden=s.id!==view);draw();}));
$('pricechart').addEventListener('pointermove',e=>{hover=e.clientX-$('pricechart').getBoundingClientRect().left;drawPrice();});$('pricechart').addEventListener('pointerleave',()=>{hover=null;drawPrice();});
window.addEventListener('resize',draw);setInterval(refresh,2500);setInterval(status,1000);refresh();

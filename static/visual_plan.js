// Visual plan: for every narration line, a picture that shows what is said, with the
// reason it was chosen. Built on request, reviewed here, applied as the production
// script only when the user says so.

window.vpData=null;window.vpFor=null;window.vpBusy=false;
const VP_KIND={guide:['Guide clip','Your guide chose this clip'],match:['Matched','A shot whose description matches the line'],
 base_clip:['Base clip','Moving place or police footage that fits'],photo:['Photo','The named victim, suspect or family member'],still:['Still','A still picture'],continue:['Continues','The same scene keeps running while the narration stays on it'],
 scripted:["Script's own","The script's window: nothing better was found"],weak:['Weak','Best available, but a poor match: check it'],uncovered:['Uncovered','No picture yet']};
function vpClock(ms){const s=ms/1000,m=Math.floor(s/60);return `${m}:${(s-m*60).toFixed(1).padStart(4,'0')}`}

function visualPlanCardHTML(){return P?.edit_mode==='documentary'?`<section class="card setup-card setup-footage" id="visual-plan-card">${vpInnerHTML()}</section>`:''}
function vpInnerHTML(){
 const d=window.vpFor===P?.id?window.vpData:null;
 const head=`<div class="setup-card-heading"><span class="setup-step">08</span><h3>Visual plan: pictures that match the narration</h3><span class="setup-status ${d?.plan&&!d.stale?'ready':''}">${!d?'Loading…':d.plan?(d.stale?'Out of date':'Plan ready'):'Not built'}</span></div>
  <p>Matches moving footage to every line of your narration, using what each shot is known to show (your guide's descriptions, the b-roll catalogue, local analysis, the script's directions). While the narration stays on the same idea the same shot keeps running. When a victim, suspect or family member is named, their photo from People on screen is shown, or footage of them when there is some. No other stills are used. Sound bites are kept exactly as they are.</p>`;
 if(!d){vpRefresh();return head}
 const st=d.settings||{},plan=d.plan;
 const caps=(d.still_caps||[0.1,0.2,0.35]).map(c=>`<option value="${c}"${Math.abs(c-(st.still_cap||0.1))<1e-6?' selected':''}>${Math.round(c*100)}% of the film</option>`).join('');
 const controls=`<div class="inline vp-controls"><label>Photo limit<select onchange="vpBuild(Number(this.value))">${caps}</select></label>
  <button class="${plan&&!d.stale?'':'new'}" type="button" onclick="vpBuild()" ${d.has_source?'':'disabled'}>${plan?'Build the plan again':'Build the visual plan'}</button>
  ${plan?`<button class="new" type="button" onclick="vpApply()" ${d.stale?'disabled':''}>Use this plan</button><a class="download" href="/api/projects/${P.id}/visual-plan/script">Download plan script</a><a class="download" href="/api/projects/${P.id}/visual-plan/missing" title="Lines still showing a stand-in picture, to paste into the Footage Gap Fill prompt">Download missing-footage list</a>`:''}
  ${d.applied?`<button type="button" onclick="vpRestore()">Restore my original script</button>`:''}</div>
  ${d.has_source?'':'<p class="small">Upload the production script (a Beat script or a card editing guide) and the SRT first.</p>'}
  ${d.stale&&plan?'<div class="notice warn">The script, footage, people or settings changed since this plan was built. Build it again before using it.</div>':''}
  ${d.applied?`<div class="notice">This plan is the production script now. Review it with <strong>Review the Beat picture plan</strong> as usual; your original script is kept and can be restored.</div>`:''}`;
 if(!plan)return head+controls;
 const total=plan.narration_ms||1,c=plan.counts_ms||{};
 const order=['guide','match','continue','base_clip','photo','still','scripted','weak','uncovered'];
 const bar=`<div class="vp-bar">${order.filter(k=>c[k]).map(k=>`<span class="vp-seg vp-${k}" style="width:${100*c[k]/total}%" title="${VP_KIND[k][0]}: ${(c[k]/1000).toFixed(0)}s"></span>`).join('')}</div>
  <div class="vp-legend">${order.filter(k=>c[k]).map(k=>`<span><i class="vp-dot vp-${k}"></i>${VP_KIND[k][0]} ${(c[k]/1000).toFixed(0)}s (${Math.round(100*c[k]/total)}%)</span>`).join('')}</div>
  <p class="small">Photos ${(plan.still_ms/1000).toFixed(0)}s of the ${(plan.still_cap_ms/1000).toFixed(0)}s allowed. Catalogue: ${plan.catalogue.items} described shots and pictures (${Object.entries(plan.catalogue.by_source||{}).map(([k,v])=>`${v} from ${{guide:'the guide',catalog:'the b-roll catalogue',analysis:'local analysis',script:'the script',base_still:'base stills',base_clip:'base clips',person_photo:'People photos'}[k]||k}`).join(', ')}).</p>`;
 const missing=(plan.catalogue.unavailable_files||[]).length?`<div class="notice warn">Described in the guide but not in this production yet: ${plan.catalogue.unavailable_files.map(E).join(', ')}. Download or upload them, then build the plan again.</div>`:'';
 const uncovered=plan.rows.filter(r=>r.pieces.some(p=>p.kind==='uncovered'));
 const uncoveredNote=uncovered.length?`<div class="notice warn"><strong>${uncovered.length} line${uncovered.length>1?'s have':' has'} no picture yet.</strong> ${E(uncovered[0].pieces.find(p=>p.kind==='uncovered').reason)}</div>`:'';
 const rows=plan.rows.map(r=>{
  const pics=r.pieces.map(p=>`<div class="vp-pic"><span class="vp-badge vp-${p.kind}" title="${E(VP_KIND[p.kind]?.[1]||'')}">${E(VP_KIND[p.kind]?.[0]||p.kind)}</span> ${p.file?`<code>${E(p.file)}</code> ${p.in_ms!=null?vpClock(p.in_ms):''} · ${((p.end_ms-p.start_ms)/1000).toFixed(1)}s`:''}<div class="small">${E(p.text||'')}</div></div>`).join('');
  const why=r.pieces.map(p=>E(p.reason||'')).join('<br>');
  const alt=(r.pieces.find(p=>p.kind!=='guide'&&p.alternatives?.length)||{}).alternatives||[];
  const over=(P.visual_plan_overrides||{})[String(r.start_ms)];
  const select=alt.length?`<select class="vp-choose" onchange="vpChoose(${r.start_ms},this.value)"><option value="">Automatic choice</option>${alt.map(a=>`<option value="${E(a.item)}"${over===a.item?' selected':''}>${E(a.file)} · ${E(a.text.slice(0,60))} (${a.score})</option>`).join('')}</select>`:'';
  return `<tr class="${r.pieces.some(p=>p.kind==='uncovered'||p.kind==='weak')?'vp-flag':''}"><td>${vpClock(r.start_ms)}</td><td class="vp-text">${E(r.text)}${r.hint?`<div class="small">Fill: ${E(r.hint)}</div>`:''}</td><td>${pics}${select}</td><td class="small">${why}</td></tr>`}).join('');
 return head+controls+bar+missing+uncoveredNote+`<details${uncovered.length?' open':''}><summary>Every line (${plan.rows.length})</summary><div class="vp-table-wrap"><table class="vp-table"><thead><tr><th>Time</th><th>Narration</th><th>Picture</th><th>Why</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}
function vpPaint(){const n=$('#visual-plan-card');if(n)n.innerHTML=vpInnerHTML()}
async function vpRefresh(){if(!P||window.vpBusy)return;window.vpBusy=true;try{const id=P.id,d=await api(`/api/projects/${id}/visual-plan`);if(P?.id!==id)return;window.vpData=d;window.vpFor=id;vpPaint()}catch(e){}finally{window.vpBusy=false}}
async function vpCall(url,body,label){
 const n=$('#visual-plan-card');if(n)n.classList.add('vp-working');toast(label||'Working…');
 try{const d=await api(url,'POST',body||{});if(d.project){P=d.project;window.vpData=d.visual_plan}else window.vpData=d;window.vpFor=P.id;
  if(d.project){renderManagement();if(typeof renderProgram==='function')renderProgram()}else vpPaint();return d}
 catch(e){toast(e.message)}finally{const m=$('#visual-plan-card');if(m)m.classList.remove('vp-working')}
}
function vpBuild(cap){return vpCall(`/api/projects/${P.id}/visual-plan`,cap?{still_cap:cap}:{},'Matching pictures to the narration…')}
async function vpChoose(start,item){const d=await vpCall(`/api/projects/${P.id}/visual-plan/choose`,{start_ms:start,item:item||null},'Planning around your choice…');if(d){try{P=await api('/api/projects/'+P.id)}catch{}}}
async function vpApply(){if(!confirm('Use this plan as the production script? Stills are made into hold clips and added to your footage. Your original script is kept and can be restored.'))return;const d=await vpCall(`/api/projects/${P.id}/visual-plan/apply`,{},'Making stills and applying the plan…');if(d?.project)toast('Plan applied. Review the Beat picture plan next.')}
async function vpRestore(){if(!confirm('Put your original production script back?'))return;await vpCall(`/api/projects/${P.id}/visual-plan/restore`,{},'Restoring…')}

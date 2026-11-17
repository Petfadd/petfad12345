/* Transitions for Beat-built documentaries.

   A Beat timeline is split at every subtitle line, so most scene boundaries are not
   picture cuts. This dialog works on the REAL cuts only -- where the footage changes --
   and lets you put any transition on one cut, the same one on every cut, or let Auto
   choose a different one for each. The script's own "Cut action" lines can be
   re-applied at any time. Timing never changes: a transition overlaps the outgoing
   shot onto the first frames of the next one. */
(function(){
 const isBeatDoc=()=>P?.edit_mode==='documentary'&&!!P?.documentary_beat_review&&(P.scenes||[]).length>0;
 let docTr={cuts:[],catalogue:null,styles:[],index:0,scope:'one',style:'balanced',duration:'standard'};

 function fmtAt(s){s=Math.max(0,s||0);const m=Math.floor(s/60),x=Math.floor(s%60);return `${m}:${String(x).padStart(2,'0')}`}
 function labelOf(key){const t=(docTr.catalogue?.transitions||[]).find(x=>x.key===key);return t?t.label:key}

 // The cut that closes the shot holding the selected scene.
 function cutForScene(id){
  const i=(P.scenes||[]).findIndex(s=>s.id===id);if(i<0)return 0;
  const n=docTr.cuts.findIndex(c=>c.scene_index>=i);return n<0?Math.max(0,docTr.cuts.length-1):n;
 }

 async function load(){
  const data=await api(`/api/projects/${P.id}/documentary-transitions`);
  docTr.cuts=data.cuts||[];docTr.catalogue=data.catalogue;docTr.styles=data.styles||[];
 }

 function render(){
  const body=$('#transition-body'),target=$('#transition-target'),controls=document.querySelector('#transition-dialog .transition-controls');
  if(!body||!target||!controls)return;
  // Auto and the bulk actions belong above the 24 cards, where they are seen first.
  if(controls.nextElementSibling!==body)body.parentNode.insertBefore(controls,body);
  const cut=docTr.cuts[docTr.index];
  const used={};docTr.cuts.forEach(c=>{if(c.transition!=='cut')used[c.transition]=(used[c.transition]||0)+1});
  const summary=Object.keys(used).length?Object.entries(used).map(([k,v])=>`${v} ${labelOf(k)}`).join(' · '):'all hard cuts';
  target.innerHTML=docTr.cuts.length?`
   <div class="doc-tr-head">
    <div class="doc-tr-nav">
     <button type="button" onclick="docTrStep(-1)" ${docTr.index>0?'':'disabled'} aria-label="Previous cut">◀</button>
     <strong>Cut ${docTr.index+1} of ${docTr.cuts.length}</strong>
     <button type="button" onclick="docTrStep(1)" ${docTr.index<docTr.cuts.length-1?'':'disabled'} aria-label="Next cut">▶</button>
     <span>at ${fmtAt(cut.at_s)} · ${E(cut.from)} → ${E(cut.to)}${cut.into_speaker?' · into a sound bite':''}</span>
     <button type="button" onclick="docTrSeek()">▶ Watch this cut</button>
    </div>
    <div class="doc-tr-scope">
     <label><input type="radio" name="doc-tr-scope" value="one" ${docTr.scope==='one'?'checked':''} onchange="docTrScope('one')"> This cut</label>
     <label><input type="radio" name="doc-tr-scope" value="all" ${docTr.scope==='all'?'checked':''} onchange="docTrScope('all')"> Every cut (${docTr.cuts.length})</label>
     <span class="small">Now: ${E(summary)}</span>
    </div>
   </div>`:'This timeline has no picture cuts to put a transition on.';
  const current=cut?.transition||'cut';
  body.innerHTML=(docTr.catalogue?.transitions||[]).map(t=>`
   <button type="button" class="transition-card t-${t.key} ${docTr.scope==='one'&&t.key===current?'current':''}" onclick="docTrChoose('${t.key}')">
    <span class="transition-preview"><span></span></span>
    <strong>${E(t.label)}</strong><small>${E(t.detail)}</small>
    ${docTr.scope==='one'&&t.key===current?`<em>${cut?.source==='script'?'From the script':cut?.source==='auto'?'Chosen by Auto':'In use'}</em>`:''}
   </button>`).join('');
  controls.innerHTML=`
   <label>Length<select onchange="docTrDuration(this.value)">
    ${(docTr.catalogue?.durations||[]).map(d=>`<option value="${d.key}" ${d.key===docTr.duration?'selected':''}>${E(d.label)}</option>`).join('')}
   </select></label>
   <label>Auto style<select onchange="docTrStyle(this.value)">
    ${docTr.styles.map(s=>`<option value="${s.key}" ${s.key===docTr.style?'selected':''}>${E(s.label)}</option>`).join('')}
   </select></label>
   <button type="button" class="new" onclick="docTrAuto(this)">Auto · a different transition per cut</button>
   <button type="button" onclick="docTrApply({action:'script'})">Use the script's Cut actions</button>
   <button type="button" onclick="docTrApply({action:'clear'})">All hard cuts</button>
   ${docTr.applied?`<p class="doc-tr-applied" style="flex-basis:100%;margin:0">✓ ${E(docTr.applied)}</p>`:''}
   <p class="small" style="flex-basis:100%;margin:0">Transitions never move a cut or change the film's length. Cuts into a person speaking get soft transitions from Auto.</p>`;
 }

 window.docTrState=()=>docTr;
 window.docTrStep=d=>{docTr.index=Math.max(0,Math.min(docTr.cuts.length-1,docTr.index+d));render()};
 window.docTrScope=s=>{docTr.scope=s;render()};
 window.docTrStyle=s=>{docTr.style=s};
 window.docTrDuration=d=>{docTr.duration=d};
 window.docTrSeek=()=>{const c=docTr.cuts[docTr.index];if(!c)return;closeTransitionLibrary();if(typeof docSeekTimeline==='function'){docSeekTimeline(Math.max(0,c.at_s-2),false);setTimeout(()=>{if(typeof docPlayTimeline==='function')docPlayTimeline()},250)}};
 window.docTrChoose=key=>{
  const cut=docTr.cuts[docTr.index];
  if(docTr.scope==='all')return docTrApply({action:'all',key,duration:docTr.duration});
  if(!cut)return;return docTrApply({action:'set',key,scene_id:cut.scene_id,duration:docTr.duration});
 };
 // Each press reshuffles the style's transitions, so Auto always gives a fresh mix.
window.docTrAuto=async function(button){
  if(button){button.disabled=true;button.textContent='Choosing transitions…'}
  const style=docTr.style,label=(docTr.styles.find(x=>x.key===style)||{}).label||style;
  await docTrApply({action:'auto',style,duration:docTr.duration,seed:Math.floor(Math.random()*2**31)||1});
  docTr.applied=`Auto applied · ${label} · ${docTr.cuts.filter(c=>c.transition!=='cut').length} of ${docTr.cuts.length} cuts now have a transition. Press again for a different mix.`;
  render();
 };
window.docTrApply=async function(body){
  try{
   const data=await api(`/api/projects/${P.id}/documentary-transitions`,'POST',body);
   P=data.project;docTr.cuts=data.cuts||[];if(body.action!=='auto')docTr.applied='';
   const parts=Object.entries(data.summary||{}).map(([k,v])=>`${v} ${labelOf(k)}`);
   toast(parts.length?`Transitions set: ${parts.join(', ')}.`:'Every cut is a hard cut.');
   render();renderInspector?.();renderProject?.();
  }catch(e){toast(e.message)}
 };

 // Take over the existing Transitions button for Beat documentaries only.
 const generalOpen=window.openTransitionLibrary;
 window.openTransitionLibrary=async function(sceneId){
  const controls=document.querySelector('#transition-dialog .transition-controls');
  if(controls&&!controls.dataset.general)controls.dataset.general=controls.innerHTML;
  if(!isBeatDoc()){
   if(controls&&controls.dataset.general)controls.innerHTML=controls.dataset.general;
   const body=$('#transition-body');if(controls&&body&&body.nextElementSibling!==controls)body.after(controls);
   return generalOpen(sceneId)}
  try{await load()}catch(e){toast(e.message);return}
  docTr.index=cutForScene(sceneId||scenes()[sceneIndex]?.id);
  render();
  const dlg=$('#transition-dialog');if(dlg&&!dlg.open)dlg.showModal();
 };
})();

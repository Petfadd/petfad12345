// People on screen: a photo appears over the playing picture when the narration names
// someone. Timing comes from the SRT; the same image is used by the monitor and the export.

function personOverlayData(){return P?.person_overlays||{windows:[],people:[],notes:[],settings:{},moments:{}}}
function personMs(ms){const s=Math.max(0,ms/1000),m=Math.floor(s/60);return `${m}:${String(Math.floor(s-m*60)).padStart(2,'0')}`}
const PERSON_ROLES=['Victim','Suspect','Mother','Father','Brother','Sister','Grandmother','Grandfather','Boyfriend','Girlfriend','Wife','Husband','Son','Daughter','Aunt','Uncle','Cousin','Witness','Detective','Lawyer'];

// People on screen. A person's photo is shown whenever the narration says their name.
// Add people here (or with P-rows in the footage sheet). Every line that names them is
// listed under them, so the right person can be checked line by line before export.
function peopleCardHTML(){
 if(P?.edit_mode!=='documentary')return '';
 const data=personOverlayData(),conf=data.settings||{},people=P.people||[],moments=data.moments||{};
 const info=Object.fromEntries((data.people||[]).map(x=>[x.id,x]));
 const opt=(value,label,current)=>`<option value="${value}"${value===current?' selected':''}>${label}</option>`;
 const mark=(text,said)=>{const i=text.toLowerCase().indexOf(String(said).toLowerCase());return i<0?E(text):E(text.slice(0,i))+'<mark>'+E(text.slice(i,i+said.length))+'</mark>'+E(text.slice(i+said.length))};
 const rows=people.map(person=>{
  const i=info[person.id]||{},photo=!!(person.photo&&i.has_photo),list=moments[person.id]||[];
  const shown=list.filter(m=>!m.blocked).length,check=list.filter(m=>m.short&&!m.blocked).length;
  const same=(i.same_photo_as||[]);
  const status=!photo?'<span class="person-status warn">No photo</span>':person.show===false?'<span class="person-status">Off</span>':`<span class="person-status ready">on screen ${shown}×</span>`;
  const sameNote=photo&&same.length?`<p class="person-flag warn">Same photo as ${E(same.join(', '))}: this is a group picture, not ${E(person.name)}'s own. Replace it with their own photo, or untick Show photo.</p>`:'';
  const items=list.map(m=>{
   const off=m.blocked==='turned off for this line',other=m.blocked&&!off;
   return `<li class="${m.blocked?'person-moment-off':''}">
    <label class="check"><input type="checkbox" ${m.blocked?'':'checked'} ${other?'disabled':''} onchange="togglePersonLine('${person.id}',${m.cue},this.checked)"></label>
    <span class="small">line ${m.cue} · ${personMs(m.ms)}</span> “${mark(m.text,m.said)}”
    ${m.blocked?'':m.footage?'<span class="person-flag good">footage of them plays here</span>':'<span class="person-flag">photo</span>'}
    ${m.via?`<span class="person-flag">about ${E(m.via)}'s ${E(person.role||'relative').toLowerCase()}</span>`:''}
    ${m.short&&!m.blocked?'<span class="person-flag warn">first name or surname only: check it is them</span>':''}
    ${other?`<span class="person-flag">${E(m.blocked)}</span>`:''}</li>`}).join('');
  return `<div class="person-row">
   <div class="person-thumb">${photo?`<img src="/api/projects/${P.id}/people/${person.id}/photo?v=${encodeURIComponent(person.photo.uploaded||'')}" alt="">`:'<span>No photo</span>'}</div>
   <form class="person-form" onsubmit="savePerson(event,'${person.id}')">
    <div class="person-head"><strong>${E(person.name)}</strong>${person.role?` <span class="small">${E(person.role)}</span>`:''} ${status}</div>
    ${sameNote}
    <div class="person-fields">
     <label>Name<input name="name" value="${E(person.name)}" required></label>
     <label>Role<input name="role" list="person-roles" value="${E(person.role||'')}" placeholder="Victim, Suspect, Mother…"></label>
     <label class="wide">How the SRT spells it <span class="small">(comma separated; found automatically)</span><input name="aliases" value="${E((person.aliases||[]).join(', '))}"></label>
     <label class="wide">Not this person <span class="small">(phrases to ignore, e.g. Harris County)</span><input name="exclude" value="${E((person.exclude||[]).join(', '))}"></label>
    </div>
    <div class="inline">
     <label class="file-button">${photo?'Replace photo':'Upload photo'}<input type="file" name="photo" accept="image/*,.heic,.heif,.avif" onchange="savePersonForm(this.form,'${person.id}')"></label>
     <label class="check"><input type="checkbox" name="show" ${person.show===false?'':'checked'} onchange="savePersonForm(this.form,'${person.id}')"> Show photo</label>
     <label class="check"><input type="checkbox" name="short_names" ${person.short_names===false?'':'checked'} onchange="savePersonForm(this.form,'${person.id}')"> First name or surname alone counts</label>
     <button type="submit">Save</button>
     <button type="button" onclick="findPersonSpellings('${person.id}')">Find SRT spellings</button>
     ${photo?`<button type="button" onclick="previewPersonCard('${person.id}')">See how it looks</button>`:''}
     <button type="button" onclick="removePerson('${person.id}')">Remove</button>
    </div>
    ${list.length?`<details class="person-moments" ${check?'open':''}><summary>${list.length} line${list.length===1?'':'s'} name ${E(person.name)}${check?` · <span class="warn">${check} to check</span>`:''} — untick a line to keep the photo off it</summary><ul>${items}</ul></details>`:'<p class="small">The narration never names them yet. Check the spelling against your SRT.</p>'}
   </form></div>`}).join('');
 const notes=(data.notes||[]).map(n=>`<li>${E(n)}</li>`).join('');
 const total=(data.windows||[]).length;
 return `<section class="card setup-card setup-footage people-card"><div class="setup-card-heading"><span class="setup-step">07</span><h3>People on screen</h3><span class="setup-status ${total?'ready':''}">${total} photo${total===1?'':'s'} on screen</span></div>
  <p>Add the victim, suspect and family with a photo. Whenever <strong>your narration</strong> says their name, their photo is shown ${conf.style==='card'?'as a card over the footage':'full screen'} ${conf.timing==='fixed'?`for ${(conf.hold_ms/1000)} seconds`:'for the whole SRT line'}; sound bites are never covered. In the opening every mention pops their photo up; after it, footage that shows them keeps playing and their photo is used only where there is no footage of them (and always the first time someone is named). Every line that names someone is listed under them: untick a line to keep the photo off it. A line like “Jane's mother…” shows the mother, not Jane. P-rows in the footage sheet add people here too.</p>
  <p class="small">You confirm who is in each photo and that you may use it. The editor does not check identity, source or publication rights.</p>
  <div class="inline person-settings">
   <label class="check"><input type="checkbox" ${conf.enabled===false?'':'checked'} onchange="savePersonSettings({enabled:this.checked})"> Show photos in preview and export</label>
   <label>Show photo<select onchange="savePersonSettings({style:this.value})">${opt('full','Full screen',conf.style)}${opt('card','Corner card',conf.style)}</select></label>
   ${conf.style!=='card'?`<label>Photo motion<select onchange="savePersonSettings({photo_motion:this.value})">${opt('none','Still',conf.photo_motion||'none')}${opt('zoom_in','Slow zoom in',conf.photo_motion)}${opt('zoom_out','Slow zoom out',conf.photo_motion)}${opt('pan_left','Pan left',conf.photo_motion)}${opt('pan_right','Pan right',conf.photo_motion)}${opt('pan_up','Pan up',conf.photo_motion)}${opt('pan_down','Pan down',conf.photo_motion)}</select></label>
   ${(conf.photo_motion||'none')!=='none'?`<label>Strength<select onchange="savePersonSettings({photo_motion_intensity:this.value})">${opt('subtle','Subtle',conf.photo_motion_intensity)}${opt('medium','Medium',conf.photo_motion_intensity)}${opt('strong','Strong',conf.photo_motion_intensity)}</select></label>`:''}`:''}
   <label>For<select onchange="savePersonSettings({timing:this.value})">${opt('cue','The whole SRT line',conf.timing)}${opt('fixed','A fixed time',conf.timing)}</select></label>
   ${conf.timing==='fixed'?`<label>Stays up<select onchange="savePersonSettings({hold_ms:Number(this.value)})">${[2500,3500,5000,7000].map(v=>opt(v,(v/1000)+' s',conf.hold_ms)).join('')}</select></label>`:''}
   <label>Photos pop up<select onchange="savePersonSettings({photo_opening:this.value})">${opt('scene1','Every mention in the first scene',conf.photo_opening)}${opt('scene2','Every mention in the first two scenes',conf.photo_opening)}${opt('half','Every mention in the first half',conf.photo_opening)}${opt('always','Every mention, all film',conf.photo_opening)}</select></label>
   <label class="check"><input type="checkbox" ${conf.show_label===false?'':'checked'} onchange="savePersonSettings({show_label:this.checked})"> Show name and role</label>
   ${P.visual_plan_applied?`<label class="check"><input type="checkbox" ${conf.with_visual_plan?'checked':''} onchange="savePersonSettings({with_visual_plan:this.checked})"> Also show name cards with the visual plan</label>`:''}
  </div>
  ${notes?`<details><summary>Notes (${(data.notes||[]).length})</summary><ul class="issues">${notes}</ul></details>`:''}
  ${rows||'<p class="muted">No people yet.</p>'}
  <datalist id="person-roles">${PERSON_ROLES.map(r=>`<option value="${r}">`).join('')}</datalist>
  <form class="person-row person-add" onsubmit="addPerson(event)">
   <div class="person-fields">
    <label>Name as the narration says it<input name="name" required placeholder="Full name"></label>
    <label>Role<input name="role" list="person-roles" placeholder="Victim, Suspect, Mother…"></label>
    <label class="wide">Photo <span class="small">(any photo file)</span><input type="file" name="photo" accept="image/*,.heic,.heif,.avif"></label>
   </div>
   <div class="inline"><button class="new" type="submit">＋ Add person</button></div>
  </form>
 </section>`;
}

async function personRequest(url,method,body){
 try{P=await api(url,method,body);if(typeof renderManagement==='function')renderManagement();return true}
 catch(e){toast(e.message);return false}
}
function personFormData(form,id){
 const f=new FormData();if(id)f.append('id',id);
 for(const key of ['name','role','aliases','exclude']){const el=form.elements[key];if(el)f.append(key,el.value)}
 for(const key of ['show','short_names']){const el=form.elements[key];if(el)f.append(key,el.checked?'1':'0')}
 const file=form.elements.photo?.files?.[0];if(file)f.append('photo',file);
 return f;
}
async function savePerson(event,id){event.preventDefault();if(await personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(event.target,id)))toast('Saved.')}
function savePersonForm(form,id){return personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(form,id))}
async function addPerson(event){event.preventDefault();const form=event.target;if(!form.elements.photo.files.length&&!confirm('Add this person without a photo? Nothing can show until you upload one.'))return;if(await personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(form,'')))toast('Added. Their lines are listed under them.')}
async function removePerson(id){const person=(P.people||[]).find(x=>x.id===id);if(!confirm(`Remove ${person?.name||'this person'} and their photo from this production?`))return;await personRequest(`/api/projects/${P.id}/people/${id}`,'DELETE')}
function savePersonSettings(change){return personRequest(`/api/projects/${P.id}`,'PATCH',{person_overlay_settings:change})}
function previewPersonCard(id){window.open(`/api/projects/${P.id}/people/${id}/card.png?v=${Date.now()}`,'_blank')}
function togglePersonLine(id,cue,on){
 const person=(P.people||[]).find(x=>x.id===id);if(!person)return;
 const skip=new Set((person.skip_cues||[]).map(Number));if(on)skip.delete(cue);else skip.add(cue);
 const f=new FormData();f.append('id',id);f.append('name',person.name);f.append('skip_cues',[...skip].join(','));
 return personRequest(`/api/projects/${P.id}/people`,'POST',f);
}
function findPersonSpellings(id){
 const person=(P.people||[]).find(x=>x.id===id);if(!person)return;
 const f=new FormData();f.append('id',id);f.append('name',person.name);f.append('find_spellings','1');
 return personRequest(`/api/projects/${P.id}/people`,'POST',f).then(ok=>ok&&toast('SRT spellings added where found.'));
}

function personOverlayAt(t){
 const data=personOverlayData();if(data.settings?.enabled===false)return null;
 const ms=t*1000;return (data.windows||[]).find(w=>ms>=w.start_ms&&ms<w.end_ms)||null;
}
function updatePersonOverlay(t){
 const frame=$('#monitor-frame');if(!frame)return;
 let node=$('#person-overlay');
 if(!node){node=document.createElement('img');node.id='person-overlay';node.alt='';node.className='person-overlay';
  const captions=$('#editor-captions');frame.insertBefore(node,captions||null)}
 const w=(window.docTimelineData?.status==='ready')?personOverlayAt(t):null,g=personOverlayData().geometry;
 const cam=w&&window.Cinematic?(personOverlayData().cameras||{})[w.person_id]:null;
 personMotionOverlay(frame,w,g,cam,t);
 // This runs on every frame: touch the page only when something actually changes,
 // or each frame repaints the monitor and the video stutters.
 if(!w||!g||cam){if(node.classList.contains('on'))node.classList.remove('on');return}
 const src=`/api/projects/${P.id}/people/${w.person_id}/card.png?v=${encodeURIComponent(personOverlayData().updated||'')}`;
 if(node.dataset.src!==src){node.dataset.src=src;node.src=src}
 // The monitor frame is not always the output shape; the picture is fitted inside it
 // (letterboxed), so place the card against the fitted picture, not the frame.
 const fw=frame.clientWidth,fh=frame.clientHeight,aspect=g.aspect||16/9;
 const pw=Math.min(fw,fh*aspect),ph=pw/aspect,ox=(fw-pw)/2,oy=(fh-ph)/2;
 const box=`${(ox+g.left*pw).toFixed(1)}|${(oy+g.top*ph).toFixed(1)}|${(g.width*pw).toFixed(1)}|${(g.height*ph).toFixed(1)}`;
 if(node._box!==box){node._box=box;const [l,tp,wd,ht]=box.split('|');node.style.left=l+'px';node.style.top=tp+'px';node.style.width=wd+'px';node.style.height=ht+'px'}
 if(!node.classList.contains('on'))node.classList.add('on');
}

// A moving full-screen photo: the photo layer is moved with the same camera arithmetic
// as the export (static/cinematic.js); the name label is a separate, still layer.
function personMotionOverlay(frame,w,g,cam,t){
 let box=$('#person-motion');
 if(!cam||!w||!g){if(box&&box.classList.contains('on'))box.classList.remove('on');return}
 if(!box){box=document.createElement('div');box.id='person-motion';box.className='person-motion';
  box.innerHTML='<img class="pm-photo" alt=""><img class="pm-label" alt="">';frame.insertBefore(box,$('#editor-captions')||null)}
 const v=encodeURIComponent(personOverlayData().updated||''),base=`/api/projects/${P.id}/people/${w.person_id}/card.png?v=${v}`;
 const photo=box.querySelector('.pm-photo'),label=box.querySelector('.pm-label');
 if(photo.dataset.src!==base+'&layer=photo'){photo.dataset.src=base+'&layer=photo';photo.src=photo.dataset.src;
  label.dataset.src=base+'&layer=label';label.src=label.dataset.src;label.onerror=()=>{label.style.display='none'};label.onload=()=>{label.style.display=''}}
 const fw=frame.clientWidth,fh=frame.clientHeight,aspect=g.aspect||16/9;
 const pw=Math.min(fw,fh*aspect),ph=pw/aspect,ox=(fw-pw)/2,oy=(fh-ph)/2;
 const pos=`${ox.toFixed(1)}|${oy.toFixed(1)}|${pw.toFixed(1)}|${ph.toFixed(1)}`;
 if(box._pos!==pos){box._pos=pos;Object.assign(box.style,{left:ox+'px',top:oy+'px',width:pw+'px',height:ph+'px'})}
 const next=Cinematic.camTransform(cam,Cinematic.slotProgress(w.start_ms,w.end_ms,t,30));
 if(photo.style.transform!==next)photo.style.transform=next;
 if(!box.classList.contains('on'))box.classList.add('on');
}

/* Shot Inspector: per-slot camera (animated zoom/pan) and the transition into the shot.
   Every control acts on the selected slots only. Nothing here moves a cut, a source
   range, narration or sound. The arithmetic lives in static/cinematic.js. */
let slotCameraPreview=null,camIntensity='medium',camFocusPick=null,camSaving=false,camCuts=null,camCutsKey='',camPreviewStop=null;

function camOf(s){return s?.camera||null}
function camBase(s){return Number(s?.picture_scale??P?.picture_scale??100)||100}
function camDefault(s){const b=camBase(s);return {zoom_start:b,zoom_end:b,x_start:.5,y_start:.5,x_end:.5,y_end:.5,easing:'ease-in-out',origin:'manual',locked:false}}
function camTarget(){const chosen=selectedScenes(),s=scenes()[sceneIndex];return chosen.find(x=>x.id===s?.id)||chosen[0]||null}
function camMixed(chosen){return new Set(chosen.map(x=>JSON.stringify(camOf(x)?{...camOf(x),locked:0,origin:0,reason:0}:null))).size>1}
function camMove(c){if(!c||!Cinematic.isActive(c))return 'static';
 if(c.zoom_end>c.zoom_start)return 'zoom_in';if(c.zoom_end<c.zoom_start)return 'zoom_out';
 if(c.x_end>c.x_start)return 'pan_right';if(c.x_end<c.x_start)return 'pan_left';
 if(c.y_end<c.y_start)return 'pan_up';if(c.y_end>c.y_start)return 'pan_down';return 'hold'}

async function camLoadCuts(){if(!P||P.edit_mode!=='documentary')return null;const key=P.id+':'+P.updated;if(camCuts&&camCutsKey===key)return camCuts;
 try{const d=await api(`/api/projects/${P.id}/documentary-transitions`);camCuts=d.cuts||[];camCutsKey=key}catch{camCuts=[]}return camCuts}
function camCutInto(s){if(!camCuts||!s)return null;const i=scenes().findIndex(x=>x.id===s.id);let found=null;for(const c of camCuts)if(c.scene_index<i)found=c;return found}

function docCameraHTML(s){
 if(P?.edit_mode!=='documentary'||!window.Cinematic)return '';
 const chosen=selectedScenes(),t=camTarget(),cam=(slotCameraPreview&&t&&slotCameraPreview.ids.has(t.id))?slotCameraPreview.camera:(camOf(t)||camDefault(t));
 const on=!!chosen.length,mixed=on&&camMixed(chosen),locked=on&&chosen.every(x=>camOf(x)?.locked),move=camMove(camOf(t));
 const ai=chosen.some(x=>camOf(x)?.origin==='ai');
 const moves=[['static','Static'],['zoom_in','Zoom in'],['zoom_out','Zoom out'],['pan_left','Pan ←'],['pan_right','Pan →'],['pan_up','Pan ↑'],['pan_down','Pan ↓']];
 const dis=on?'':'disabled';
 const zoomRow=(key,label)=>`<label class="cam-zoom">${label}<input type="range" min="100" max="200" step="1" value="${Math.round(cam[key])}" ${dis} oninput="camEdit('${key}',this.value,false)" onchange="camEdit('${key}',this.value,true)"><input type="number" min="100" max="200" step="1" value="${Math.round(cam[key])}" ${dis} aria-label="${label} percent" onchange="camEdit('${key}',this.value,true)"><span>%</span></label>`;
 const cut=camCutInto(s),cat=(transitionCatalogue?.transitions||[]).map(x=>[x.key,x.label]);
 const trSecs=cut?.frames?(cut.frames/30).toFixed(2):'0.50';
 if(camCuts===null||camCutsKey!==P.id+':'+P.updated)camLoadCuts().then(()=>{if($('#cam-panel'))renderInspector()});
 return `<div class="cam-panel" id="cam-panel">
  <div class="cam-head"><strong>Camera</strong><span>${on?chosen.length+' selected'+(mixed?' · mixed':''):'none selected'}${ai?' · AI':''}</span>
   <label class="cam-lock" title="A locked camera is never changed by AI or bulk actions"><input type="checkbox" ${locked?'checked':''} ${dis} onchange="camLock(this.checked)"> Lock</label></div>
  <div class="cam-moves">${moves.map(([k,l])=>`<button type="button" class="${k===move?'current':''}" ${dis} onclick="camApplyPreset('${k}')">${l}</button>`).join('')}</div>
  <div class="cam-row"><label>Intensity <select ${dis} onchange="camIntensity=this.value">${['subtle','medium','strong'].map(k=>`<option value="${k}" ${k===camIntensity?'selected':''}>${k[0].toUpperCase()+k.slice(1)}</option>`).join('')}</select></label>
   <label>Easing <select ${dis} onchange="camEdit('easing',this.value,true)">${Cinematic.EASINGS.map(k=>`<option value="${k}" ${k===cam.easing?'selected':''}>${k}</option>`).join('')}</select></label></div>
  ${zoomRow('zoom_start','Start zoom')}${zoomRow('zoom_end','End zoom')}
  <div class="cam-row"><span class="cam-focus">Focus ${Math.round(cam.x_start*100)},${Math.round(cam.y_start*100)} → ${Math.round(cam.x_end*100)},${Math.round(cam.y_end*100)}</span>
   <button type="button" ${dis} onclick="camPickFocus('start')" class="${camFocusPick==='start'?'current':''}">Set start</button><button type="button" ${dis} onclick="camPickFocus('end')" class="${camFocusPick==='end'?'current':''}">Set end</button></div>
  <div class="cam-row"><button type="button" ${t?'':'disabled'} onclick="camPreviewShot()">▶ Preview shot</button><button type="button" ${chosen.some(camOf)?'':'disabled'} onclick="camSave(null)">Remove</button><button type="button" ${(P.cinematic_undo||[]).length?'':'disabled'} onclick="camUndo()">Undo</button></div>
  ${cut?`<div class="cam-tr"><strong>Transition into this shot</strong>
   <div class="cam-row"><select id="cam-tr-key">${cat.map(([k,l])=>`<option value="${k}" ${k===cut.transition?'selected':''}>${E(l)}</option>`).join('')}</select>
    <label>Length <input id="cam-tr-secs" type="number" min="0.13" max="3" step="0.05" value="${trSecs}"> s</label></div>
   <div class="cam-row"><label class="cam-lock"><input id="cam-tr-lock" type="checkbox" ${cut.locked?'checked':''}> Lock</label><button type="button" onclick="camSetTransition()">Apply</button><span class="small">${cut.source==='auto'?'set by Auto':cut.source==='script'?'from the script':cut.source?'set by you':''}</span></div></div>`:''}
 </div>`}

function camWorking(){const t=camTarget();return {...((slotCameraPreview&&t&&slotCameraPreview.ids.has(t.id))?slotCameraPreview.camera:(camOf(t)||camDefault(t)))}}
function camShow(c){const chosen=selectedScenes();if(!chosen.length)return;slotCameraPreview={ids:new Set(chosen.map(x=>x.id)),camera:c};if(typeof docApplyPictureScale==='function')docApplyPictureScale()}
function camEdit(key,value,save){const c=camWorking();if(key==='easing')c.easing=value;else c[key]=Math.max(100,Math.min(200,Math.round(Number(value)||100)));camShow(c);if(save)camSave(c)}
function camApplyPreset(move){const t=camTarget();if(!t)return;const cur=camOf(t);
 const focus=cur?[cur.x_start,cur.y_start]:[.5,.5];
 if(move==='static'){camSave(null);return}
 const c=Cinematic.camPreset(move,camIntensity,focus,camBase(t));camShow(c);camSave(c)}
function camPickFocus(which){camFocusPick=camFocusPick===which?null:which;const frame=$('#monitor-frame');
 if(frame)frame.style.cursor=camFocusPick?'crosshair':'';renderInspector();if(camFocusPick)toast(`Click the picture where the ${which} of the move should look.`)}
document.addEventListener('click',e=>{if(!camFocusPick)return;const frame=e.target.closest('#monitor-frame');if(!frame)return;
 const r=frame.getBoundingClientRect(),u=(e.clientX-r.left)/r.width,v=(e.clientY-r.top)/r.height;
 // The click lands on the picture as currently framed: turn it back into a point of the full frame.
 const c=camWorking(),[z,cx,cy]=Cinematic.camWindow(c,camFocusPick==='start'?0:1);
 const fx=Math.min(1,Math.max(0,cx+(u-.5)/z)),fy=Math.min(1,Math.max(0,cy+(v-.5)/z));
 if(camFocusPick==='start'){c.x_start=+fx.toFixed(4);c.y_start=+fy.toFixed(4)}else{c.x_end=+fx.toFixed(4);c.y_end=+fy.toFixed(4)}
 camFocusPick=null;frame.style.cursor='';camShow(c);camSave(c)},true);

async function camSave(c,extra){const chosen=selectedScenes();if(!P||!chosen.length||camSaving)return;camSaving=true;const id=P.id;
 try{const body={scene_ids:chosen.map(x=>x.id),camera:c,...(extra||{})};const updated=await api(`/api/projects/${id}/scenes/camera`,'PATCH',body);
  if(P?.id!==id)return;P=updated;slotCameraPreview=null;toast(c===null?`Camera removed from ${chosen.length} slot(s).`:`Camera saved for ${chosen.length} slot(s). Render again to include it.`)}
 catch(e){slotCameraPreview=null;toast(e.message)}finally{camSaving=false;renderProject()}}
async function camLock(on){const chosen=selectedScenes();if(!chosen.length)return;
 if(chosen.some(x=>!camOf(x))){const c=camWorking();await camSave(c,{locked:on});return}
 const id=P.id;try{P=await api(`/api/projects/${id}/scenes/camera`,'PATCH',{scene_ids:chosen.map(x=>x.id),locked:on});toast(on?'Camera locked.':'Camera unlocked.')}catch(e){toast(e.message)}renderProject()}
async function camUndo(){const id=P.id;try{const r=await api(`/api/projects/${id}/cinematic/undo`,'POST');if(P?.id!==id)return;P=r;camCuts=null;toast(`Undid the last ${r.undone?.label||'change'} (${r.undone?.slots||0} slot(s)).`)}catch(e){toast(e.message)}renderProject()}
async function camSetTransition(){const s=scenes()[sceneIndex],key=$('#cam-tr-key')?.value,secs=Number($('#cam-tr-secs')?.value),locked=!!$('#cam-tr-lock')?.checked;
 if(!s||!key)return;const frames=Math.max(4,Math.min(90,Math.round((Number.isFinite(secs)?secs:.5)*30)));const id=P.id;
 try{const r=await api(`/api/projects/${id}/documentary-transitions`,'POST',{action:'set',scene_id:s.id,into:true,key,frames,locked});if(P?.id!==id)return;
  P=r.project||P;camCuts=r.cuts||null;camCutsKey=camCuts?P.id+':'+P.updated:'';toast('Transition saved. Render again to include it.')}catch(e){toast(e.message)}renderProject()}
function camPreviewShot(){const s=camTarget()||scenes()[sceneIndex];if(!s)return;const start=s.frame_in/30,end=s.frame_out/30;
 if(camPreviewStop)cancelAnimationFrame(camPreviewStop);
 if(typeof docSeekTimeline==='function')docSeekTimeline(start,false);
 setTimeout(()=>{playEditor();const tick=()=>{if(!editorPlaying){camPreviewStop=null;return}if(editorTime()>=end-.02){pauseEditor();camPreviewStop=null;return}camPreviewStop=requestAnimationFrame(tick)};camPreviewStop=requestAnimationFrame(tick)},120)}

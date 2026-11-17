/* Per-slot camera motion in the monitor: the same arithmetic as cinematic.py.
   A test (tests/test_cinematic.py) runs both and requires them to agree, so what the
   monitor shows is what the render draws. */
(function(root){
 const EASINGS=['linear','ease-in','ease-out','ease-in-out'];
 function ease(p,e){p=Math.min(1,Math.max(0,p));
  if(e==='ease-in')return p*p;if(e==='ease-out')return 1-(1-p)*(1-p);
  if(e==='ease-in-out')return .5-.5*Math.cos(Math.PI*p);return p}
 function camWindow(c,p){const e=ease(p,c.easing),z=(c.zoom_start+(c.zoom_end-c.zoom_start)*e)/100,
  half=.5/z,cx=c.x_start+(c.x_end-c.x_start)*e,cy=c.y_start+(c.y_end-c.y_start)*e;
  return [z,Math.min(1-half,Math.max(half,cx)),Math.min(1-half,Math.max(half,cy))]}
 function isActive(c){return !!c&&(c.zoom_start!==c.zoom_end||c.x_start!==c.x_end||c.y_start!==c.y_end||c.zoom_start!==100)}
 // Progress of a slot at time t (seconds, film clock): 0 on its first frame, 1 on its last.
 function slotProgress(inMs,outMs,t,fps){const frame=1000/(fps||30),span=outMs-inMs-frame;
  return span<=0?0:Math.min(1,Math.max(0,(t*1000-inMs)/span))}
 // CSS transform that shows the camera window of a full-frame layer.
 function camTransform(c,p){const [z,cx,cy]=camWindow(c,p);
  return `translate(${(-(cx-.5)*z*100).toFixed(4)}%,${(-(cy-.5)*z*100).toFixed(4)}%) scale(${z.toFixed(5)})`}
 const INTENSITY={subtle:[5,.03],medium:[10,.05],strong:[18,.08]};
 function camPreset(direction,intensity,focus,baseZoom){const [dz,dp]=INTENSITY[intensity]||INTENSITY.medium;
  const fx=focus?.[0]??.5,fy=focus?.[1]??.5,base=Math.max(100,Math.min(200,Math.round(baseZoom||100)));
  const c={zoom_start:base,zoom_end:base,x_start:fx,y_start:fy,x_end:fx,y_end:fy,easing:'ease-in-out'};
  if(direction==='zoom_in')c.zoom_end=Math.min(200,base+dz);
  else if(direction==='zoom_out')c.zoom_start=Math.min(200,base+dz);
  else if(['pan_left','pan_right','pan_up','pan_down'].includes(direction)){
   const z=Math.max(base,Math.min(200,Math.ceil(dp<.45?100/(1-2*dp):200)));c.zoom_start=c.zoom_end=z;
   const s={pan_left:[1,0],pan_right:[-1,0],pan_up:[0,1],pan_down:[0,-1]}[direction];
   c.x_start=fx+s[0]*dp;c.x_end=fx-s[0]*dp;c.y_start=fy+s[1]*dp;c.y_end=fy-s[1]*dp;c.easing='linear'}
  for(const k of ['x_start','x_end','y_start','y_end'])c[k]=Math.round(Math.min(1,Math.max(0,c[k]))*1e4)/1e4;
  return c}
 const api={EASINGS,ease,camWindow,isActive,slotProgress,camTransform,camPreset};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.Cinematic=api;
})(typeof window!=='undefined'?window:globalThis);

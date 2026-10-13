/* gr.HTML value is authoritative; edits emit a matrix without changing props. */
if (typeof element._atommovrPlayerCleanup === "function") element._atommovrPlayerCleanup();
let preferredSpeed = 1;
let currentCleanup = () => {};

function mountPlayer() {
  currentCleanup();
  const root = element.querySelector(".am-player");
  if (!root) return;
  const data = props.value && typeof props.value === "object" ? props.value : {};
  const preview = data.preview === true;
  const frames = !preview && Array.isArray(data.frames) ? data.frames : [];
  const n = Math.max(1, Number(data.n || data.config?.n || data.initial?.length || 10));
  const hasInitial = Array.isArray(data.initial) && data.initial.length === n && data.initial.every(row => Array.isArray(row) && row.length === n);
  let initial = hasInitial ? data.initial.map(row => row.slice()) : Array.from({length: n}, () => Array(n).fill(0));
  const target = data.target || Array.from({length: n}, () => Array(n).fill(0));
  const summary = data.summary || {};
  const resultError = summary.status === "invalid" || summary.status === "algorithm_error";
  const editable = preview && data.config?.initial_mode === "manual" && hasInitial && !resultError;
  const exportable = !preview && hasInitial && ["success", "incomplete", "blocked"].includes(summary.status);
  const countAtoms = (state) => (state || []).reduce((sum, row) => sum + row.reduce((v, cell) => v + (cell ? 1 : 0), 0), 0);
  const countFilled = (state) => (state || []).reduce((sum, row, r) => sum + row.reduce((v, cell, c) => v + (cell && target[r]?.[c] ? 1 : 0), 0), 0);
  let initialCount = summary.initial_count ?? countAtoms(initial);
  const targetCount = summary.target_count ?? countAtoms(target);
  const nonnegativeInteger = value => typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
  const configuredTweezers = data.config?.tweezer_count ?? summary.tweezer_count;
  const availableTweezers = nonnegativeInteger(configuredTweezers) > 0 ? configuredTweezers : 4;
  const tweezerId = move => nonnegativeInteger(move.tweezer_id) > 0 ? move.tweezer_id : null;
  function activeTweezerCount(frame) {
    if (!frame) return 0;
    const recorded = nonnegativeInteger(frame.active_tweezers);
    if (recorded !== null) return recorded;
    const ids = (frame.moves || []).map(tweezerId).filter(id => id !== null);
    return ids.length ? new Set(ids).size : (frame.moves || []).length ? null : 0;
  }
  const recordedPeak = nonnegativeInteger(summary.max_active_tweezers);
  const knownCounts = frames.map(activeTweezerCount).filter(value => value !== null);
  const peakTweezers = recordedPeak ?? (knownCounts.length ? Math.max(...knownCounts) : null);
  const checkedBatches = nonnegativeInteger(summary.collision_checked_batches);
  const canvas = root.querySelector(".am-canvas");
  const ctx = canvas.getContext("2d");
  const progress = root.querySelector(".am-progress");
  const speedControl = root.querySelector(".am-speed");
  const playButton = root.querySelector(".am-play");
  const replayButton = root.querySelector(".am-replay");
  const previousButton = root.querySelector(".am-previous");
  const nextButton = root.querySelector(".am-next");
  const exportButton = root.querySelector(".am-export");
  const exportStatus = root.querySelector(".am-export-status");
  exportStatus.textContent="";
  const stat = (name, value) => {const node=root.querySelector(`[data-stat="${name}"]`),text=String(value);if(node.textContent!==text)node.textContent=text;};
  const aborter = new AbortController();
  let index = 0, fraction = 0, playing = false, raf = 0, lastTime = null, disposed = false;
  let logicalSize = 0;
  let editPending = false, hoverCell = null;
  const downloadUrls = new Set(), downloadTimers = new Set();
  const speedText = (speed) => `${Number(speed.toFixed(2))}×`;
  speedControl.value = preferredSpeed;
  speedControl.disabled = preview || !hasInitial || !frames.length;
  progress.max = frames.length;
  progress.disabled = frames.length === 0;
  const mode = root.querySelector(".am-mode");
  mode.textContent = resultError ? "参数或仿真异常" : preview ? (editable ? "手动布置" : "参数预览") : data.config ? (data.config.noise ? "误差演示" : "理想重排") : "等待仿真";
  mode.dataset.noise = String(Boolean(data.config?.noise));
  root.querySelector(".am-stage-coordinates").textContent = `${n} × ${n} 阵列`;
  const result = root.querySelector(".am-result");
  result.dataset.status = resultError ? summary.status : preview ? "preview" : summary.status || "ready";
  root.querySelector(".am-result-icon").textContent = resultError ? "!" : preview ? "i" : summary.status === "success" ? "✓" : summary.status ? "!" : "◌";
  root.querySelector(".am-result-text").textContent = resultError ? (summary.message || "无法准备阵列或完成仿真，请检查参数。") : preview ? "当前为初态与目标预览。点击“运行仿真”生成移动轨迹。" : (summary.message ? "最终仿真结果：" + summary.message : "正在准备默认演示…");
  const editNote = root.querySelector(".am-edit-note");
  editNote.hidden = !editable;
  root.querySelector(".am-events").hidden = preview;

  function eventKind(move) {
    if (Number(move.flag) === 3 || Number(move.event) === 3 || move.event_name === "NO_ATOM") return "empty";
    if (Number(move.flag) === 1 || Number(move.event) === 1 || move.event_name === "PICKUP_FAIL") return "pickup";
    if (Number(move.flag) === 2 || (Number(move.event) >= 2 && Number(move.event) !== 3)) return "loss";
    return "success";
  }
  function occupied(state, point) {return Boolean(point && state[point[0]]?.[point[1]]);}
  function nonzeroMove(move) {return move.from[0] !== move.to[0] || move.from[1] !== move.to[1];}
  function key(point) {return `${point[0]},${point[1]}`;}
  function position(point, pad, pitch) {return {x: pad + point[1] * pitch, y: pad + point[0] * pitch};}
  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "0 µs";
    if (seconds < 0.001) return `${Number((seconds * 1e6).toFixed(1))} µs`;
    if (seconds < 1) return `${Number((seconds * 1e3).toFixed(2))} ms`;
    return `${Number(seconds.toFixed(3))} s`;
  }
  function dot(x, y, radius, color, alpha = 1, shape = "circle", prominent = false) {
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.fillStyle = color;ctx.strokeStyle = color==="#7e2f8e"?"#57215f":color==="#c63232"?"#8d2424":prominent ? "#7c2e0e" : shape === "triangle" ? "#936900" : "#00558a";ctx.lineWidth = prominent ? 1.4 : .8;
    ctx.beginPath();
    if(shape === "triangle"){ctx.moveTo(x,y-radius*1.25);ctx.lineTo(x+radius*1.15,y+radius*.8);ctx.lineTo(x-radius*1.15,y+radius*.8);ctx.closePath();}
    else ctx.arc(x,y,radius,0,Math.PI*2);
    ctx.fill();ctx.stroke();ctx.restore();
  }
  function arrow(from, to, color, pad, pitch) {
    const a = position(from, pad, pitch), b = position(to, pad, pitch);
    const distance = Math.hypot(b.x - a.x, b.y - a.y);
    if (distance < 1) return;
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    const head = Math.min(7, pitch * .25);
    ctx.save();ctx.strokeStyle = color;ctx.fillStyle = color;ctx.globalAlpha = fraction > 0 ? .9 : .65;ctx.lineWidth = fraction > 0 ? Math.max(1.5, pitch * .04) : 1.2;
    ctx.setLineDash(fraction > 0 ? [] : [3,3]);ctx.beginPath();ctx.moveTo(a.x, a.y);ctx.lineTo(b.x, b.y);ctx.stroke();ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(b.x,b.y);ctx.lineTo(b.x - head*Math.cos(angle-.5),b.y - head*Math.sin(angle-.5));ctx.lineTo(b.x-head*Math.cos(angle+.5),b.y-head*Math.sin(angle+.5));ctx.closePath();ctx.fill();ctx.restore();
  }
  function lossMarker(point, color, pad, pitch, alpha = 1, shape = "cross") {
    const p = position(point, pad, pitch), radius = Math.max(4, pitch * .19);
    ctx.save();ctx.globalAlpha = alpha;ctx.strokeStyle = color;ctx.lineWidth = Math.max(1.4, pitch*.045);
    ctx.beginPath();
    if(shape === "diamond"){ctx.moveTo(p.x,p.y-radius*1.4);ctx.lineTo(p.x+radius*1.4,p.y);ctx.lineTo(p.x,p.y+radius*1.4);ctx.lineTo(p.x-radius*1.4,p.y);ctx.closePath();}
    else{ctx.moveTo(p.x-radius,p.y-radius);ctx.lineTo(p.x+radius,p.y+radius);ctx.moveTo(p.x+radius,p.y-radius);ctx.lineTo(p.x-radius,p.y+radius);}
    ctx.stroke();ctx.restore();
  }
  function tweezerMarker(move, frame, phase, pad, pitch, radius, side) {
    const id = tweezerId(move);
    if (id === null || !Array.isArray(move.from) || !Array.isArray(move.to)) return;
    const a = position(move.from,pad,pitch),b = position(move.to,pad,pitch);
    const x = a.x+(b.x-a.x)*phase,y=a.y+(b.y-a.y)*phase;
    const kind = eventKind(move);
    const empty = !occupied(frame.before,move.from) || kind === "empty" || kind === "pickup" || phase >= 1 && (kind === "loss" || !occupied(frame.after,move.to));
    const ring = Math.max(4.5,radius*1.95);
    ctx.save();ctx.strokeStyle="#d95319";ctx.lineWidth=1.4;ctx.setLineDash(empty?[2.5,2.5]:[]);
    ctx.beginPath();ctx.arc(x,y,ring,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);
    const text=`T${id}`,fontSize=Math.max(8,Math.min(10,pitch*.28));
    const width=text.length*fontSize*.6+4;
    const labelX=Math.max(2,Math.min(side-width-2,x+ring+2)),labelY=Math.max(fontSize+2,y-ring-2);
    ctx.fillStyle="rgba(255,255,255,.96)";ctx.fillRect(labelX-1,labelY-fontSize,width,fontSize+3);
    ctx.fillStyle="#a43d13";ctx.font=`600 ${fontSize}px Arial, sans-serif`;ctx.textAlign="left";ctx.textBaseline="alphabetic";ctx.fillText(text,labelX+1,labelY);ctx.restore();
  }
  function plotMetrics(){const side=Math.max(1,logicalSize||canvas.getBoundingClientRect().width||480);const pad=Math.max(27,side*.075);return {side,pad,pitch:(side-pad*2)/Math.max(1,n-1)};}
  function cellAt(event){
    const rect=canvas.getBoundingClientRect(),{side,pad,pitch}=plotMetrics();
    if(!rect.width||!rect.height||pitch<=0)return null;
    const x=(event.clientX-rect.left)*side/rect.width,y=(event.clientY-rect.top)*side/rect.height;
    const c=Math.round((x-pad)/pitch),r=Math.round((y-pad)/pitch);
    if(r<0||r>=n||c<0||c>=n||Math.hypot(x-(pad+c*pitch),y-(pad+r*pitch))>Math.max(8,pitch*.42))return null;
    return [r,c];
  }
  function updateEvents(frame) {
    const container = root.querySelector(".am-event-text");
    container.replaceChildren();
    if (!frame) {container.textContent = "播放或单步查看每批原子的移动与损耗。";root.querySelector(".am-event-batch").textContent = "初始状态";root.querySelector(".am-loss-note").hidden=true;return;}
    const activeBatch = fraction > 0 ? index + 1 : index;
    root.querySelector(".am-event-batch").textContent = `第 ${activeBatch} / ${frames.length} 批`;
    const moves = frame.moves || [];
    const actual = moves.filter(move => occupied(frame.before, move.from));
    const successes = actual.filter(move => eventKind(move) === "success" && nonzeroMove(move)).length;
    const idle = actual.filter(move => eventKind(move) === "success" && !nonzeroMove(move)).length;
    const pickups = actual.filter(move => eventKind(move) === "pickup").length;
    const losses = actual.filter(move => eventKind(move) === "loss").length;
    const vacuum = (frame.vacuum_losses || []).length;
    const collisions = (frame.overlap_losses || []).length;
    const chips = [["success",`成功搬运命令 ${successes}`]];
    if(idle)chips.push(["idle",`原地动作 ${idle}`]);
    if (pickups) chips.push(["pickup",`拾取失败 ${pickups}`]);
    if (losses) {
      const putdowns = actual.filter(move => Number(move.event) === 2).length;
      const collisionEvents = actual.filter(move => [7,8].includes(Number(move.event))).length;
      if (putdowns) chips.push(["loss",`放下损失 ${putdowns}`]);
      if(collisionEvents)chips.push(["loss",`碰撞损失 ${collisionEvents}`]);
      if (losses > putdowns + collisionEvents) chips.push(["loss",`搬运损失 ${losses-putdowns-collisionEvents}`]);
    }
    if (vacuum) chips.push(["vacuum",`真空损耗 ${vacuum}`]);
    if (collisions) chips.push(["loss",`重叠损耗格点 ${collisions}`]);
    const emptyMoves = moves.length - actual.length;
    if (emptyMoves) chips.push(["empty",`空位动作 ${emptyMoves}`]);
    chips.forEach(([kind,text]) => {const span=document.createElement("span");span.className="am-event-chip";span.dataset.kind=kind;span.textContent=text;container.append(span);});
    root.querySelector(".am-loss-note").hidden=!(losses||vacuum||collisions);
  }
  let lastEventIdentity = null;
  function render() {
    if (disposed) return;
    const {side,pad,pitch}=plotMetrics();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(side * ratio) || canvas.height !== Math.round(side * ratio)) {canvas.width=Math.round(side*ratio);canvas.height=Math.round(side*ratio);}
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,side,side);
    const radius=Math.min(8,Math.max(2.5,pitch*.165));
    const completed = index > 0 ? frames[index-1] : null;
    const active = fraction > 0 && index < frames.length ? frames[index] : null;
    const frame = active || completed;
    const state = completed?.after || initial;
    const drawState = active?.before || state;
    const suppress = new Set();
    if (active) (active.moves||[]).forEach(move => {if (occupied(drawState,move.from) && (eventKind(move)==="loss" || eventKind(move)==="success"&&nonzeroMove(move))) suppress.add(key(move.from));});
    ctx.strokeStyle="#e5e5e5";ctx.lineWidth=.65;
    for(let k=0;k<n;k++){const p=pad+k*pitch;ctx.beginPath();ctx.moveTo(p,pad);ctx.lineTo(p,side-pad);ctx.moveTo(pad,p);ctx.lineTo(side-pad,p);ctx.stroke();}
    for(let r=0;r<n;r++) for(let c=0;c<n;c++) {
      const p=position([r,c],pad,pitch);
      if(target[r]?.[c]) {const h=radius*1.65;ctx.fillStyle="#f2f8f2";ctx.fillRect(p.x-h,p.y-h,h*2,h*2);ctx.strokeStyle="#388438";ctx.lineWidth=1.1;ctx.strokeRect(p.x-h,p.y-h,h*2,h*2);}
      ctx.strokeStyle="#a7a7a7";ctx.lineWidth=.65;ctx.beginPath();ctx.arc(p.x,p.y,Math.max(1.3,radius*.45),0,Math.PI*2);ctx.stroke();
    }
    ctx.strokeStyle="#777";ctx.lineWidth=.8;ctx.strokeRect(pad-7,pad-7,side-pad*2+14,side-pad*2+14);
    ctx.fillStyle="#4b4b4b";ctx.font=`${Math.max(8,Math.min(11,pitch*.35))}px Arial, sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";
    const stride=n>16?3:n>10?2:1;
    for(let k=0;k<n;k++)if(k%stride===0||k===n-1){ctx.fillText(String(k+1),pad+k*pitch,side-pad+17);ctx.fillText(String(k+1),pad-18,pad+k*pitch);}
    if(editable&&hoverCell&&!editPending){const p=position(hoverCell,pad,pitch),h=Math.max(radius*2,pitch*.32);ctx.strokeStyle="#777";ctx.lineWidth=.8;ctx.setLineDash([3,2]);ctx.strokeRect(p.x-h,p.y-h,h*2,h*2);ctx.setLineDash([]);}
    if(frame) (frame.moves||[]).forEach(move => {if(occupied(frame.before,move.from)&&eventKind(move)!=="empty")arrow(move.from,move.to,eventKind(move)==="loss"?"#c63232":eventKind(move)==="pickup"?"#ac7e00":"#d95319",pad,pitch);});
    const pickups = new Set((frame?.moves||[]).filter(move=>eventKind(move)==="pickup"&&occupied(frame.before,move.from)).map(move=>key(move.from)));
    const vacuum = new Set((active?.vacuum_losses||[]).map(key));
    const overlaps = new Set((active?.overlap_losses||[]).map(key));
    const moved = new Set(!active ? (completed?.moves||[]).filter(move=>eventKind(move)==="success"&&nonzeroMove(move)&&occupied(completed.before,move.from)).map(move=>key(move.to)) : []);
    for(let r=0;r<n;r++)for(let c=0;c<n;c++)if(drawState[r]?.[c]&&!suppress.has(`${r},${c}`)){
      const p=position([r,c],pad,pitch);const fades=active&&(vacuum.has(`${r},${c}`)||overlaps.has(`${r},${c}`))?Math.max(0,1-Math.max(0,fraction-.7)/.3):1;
      const pickup=pickups.has(`${r},${c}`),highlight=moved.has(`${r},${c}`);
      dot(p.x,p.y,highlight?radius*1.2:radius,vacuum.has(`${r},${c}`)?"#7e2f8e":overlaps.has(`${r},${c}`)?"#c63232":pickup?"#edb120":highlight?"#d95319":"#0072bd",fades,pickup?"triangle":"circle",highlight);
    }
    if(active) (active.moves||[]).forEach(move=>{
      if(!occupied(active.before,move.from))return;
      const kind=eventKind(move);if(kind!=="success"&&kind!=="loss")return;
      if(kind==="success"&&!nonzeroMove(move))return;
      const a=position(move.from,pad,pitch),b=position(move.to,pad,pitch);
      const vacuumLoss=kind==="success"&&vacuum.has(key(move.to)),overlapLoss=kind==="success"&&overlaps.has(key(move.to));
      const alpha=kind==="loss"?Math.max(0,1-Math.max(0,fraction-.65)/.35):vacuumLoss||overlapLoss?Math.max(0,1-Math.max(0,fraction-.7)/.3):1;
      dot(a.x+(b.x-a.x)*fraction,a.y+(b.y-a.y)*fraction,radius*1.35,vacuumLoss?"#7e2f8e":kind==="loss"||overlapLoss?"#c63232":"#d95319",alpha,"circle",true);
    });
    if(frame){
      (frame.moves||[]).forEach(move=>{if(eventKind(move)==="loss"&&occupied(frame.before,move.from))lossMarker(move.to,"#c63232",pad,pitch,active?Math.max(0,(fraction-.65)/.35):1);});
      (frame.vacuum_losses||[]).forEach(point=>lossMarker(point,"#7e2f8e",pad,pitch,active?Math.max(0,(fraction-.7)/.3):1,"diamond"));
      (frame.overlap_losses||[]).forEach(point=>lossMarker(point,"#c63232",pad,pitch,active?Math.max(0,(fraction-.7)/.3):1));
      (frame.moves||[]).forEach(move=>tweezerMarker(move,frame,active?fraction:1,pad,pitch,radius,side));
    }
    const counts=completed?.counts;
    const remaining=counts?.remaining??countAtoms(state);
    const filled=counts?.filled??countFilled(state);
    const elapsed=(completed?.elapsed||0)+(active?((active.elapsed||0)-(completed?.elapsed||0))*fraction:0);
    stat("initial",hasInitial?initialCount:"—");stat("remaining",hasInitial?remaining:"—");stat("filled",hasInitial?`${filled} / ${targetCount}`:"—");stat("fill-percent",hasInitial&&targetCount?`${Math.round(filled/targetCount*100)}%`:"—");stat("batches",preview?"待运行":`${index} / ${frames.length}`);stat("time",preview||!hasInitial?"—":formatTime(elapsed));stat("losses",preview||!hasInitial?"—":counts?.losses??Math.max(0,initialCount-remaining));
    const endPhase=summary.status==="success"?"回放完成 · 目标已填满":summary.status==="blocked"?"回放完成 · 仿真安全停止":summary.status==="incomplete"?"回放完成 · 目标未填满":"回放完成 · 已记录步骤";
    root.querySelector(".am-stage-phase").textContent=!hasInitial?"等待有效阵列":preview?(editable?"初态预览 · 点击网格编辑":"初态与目标预览"):active?`移动中 · 第 ${index+1} 批`:index===0?(!frames.length&&summary.status==="success"?"初态已满足目标":!frames.length?"未生成移动轨迹":"初始装载"):index===frames.length?endPhase:`第 ${index} 批已完成`;
    root.querySelector(".am-progress-label").textContent=preview?"尚未生成轨迹":`${index} / ${frames.length} 批`;
    progress.value=index+fraction;playButton.textContent=playing?"Ⅱ 暂停":"▶ 播放";
    playButton.disabled=frames.length===0;replayButton.disabled=frames.length===0;previousButton.disabled=index===0&&fraction===0;nextButton.disabled=index>=frames.length;
    exportButton.disabled=!exportable||editPending;
    root.querySelector(".am-speed-label").textContent=speedText(preferredSpeed);
    root.dataset.frameIndex=String(index);root.dataset.frameFraction=fraction.toFixed(4);root.dataset.playing=String(playing);root.dataset.speed=String(preferredSpeed);root.dataset.simulatedTime=preview||!hasInitial?"unknown":String(elapsed);root.dataset.remaining=hasInitial?String(remaining):"unknown";root.dataset.filled=hasInitial?String(filled):"unknown";root.dataset.totalFrames=String(frames.length);root.dataset.exportable=String(exportable);
    root.dataset.preview=String(preview);root.dataset.editable=String(editable);root.dataset.editPending=String(editPending);
    const activeTweezers=activeTweezerCount(frame);
    root.querySelector('[data-tweezer-stat="available"]').textContent=String(availableTweezers);
    root.querySelector('[data-tweezer-stat="active"]').textContent=preview?"待运行":activeTweezers===null?"未记录":String(activeTweezers);
    root.querySelector('[data-tweezer-stat="peak"]').textContent=preview?"—":peakTweezers===null?"未记录":String(peakTweezers);
    root.querySelector('.am-plan-check-stat').hidden=preview||checkedBatches===null;
    root.querySelector('[data-tweezer-stat="checks"]').textContent=checkedBatches===null?"0":String(checkedBatches);
    root.querySelector('.am-batch-check').hidden=preview||frame?.collision_checked!==true;
    root.dataset.tweezerCount=String(availableTweezers);root.dataset.activeTweezers=activeTweezers===null?"unknown":String(activeTweezers);root.dataset.maxActiveTweezers=peakTweezers===null?"unknown":String(peakTweezers);root.dataset.collisionCheckedBatches=checkedBatches===null?"unknown":String(checkedBatches);
    root.dataset.batchCollisionChecked=frame?.collision_checked===true?"true":frame?.collision_checked===false?"false":"unknown";
    root.dataset.tweezerIds=(frame?.moves||[]).map(tweezerId).filter(id=>id!==null).join(",");
    if(editable)editNote.textContent=editPending?"正在保存布置，完成后可继续点击。":"点击网格点添加或移除原子，再点击“运行仿真”。";
    canvas.setAttribute("aria-label",hasInitial?`${n}乘${n}原子阵列，第${index}批，共${frames.length}批，剩余${remaining}个原子，目标填充${filled}/${targetCount}，可用${availableTweezers}束移动光镊，本批使用${activeTweezers===null?"未记录":activeTweezers}束`:`阵列暂不可用。${summary.message||"正在准备阵列。"}`);
    const identity=frame?(active?index+1:index):0;
    if(identity!==lastEventIdentity){updateEvents(frame);lastEventIdentity=identity;}
  }
  function advance(time){
    if(lastTime!==null)fraction+=(Math.max(0,time-lastTime)*preferredSpeed)/600;
    lastTime=time;
    while(fraction>=1&&index<frames.length){fraction-=1;index++;}
    if(index>=frames.length){index=frames.length;fraction=0;playing=false;lastTime=null;}
  }
  function pause(){if(playing)advance(performance.now());playing=false;lastTime=null;if(raf)cancelAnimationFrame(raf);raf=0;render();}
  function tick(time){
    if(disposed||!playing||!root.isConnected){pause();return;}
    advance(time);render();raf=playing?requestAnimationFrame(tick):0;
  }
  function play(){if(!frames.length)return;if(index>=frames.length){index=0;fraction=0;}playing=true;lastTime=performance.now();render();raf=requestAnimationFrame(tick);}
  function step(delta){pause();if(delta<0){index=fraction>0?index:Math.max(0,index-1);}else index=Math.min(frames.length,index+1);fraction=0;render();}
  function on(node,event,handler){node.addEventListener(event,handler,{signal:aborter.signal});}
  on(playButton,"click",()=>playing?pause():play());
  on(replayButton,"click",()=>{pause();index=0;fraction=0;play();});
  on(previousButton,"click",()=>step(-1));on(nextButton,"click",()=>step(1));
  on(progress,"input",()=>{const requested=Number(progress.value);pause();index=Math.max(0,Math.min(frames.length,requested));fraction=0;render();});
  on(speedControl,"input",()=>{if(playing)advance(performance.now());preferredSpeed=Math.max(.25,Math.min(4,Number(speedControl.value)));if(!playing&&raf){cancelAnimationFrame(raf);raf=0;}render();});
  on(exportButton,"click",()=>{
    if(!exportable||editPending||disposed)return;
    let url=null,link=null;
    try{
      const algorithm=String(data.config?.algorithm||"result").replace(/[^A-Za-z0-9_-]/g,"").slice(0,50)||"result";
      const seed=String(data.config?.seed??"unknown").replace(/[^A-Za-z0-9_-]/g,"").slice(0,20)||"unknown";
      const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json;charset=utf-8"});
      url=URL.createObjectURL(blob);downloadUrls.add(url);link=document.createElement("a");link.href=url;link.download=`atommovr-${algorithm}-seed-${seed}.json`;link.hidden=true;document.body.append(link);link.click();
      exportStatus.textContent="结果文件已生成";
      const timer=setTimeout(()=>{URL.revokeObjectURL(url);downloadUrls.delete(url);downloadTimers.delete(timer);},1000);downloadTimers.add(timer);
    }catch(error){if(url){URL.revokeObjectURL(url);downloadUrls.delete(url);}exportStatus.textContent="结果导出失败，请重试";}
    finally{if(link)link.remove();}
  });
  on(canvas,"pointermove",event=>{if(!editable||editPending)return;const cell=cellAt(event);if((cell?key(cell):"")!==(hoverCell?key(hoverCell):"")){hoverCell=cell;render();}});
  on(canvas,"pointerleave",()=>{if(hoverCell){hoverCell=null;render();}});
  on(canvas,"click",event=>{
    if(!editable||editPending||disposed)return;
    const cell=cellAt(event);if(!cell)return;
    const oldInitial=initial,oldCount=initialCount;
    const [r,c]=cell;initial=initial.map(row=>row.slice());initial[r][c]=initial[r][c]?0:1;initialCount=countAtoms(initial);editPending=true;hoverCell=null;render();
    try{trigger("edit",{matrix:initial.map(row=>row.slice()),n});}
    catch(error){initial=oldInitial;initialCount=oldCount;editPending=false;result.dataset.status="algorithm_error";root.querySelector(".am-result-text").textContent="布置发送失败，已恢复原布置。请重试或重新切换编辑初态。";render();}
  });
  on(root.querySelector(".am-stage"),"keydown",event=>{if(event.code==="Space"){event.preventDefault();playing?pause():play();}else if(event.key==="ArrowLeft"){event.preventDefault();step(-1);}else if(event.key==="ArrowRight"){event.preventDefault();step(1);}});
  const resizeObserver=new ResizeObserver(entries=>{const entry=entries[0];if(entry){logicalSize=entry.contentRect.width;render();}});
  resizeObserver.observe(root.querySelector(".am-canvas-wrap"));
  currentCleanup=()=>{disposed=true;playing=false;if(raf)cancelAnimationFrame(raf);aborter.abort();resizeObserver.disconnect();downloadTimers.forEach(clearTimeout);downloadUrls.forEach(url=>URL.revokeObjectURL(url));downloadTimers.clear();downloadUrls.clear();};
  element._atommovrPlayerCleanup=currentCleanup;
  render();
}
mountPlayer();
watch("value", mountPlayer);

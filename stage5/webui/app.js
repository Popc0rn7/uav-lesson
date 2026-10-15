const $=id=>document.getElementById(id), esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,n=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(n):'—';
let view='rgb',preview={},lastNow=0,currentRun=null;
const names={plan:'规划任务',review:'验收阶段',summary:'总结任务',accept:'接受阶段',redo:'重做阶段',modify_stage:'修改当前阶段',modify_plan:'修改后续计划',abort:'终止任务'};
function metric(k,v,cls=''){return `<div class="metric ${cls}"><span>${esc(k)}</span><b>${esc(v)}</b></div>`}
function drawPreview(){
 const detection=preview.detection, encoded=view==='detection'?detection?.image:preview.rgb;
 $('rgb').style.display=encoded?'block':'none';$('rgbEmpty').style.display=encoded?'none':'grid';
 if(encoded)$('rgb').src='data:image/png;base64,'+encoded;
 $('depth').style.display=preview.depth?'block':'none';$('depthEmpty').style.display=preview.depth?'none':'grid';
 if(preview.depth)$('depth').src='data:image/png;base64,'+preview.depth;
 $('imageStamp').textContent=preview.received?`${view==='detection'?'DINO SNAPSHOT':'RGB LIVE'} · ${fmt(Math.max(0,lastNow-(view==='detection'?preview.detection_received:preview.received)))}s ago · SIM ${fmt(preview.sim_time)}s`:'NO SIGNAL';
 $('boxes').innerHTML='';
 if(view==='detection'&&detection){
 $('boxes').setAttribute('viewBox',`0 0 ${detection.width} ${detection.height}`);$('boxes').setAttribute('preserveAspectRatio','xMidYMid meet');
 $('boxes').innerHTML=(detection.detections||[]).map(d=>{let [x,y,x2,y2]=d.box_xyxy;const color=d.accepted===false?'#eaba6b':'#53e1cf';return `<rect x="${Number(x)}" y="${Number(y)}" width="${Number(x2-x)}" height="${Number(y2-y)}" fill="#53e1cf12" stroke="${color}" stroke-dasharray="${d.accepted===false?'5 4':'none'}" stroke-width="2"/><text x="${Number(x)+3}" y="${Math.max(15,Number(y)-6)}" fill="${color}" font-size="13">${esc(d.label)} ${fmt(d.score,2)} ${esc(d.rejection_reason||'候选')}</text>`}).join('');
 }
}
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b===button));drawPreview()});
function render(data){
 if(data.run_id!==currentRun){currentRun=data.run_id;preview={};$('boxes').innerHTML='';drawPreview();}
 const s=data.state||{},r=s.runtime||{},o=r.observation||{},j=r.judgment||{},l=s.ledger||{},p=r.progress||{},stage=r.stage||{},tracking=o.tracking,target=tracking?.target||{},row=r.row||{};
 lastNow=data.now;const age=s.updated_monotonic?Math.max(0,data.now-s.updated_monotonic):Infinity;
 const live=age<3&&!s.finalized,active=live&&r.active,qa=live&&s.qwen_activity;
 $('connection').textContent=s.finalized?'任务已结束':live?'实时连接':s.updated_monotonic?`数据已陈旧 · ${fmt(age)}s`:'等待任务';$('connectionDot').className=live?'on':'';
 $('task').textContent=s.task||'等待任务接入';$('run').textContent=`RUN / ${data.run}${data.follow_latest?' · 自动跟随':''} · ${s.finalized?data.terminal?.outcome||'已结束':live?'状态每 0.7 秒更新':'等待当前版本 mission 写入 ui.json'}`;
 $('elapsed').textContent=fmt(l.elapsed_s,0);$('qwen').classList.toggle('active',!!qa);$('qwenStatus').textContent=qa?'● ACTIVE':s.finalized?'FINISHED':'STANDBY';
 $('qwenAction').textContent=qa?(names[qa]||qa)+(s.simulation_paused?' · 仿真已暂停':' · 仿真最多推进3秒'):s.finalized?'任务已结束':active?'等待阶段报告':'等待任务进展';
 const decision=s.last_decision||{};const decisionText=decision.assessment||decision.summary||decision.reason||((decision.stages||[]).length?`已分配 ${decision.stages.length} 个阶段：${decision.stages.map(x=>x.goal).join(' → ')}`:'尚无模型决策');
 $('decision').textContent=(decision.action?`${names[decision.action]||decision.action} · `:'')+(typeof decisionText==='string'?decisionText:JSON.stringify(decisionText));
 const qm=s.qwen_metrics?.usage?s.qwen_metrics:[...(data.events||[])].reverse().find(e=>e.event==='qwen_usage')||{};
 $('qwenMetrics').innerHTML=[['Qwen 执行额度',`${l.qwen_execution_calls??0} / ${l.qwen_budget??'—'}`],['最终总结（额外最多1次）',`${l.qwen_summary_calls??0} / 1`],['输入 / 输出 token',`${qm.usage?.prompt_tokens??'—'} / ${qm.usage?.completion_tokens??'—'}`],['历史轮数',qm.history_turns??0],['计划版本',`v${s.revision??'—'}`],['任务剩余',`${fmt(l.remaining_timeout_s,0)} s`]].map(([k,v])=>`<span>${k}<b>${esc(v)}</b></span>`).join('');
 $('revision').textContent=`PLAN v${s.revision??'—'}`;
 const stages=s.plan?.stages||[],accepted=s.accepted||[];
 $('stages').innerHTML=stages.length?stages.map((st,i)=>{const done=accepted.some(a=>a.stage.id===st.id),current=i===s.current_index&&!done&&!s.finalized;const progress=st.id===r.tag?.stage_id?p:{};const duration=st.duration_s;const value=progress.valid_follow_s||progress.observed_s||0;return `<article class="stage ${done?'done':current?'current':''}"><div class="stage-top"><span>STAGE ${String(i+1).padStart(2,'0')}</span><span>${done?'✓ 已验收':current?(qa?'等待验收':'● 当前阶段'):'○ 等待'}</span></div><h3>${esc(st.goal)}</h3><p>${esc(st.skill)} · ${st.allocation?.budget??'—'} 次 / ${st.allocation?.timeout??'—'}s</p><p>${current?'Attempt '+(r.tag?.attempt??'—')+' · ':''}${duration?`达标 ${fmt(value)} / ${duration}s`:done?'阶段已接受':'原地观察 / 按阶段标准验收'}</p><div class="bar"><span style="width:${done?100:duration?Math.min(100,value/duration*100):0}%"></span></div></article>`}).join(''):'<div class="empty">Qwen 生成计划后自动展示阶段</div>';
 $('stageLabel').textContent=active?stage.id||'RUNNING':qa?'QWEN '+qa.toUpperCase():'IDLE';
 const fresh=live&&o.age_s<.7,valid=active&&j.source==='jev'&&!j.stale;
 const lights=[['取帧',fresh,`${fmt(o.age_s,2)}s · SIM ${fmt(o.sim_time)}`],['DINO',live&&r.dino_pending,r.dino_pending?'请求中':`检测年龄 ${fmt(o.detection_age_s)}s`],['目标跟踪',fresh&&!!tracking,tracking?'目标已确认':'目标不可用'],['Jev',active&&r.jev_pending,r.jev_pending?'请求中':j.source==='error'?'请求失败':valid?'建议有效':'等待新决策'],['决策许可',valid,valid?j.maneuver||'已有建议':'无有效授权'],['飞行控制',active,active?`PX4 ${r.mode===6?'Offboard':r.mode}`:r.frozen?'已冻结 / Hold':'Hold / 待命']];
 $('lights').innerHTML=lights.map(([title,on,desc])=>`<div class="light ${on?'on':title==='Jev'&&j.source==='error'?'warn':''}"><strong>${title}</strong><small>${esc(desc)}</small></div>`).join('');
 const stats=r.jev_stats||{},space=o.local_space||{},forward=space.motion_candidates?.forward_1m||{};
 const velocity=r.velocity_ned||[];const moving=velocity.some(v=>Math.abs(v)>.01);
 $('metrics').innerHTML=[['Jev 行为',j.maneuver],['风险',fmt(j.risk,2)],['阶段判断',j.stage_status],['阶段原因',j.stage_reason],['判断校验',r.rejected_stage_status?'失败缺少证据，已拦截':'—'],['决策来源',({default:'等待首次响应',jev:'Jev',error:'请求失败'})[j.source]||j.source],['决策新鲜度',j.stale?'已过期':valid?'有效':'—',valid?'good':'warn'],['实际执行',active?(moving?'发送运动速度':'零速 / 悬停'):'Hold'],['语义目标',target.semantic_label],['检测置信度',fmt(target.semantic_score,2)],['观测年龄',`${fmt(o.age_s,2)} s`,fresh?'good':'warn'],['前向通道',forward.status],['前方净空',`${fmt(space.front_clearance_m,2)} m`],['阻止执行原因',r.block_reason||'无'],['感知错误',o.perception_error||'无'],['语义候选 / 原始',`${o.detections?.length??0} / ${o.detection_candidates?.length??0}`],['目标状态',tracking?'DINO + RGBD 已确认':o.semantic_targets?.length?'有语义候选，无可用跟踪':'未确认目标'],['达标跟随',`${fmt(p.valid_follow_s)} / ${stage.duration_s??'—'} s`],['允许跟随',`${fmt(p.enabled_follow_s)} s`],['有效观察',`${fmt(p.observed_s)} s`],['当前阶段 Jev 额度',`${stats.attempts??0} / ${stage.allocation?.budget??'—'}`],['Jev 成功 / 失败',`${stats.calls??0} / ${stats.errors??0}`],['检测提示词',o.dino_text],['速度 N / E / D',velocity.length?velocity.map(v=>fmt(v,2)).join(' / ')+' m/s':'—'],['自身 NED / m',o.own_position_ned_m?.map(v=>fmt(v,2)).join(' / ')],['目标点 NED / m',row.goal_ned?.map(v=>fmt(v,2)).join(' / ')]].map(a=>metric(...a)).join('');
 const events=data.events||[];const eventNames={qwen_request:'Qwen 请求',qwen_result:'Qwen 返回',stage_start:'阶段开始',qwen_sim_window:'仿真3秒窗口',simulation_paused:'仿真已暂停',simulation_resumed:'仿真已恢复',stage_end:'阶段结束',qwen_error:'Qwen 错误',task_aborted:'任务终止',invalid_qwen_result:'协议修正'};
 $('eventCount').textContent=events.length+' EVENTS';$('events').innerHTML=events.length?[...events].reverse().slice(0,30).map(e=>`<div class="event"><time>+${fmt(e.elapsed_s)}s</time><strong>${esc(eventNames[e.event]||e.event)}</strong><span>${esc(e.event==='qwen_result'?(names[e.result?.action]||'计划已生成')+' · '+(e.result?.assessment||''):e.stage_id?`${e.stage_id} · attempt ${e.attempt} · ${e.status||''} ${e.reason||''}`:names[e.purpose]||e.assessment||e.error_type||e.reason||'')}</span></div>`).join(''):'<div class="empty">等待任务事件</div>';
 $('raw').textContent=JSON.stringify({state:s,terminal:data.terminal,summary:data.summary},null,2);drawPreview();
}
async function poll(){try{const res=await fetch('/api/state');if(!res.ok)throw Error();render(await res.json())}catch(e){$('connection').textContent='连接中断';$('connectionDot').className='';$('qwen').classList.remove('active');document.querySelectorAll('.light.on').forEach(el=>el.classList.remove('on'))}finally{setTimeout(poll,700)}}
async function images(){try{const res=await fetch('/api/preview');if(res.ok){const packet=await res.json();if(packet.run_id===currentRun){preview=packet.preview||{};drawPreview()}}}catch(e){}finally{setTimeout(images,1200)}}
poll();images();

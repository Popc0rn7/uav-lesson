const $=id=>document.getElementById(id), esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,n=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(n):'—';
let preview={},lastNow=0,currentRun=null,previewEtag=null,lastChoiceGroups=[];
const names={plan:'规划任务',review:'验收阶段',summary:'总结任务',accept:'接受阶段',redo:'重做阶段',modify_stage:'修改当前阶段',modify_plan:'修改后续计划',abort:'终止任务'};
function metric(k,v,cls=''){return `<div class="metric ${cls}"><span>${esc(k)}</span><b>${esc(v)}</b></div>`}
function drawPreview(){
 const detection=preview.detection, encoded=detection?.image;
 $('rgb').style.display=encoded?'block':'none';$('rgbEmpty').style.display=encoded?'none':'grid';
 if(encoded)$('rgb').src='data:image/png;base64,'+encoded;
 $('imageStamp').textContent=encoded?`DINO · ${fmt(Math.max(0,lastNow-preview.detection_received))}s ago · SIM ${fmt(preview.sim_time)}s`:'WAITING FOR DETECTION';
 $('boxes').innerHTML='';
 if(encoded&&detection){
 $('boxes').setAttribute('viewBox',`0 0 ${detection.width} ${detection.height}`);$('boxes').setAttribute('preserveAspectRatio','xMidYMid meet');
 $('boxes').innerHTML=(detection.detections||[]).map(d=>{let [x,y,x2,y2]=d.box_xyxy;const color=d.accepted===false?'#eaba6b':'#53e1cf';return `<rect x="${Number(x)}" y="${Number(y)}" width="${Number(x2-x)}" height="${Number(y2-y)}" fill="#53e1cf12" stroke="${color}" stroke-dasharray="${d.accepted===false?'5 4':'none'}" stroke-width="2"/><text x="${Number(x)+3}" y="${Math.max(15,Number(y)-6)}" fill="${color}" font-size="13">${esc(d.label)} ${fmt(d.score,2)} ${esc(d.rejection_reason||'候选')}</text>`}).join('');
 }
}
function render(data){
 if(data.run_id!==currentRun){currentRun=data.run_id;lastChoiceGroups=[];preview={};previewEtag=null;$('boxes').innerHTML='';drawPreview();}
 const s=data.state||{},r=s.runtime||{},o=r.observation||{},j=r.judgment||{},l=s.ledger||{},p=r.progress||{},stage=r.stage||{},tracking=o.tracking,target=tracking?.target||{},row=r.row||{};
 lastNow=data.now;const age=s.updated_monotonic?Math.max(0,data.now-s.updated_monotonic):Infinity;
 const live=age<3&&!s.finalized,active=live&&r.active,qa=live&&s.qwen_activity;
 $('connection').textContent=s.finalized?'任务已结束':live?'实时连接':s.updated_monotonic?`数据已陈旧 · ${fmt(age)}s`:'等待任务';$('connectionDot').className=live?'on':'';
 $('task').textContent=s.task||'等待任务接入';$('run').textContent=`RUN / ${data.run}${data.follow_latest?' · 自动跟随':''} · ${s.finalized?data.terminal?.outcome||'已结束':live?'状态每 0.7 秒更新':'等待当前版本 mission 写入 ui.json'}`;
 $('elapsed').textContent=fmt(l.elapsed_s,0);$('qwen').classList.toggle('active',!!qa);$('qwenStatus').textContent=qa?'● ACTIVE':s.finalized?'FINISHED':'STANDBY';
 $('qwenAction').textContent=qa?(names[qa]||qa):s.finalized?'任务已结束':active?'等待阶段报告':'等待任务进展';
 const decision=s.last_decision||{};const decisionText=decision.assessment||decision.summary||decision.reason||((decision.stages||[]).length?`已分配 ${decision.stages.length} 个阶段：${decision.stages.map(x=>x.goal).join(' → ')}`:'尚无模型决策');
 $('decision').textContent=(decision.action?`${names[decision.action]||decision.action} · `:'')+(typeof decisionText==='string'?decisionText:JSON.stringify(decisionText));
 const qm=s.qwen_metrics?.usage?s.qwen_metrics:[...(data.events||[])].reverse().find(e=>e.event==='qwen_usage')||{};
 $('qwenMetrics').innerHTML=[['Qwen 执行额度',`${l.qwen_execution_calls??0} / ${l.qwen_budget??'—'}`],['最终总结（额外最多1次）',`${l.qwen_summary_calls??0} / 1`],['输入 / 输出 token',`${qm.usage?.prompt_tokens??'—'} / ${qm.usage?.completion_tokens??'—'}`],['历史轮数',qm.history_turns??0],['计划版本',`v${s.revision??'—'}`],['任务剩余',`${fmt(l.remaining_timeout_s,0)} s`]].map(([k,v])=>`<span>${k}<b>${esc(v)}</b></span>`).join('');
 $('revision').textContent=`PLAN v${s.revision??'—'}`;
 const stages=s.plan?.stages||[],accepted=s.accepted||[];
 const reviewing=s.qwen_activity==='review'&&!s.finalized;
 const focusId=reviewing?(s.qwen_stage_id||r.tag?.stage_id||stages[s.current_index]?.id):stages[s.current_index]?.id;
 $('stages').innerHTML=stages.length?stages.map((st,i)=>{const current=st.id===focusId&&!s.finalized&&s.qwen_activity!=='summary'&&(reviewing||!accepted.some(a=>a.stage.id===st.id)),done=!current&&accepted.some(a=>a.stage.id===st.id);const progress=st.id===r.tag?.stage_id?p:{};const duration=st.duration_s;const value=progress.valid_follow_s||progress.observed_s||0;return `<article class="stage ${done?'done':current?'current':''}"><div class="stage-top"><span>STAGE ${String(i+1).padStart(2,'0')}</span><span>${done?'✓ 已验收':current?(reviewing?'● Qwen 验收中':'● 当前阶段'):'○ 等待'}</span></div><h3>${esc(st.goal)}</h3><p>${esc(st.skill)} · ${st.allocation?.budget??'—'} 次 / ${st.allocation?.timeout??'—'}s</p><p>${current?'Attempt '+(r.tag?.attempt??'—')+' · ':''}${duration?`达标 ${fmt(value)} / ${duration}s`:done?'阶段已接受':'原地观察 / 按阶段标准验收'}</p><div class="bar"><span style="width:${done?100:duration?Math.min(100,value/duration*100):0}%"></span></div></article>`}).join(''):'<div class="empty">Qwen 生成计划后自动展示阶段</div>';
 if(j.source==='jev'&&j.choice_groups?.length)lastChoiceGroups=j.choice_groups;
 const groups=lastChoiceGroups;
 const labels={maneuver:'行为',stage_reason:'阶段原因',stage_status:'阶段判断',target_ambiguous:'目标歧义'};
 $('choices').innerHTML=groups.length?groups.map(group=>`<div class="choice-group"><div class="choice-title">${esc(labels[group.key]||group.key)}</div><div class="choice-options">${group.options.map(option=>{const selected=group.selected===option.key;return `<div class="choice ${selected?'selected':''}" title="${esc(option.description)}"><i></i><span>${esc(option.key)}</span>${selected?'<small>已选择</small>':''}</div>`}).join('')}</div></div>`).join(''):'<div class="empty">等待 Jev 选择</div>';
 const events=data.events||[];const eventNames={qwen_request:'Qwen 请求',qwen_result:'Qwen 返回',stage_start:'阶段开始',qwen_sim_window:'仿真3秒窗口',simulation_paused:'仿真已暂停',simulation_resumed:'仿真已恢复',stage_end:'阶段结束',qwen_error:'Qwen 错误',task_aborted:'任务终止',invalid_qwen_result:'协议修正'};
 $('eventCount').textContent=events.length+' EVENTS';$('events').innerHTML=events.length?[...events].reverse().slice(0,30).map(e=>`<div class="event"><time>+${fmt(e.elapsed_s)}s</time><strong>${esc(eventNames[e.event]||e.event)}</strong><span>${esc(e.event==='qwen_result'?(names[e.result?.action]||'计划已生成')+' · '+(e.result?.assessment||''):e.stage_id?`${e.stage_id} · attempt ${e.attempt} · ${e.status||''} ${e.reason||''}`:names[e.purpose]||e.assessment||e.error_type||e.reason||'')}</span></div>`).join(''):'<div class="empty">等待任务事件</div>';
 $('raw').textContent=JSON.stringify({state:s,terminal:data.terminal,summary:data.summary},null,2);drawPreview();
}
async function poll(){try{const res=await fetch('/api/state');if(!res.ok)throw Error();render(await res.json())}catch(e){$('connection').textContent='连接中断';$('connectionDot').className='';$('qwen').classList.remove('active')}finally{setTimeout(poll,700)}}
async function images(){try{const res=await fetch('/api/preview',{headers:previewEtag?{'If-None-Match':previewEtag}:{}});if(res.ok){const packet=await res.json();if(packet.run_id===currentRun){previewEtag=res.headers.get('ETag');if(packet.preview?.detection?.image){preview=packet.preview;drawPreview()}}}}catch(e){}finally{setTimeout(images,1200)}}
poll();images();

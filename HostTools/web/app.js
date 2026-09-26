"use strict";
const $=id=>document.getElementById(id), names={POINT_LEFT:"向左",POINT_RIGHT:"向右",FIST:"握拳",PALM:"张掌",V_SIGN:"V 字",OTHER:"其他手形",EMPTY:"无手"};
const owner=crypto.randomUUID().replaceAll("-", "");
window.studioOwner=owner;
let state,editable=false,closing=false,observing=false,actionBusy=false,pollBusy=false,previewBusy=false;
let previewSequence=0,previewUrl=null,previewFrame=null,badgeTimer,scope="current",pageOffset=0,galleryKey="";
let galleryRequest=0,observationVersion=0,heartbeatBusy=false;
for(const id of ["capture-label","clip-label"]){for(const [value,name] of Object.entries(names)){const o=document.createElement("option");o.value=value;o.textContent=name;$(id).append(o);}$(id).value="PALM";}
$("session-name").value=`手势采集_${new Date().toLocaleDateString("zh-CN").replaceAll("/","-")}`;
const labelName=name=>names[name]||"待标注";
function message(text,error=false){$("message").textContent=text;$("message").classList.toggle("error",error);}
async function request(path,options,consume,timeout=5000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{return await consume(await fetch(path,{...options,signal:controller.signal}));}
 catch(error){if(error.name==="AbortError")throw new Error("连接超时，请查看当前状态后重试；刚才的操作可能已完成。");throw error;}
 finally{clearTimeout(timer);}
}
async function api(path,body,keepalive=false){
 const options=body===undefined?{cache:"no-store"}:{method:"POST",keepalive,headers:{"Content-Type":"application/json","X-UI-Token":state?.ui_token||""},body:JSON.stringify({...body,owner})};
 const consume=async response=>{const result=await response.json();if(!response.ok)throw new Error(result.message||`连接失败 (${response.status})`);return result;};
 return keepalive?consume(await fetch(path,options)):request(path,options,consume,body===undefined?5000:30000);
}
async function act(path,body,success){if(actionBusy||closing)return;actionBusy=true;try{const result=await api(path,body);if(success)success(result);await refresh();}catch(error){message(error.message,true);}finally{actionBusy=false;}}
function hideGesture(){clearTimeout(badgeTimer);$("gesture-badge").hidden=true;$("gesture-badge").textContent="";}
function clearPreview(){hideGesture();previewFrame=null;$("preview").removeAttribute("src");$("preview").hidden=true;$("empty-preview").hidden=false;if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;}
function renderClips(rows){$("clips").replaceChildren();const labeled=rows.filter(r=>r.status==="labeled");if(!labeled.length){const p=document.createElement("p");p.className="hint";p.textContent="完成片段整理后，视频会出现在这里。";$("clips").append(p);return;}for(const clip of labeled){const row=document.createElement("div"),text=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("span"),link=document.createElement("a");row.className="clip-row";title.textContent=`${labelName(clip.label)} · 完整保存 ${clip.frame_count} 帧`;meta.textContent=clip.video_file.split("/").at(-1);text.append(title,meta);link.href=`/video/${clip.clip_id}`;link.download=clip.video_file.split("/").at(-1);link.textContent="下载视频";row.append(text,link);$("clips").append(row);}}
function render(next){
 if(state&&(state.epoch!==next.epoch||state.ui_token!==next.ui_token))clearPreview();
 if(state&&state.ui_token!==next.ui_token){previewSequence=0;observing=false;editable=false;message("服务已重新启动，请重新打开窗口建立连接。",true);}
 if(state&&state.view_session!==next.view_session){galleryRequest++;pageOffset=0;galleryKey="";$("review").hidden=true;$("export-result").replaceChildren();}
 state=next;const pending=next.pending_clips[0]||null,processing=!!pending?.processing;
 $("connection").textContent=next.active?"正在录制":next.usb?.connected?"板卡已连接":"等待 USB 连接";$("connection").className="pill"+(next.usb?.connected?"":" neutral");
 $("workspace-notice").textContent=editable?"":next.workspace_busy?"另一窗口正在控制采集；此窗口可查看画面与历史。":"此窗口尚未取得控制权，请点击下方按钮重新连接。";
 const deviceError=next.model_error||(!next.usb?.connected?next.usb?.last_error:"")||next.last_error||"";$("device-error").textContent=deviceError;$("device-error").hidden=!deviceError;
 $("take-control").hidden=editable;$("new-session").hidden=false;$("new-session").querySelectorAll("input,select,button").forEach(el=>el.disabled=!editable);
 $("active-session").hidden=!next.session;$("start-panel").hidden=!next.session||!!next.active_clip||!!pending;$("recording-panel").hidden=!next.active_clip;$("clip-labeler").hidden=!pending;
 $("session-state").textContent=next.active_clip?"录制中":processing?"正在整理":pending?"待处理":next.session?"临时会话":next.session_saved?"已保存":"未建立";
 $("total").textContent=(next.captured_total??next.total).toLocaleString();$("included").textContent=(next.exportable_total??0).toLocaleString();$("rate").textContent=`${(1000/next.interval_ms).toFixed(1)} fps`;
 $("selection-status").textContent=next.active?"录制中：收到的完整画面逐帧保存，结束后生成完整视频。":processing?"正在将录到的全部画面整理成视频，请稍候。":pending?"片段尚未整理成功，请查看下方处理提示并确认标签或放弃。":next.total?`本次已录制 ${next.total} 帧，已整理 ${next.exportable_total??0} 帧${next.session_saved?"，已保存到历史。":"；需要长期保留，请保存到历史。"}`:"尚未录制；实时观察不会存盘。";
 $("history-info").textContent=`历史资料保留 ${next.history_total?.toLocaleString()||0} 帧`;$('output-root').textContent=`资料位置：${next.output_root}`;
 $("label-counts").textContent=scope==="current"?Object.entries(names).map(([key,name])=>`${name} ${next.captured_counts?.[key]||0}`).join("　·　"):"历史资料只读，关闭窗口或新建会话不会删除。";
 for(const id of ["start-clip","stop-clip","save-clip-label","discard-clip"])$(id).disabled=!editable||processing;
 $("end-session").disabled=!editable||next.active||!!pending;$("export").disabled=!editable||next.active||!!pending||(scope==="current"&&!next.session_saved);
 if(next.session){$("session-title").textContent=next.session.name;$("session-meta").textContent="临时内容 · 保存到历史后长期保留";}
 if(next.active_clip){const left=next.active_clip.auto_stop_at?Math.max(0,Math.ceil((Date.parse(next.active_clip.auto_stop_at)-Date.now())/1000)):null;$("recording-meta").textContent=`${labelName(next.active_clip.label)} · ${next.active_clip.frame_count} 帧${left===null?"":` · 剩余 ${left} 秒`}`;}
 if(pending){if($("pending-clip-id").value!==pending.clip_id&&pending.label)$("clip-label").value=pending.label;$("pending-clip-id").value=pending.clip_id;$("pending-meta").textContent=processing?`正在将 ${pending.frame_count} 帧全部整理成视频，请稍候…`:`录到 ${pending.frame_count} 帧${pending.processing_error?` · ${pending.processing_error}`:""}`;}
 $("model-info").textContent=next.model?`与板卡同一模型 · ${next.model.model_id} · SHA256 ${next.model.model_sha256}。桌面使用 LiteRT，板卡使用 STM32Cube.AI，运行库数值可能存在小幅差异。`:next.model_error||"模型正在加载…";
 if(scope==="current"){renderClips(next.recent_clips);if(pageOffset===0)renderGallery(next.recent,next.total);}
}
function renderGallery(rows,total){$("page-info").textContent=`第 ${Math.floor(pageOffset/30)+1} 页 · 共 ${total} 帧`;$("previous-page").disabled=pageOffset===0;$("next-page").disabled=pageOffset+30>=total;const key=scope+rows.map(r=>`${r.record_id}:${r.label}`).join("|");if(key===galleryKey)return;galleryKey=key;$("gallery").replaceChildren();for(const row of rows){const button=document.createElement("button"),img=document.createElement("img"),text=document.createElement("span");button.className="thumb";img.src=`/media/${row.record_id}.png`;img.alt=labelName(row.label);img.loading="lazy";text.textContent=`${labelName(row.label)} · ${row.frame_id}`;button.append(img,text);button.onclick=()=>selectFrame(row);$("gallery").append(button);}if(!rows.length){const p=document.createElement("p");p.className="hint";p.textContent="还没有画面记录。实时观察不会自动保存。";$("gallery").append(p);}}
async function loadPage(offset){const version=++galleryRequest,requestedScope=scope,session=state?.view_session;try{const page=await api(`/api/frames?offset=${offset}&limit=30&scope=${requestedScope}`);if(closing||version!==galleryRequest||scope!==requestedScope||session!==state?.view_session)return;pageOffset=offset;renderGallery(page.samples,page.total);}catch(error){if(version===galleryRequest)message(error.message,true);}}
async function setScope(value){scope=value;const version=++galleryRequest;pageOffset=0;galleryKey="";$("scope-current").classList.toggle("selected",value==="current");$("scope-history").classList.toggle("selected",value==="history");$("review").hidden=true;await refresh();if(scope!==value||galleryRequest!==version)return;await loadPage(0);const pageVersion=galleryRequest;if(value==="history")try{const result=await api("/api/history");if(!closing&&scope===value&&galleryRequest===pageVersion)renderClips(result.clips);}catch(error){if(scope===value)message(error.message,true);}}
async function refresh(){if(pollBusy||closing)return;pollBusy=true;try{render(await api("/api/state"));}catch(error){$("connection").textContent="服务连接中断";hideGesture();message(error.message,true);}finally{pollBusy=false;}}
function selectFrame(row){$("review").hidden=false;$("review-image").src=`/media/${row.record_id}.png`;$("review-meta").textContent=`${labelName(row.label)} · 帧 ${row.frame_id} · 只读`;$("review-label-text").textContent=labelName(row.label);$("download-raw").href=`/media/${row.record_id}.rgb565`;$("review").scrollIntoView({behavior:"smooth",block:"nearest"});}
async function startObservation(){if(closing)return;const version=++observationVersion;try{await api("/api/preview",{action:"start"});if(closing||version!==observationVersion)return;observing=true;$("empty-preview").textContent="正在等待相机新画面，请连接开发板 Device USB。";$("preview-rate").textContent="等待相机新画面";await refresh();}catch(error){message(error.message,true);}}
async function refreshPreview(){if(previewBusy||!state||closing||!observing)return;previewBusy=true;try{const token=state.ui_token,epoch=state.epoch,version=observationVersion;const response=await request(`/api/preview.png?after=${previewSequence}`,{cache:"no-store"},async r=>({status:r.status,headers:r.headers,body:r.status===200?await r.blob():null}));if(closing||!observing||version!==observationVersion)return;if(response.status===200){const blob=response.body;if(token!==state.ui_token||epoch!==state.epoch||Number(response.headers.get("X-Control-Epoch"))!==epoch)return;const url=URL.createObjectURL(blob),old=previewUrl;previewUrl=url;$("preview").src=url;$("preview").hidden=false;$("empty-preview").hidden=true;if(old)URL.revokeObjectURL(old);previewSequence=Number(response.headers.get("X-Frame-Sequence"));previewFrame=Number(response.headers.get("X-Frame-ID"));$("frame-info").textContent=`实时画面 · ${previewFrame}`;hideGesture();}const liveRequestAt=performance.now();const live=await api("/api/live"),r=live.recognition;const resultAge=r?r.age_ms+(performance.now()-liveRequestAt):Infinity;if(closing||!observing||version!==observationVersion||token!==state.ui_token||epoch!==state.epoch)return;$("preview-rate").textContent=live.preview.age_ms!==null&&live.preview.age_ms<3000?`实时 ${live.preview.received_fps} fps`:observing?"等待相机新画面":"观察已暂停";if(r?.qualified&&r.label&&["POINT_LEFT","POINT_RIGHT","FIST","PALM","V_SIGN"].includes(r.class_name)&&Number.isFinite(resultAge)&&resultAge>=0&&resultAge<300&&r.epoch===epoch&&r.sequence===previewSequence&&r.frame_id===previewFrame){$("gesture-badge").textContent=r.label;$("gesture-badge").hidden=false;clearTimeout(badgeTimer);badgeTimer=setTimeout(hideGesture,Math.max(1,300-resultAge));}else hideGesture();if(live.preview.age_ms===null||live.preview.age_ms>=3000)clearPreview();}catch(_){hideGesture();}finally{previewBusy=false;}}
$("new-session").onsubmit=event=>{event.preventDefault();act("/api/session",{action:"new",name:$("session-name").value,split:$("split").value,sensor_profile:$("sensor-profile").value,exposure_profile:$("exposure-profile").value},()=>{message("新会话已就绪，上次临时内容已清空；历史资料保留。");setScope("current");});};
$("start-clip").onclick=()=>act("/api/clip",{action:"start",fps:Number($("fps").value),label:$("capture-label").value,duration_seconds:Number($("duration").value)},()=>message("开始录制。收到的完整画面会逐帧保存；所选手势只记录录制意图。"));
$("stop-clip").onclick=()=>act("/api/clip",{action:"finish"},()=>message("录制已停止，正在将全部画面生成视频。"));
$("save-clip-label").onclick=()=>act("/api/clip",{action:"label",clip_id:$("pending-clip-id").value,label:$("clip-label").value},()=>message("片段已整理；需要长期保留，请保存到历史。"));
$("discard-clip").onclick=()=>act("/api/clip",{action:"discard",clip_id:$("pending-clip-id").value},()=>message("片段已放弃；原始画面仍保留。"));
$("end-session").onclick=()=>act("/api/session",{action:"save"},()=>message("已保存到历史。关闭窗口或新建会话不会删除这些资料。"));
$("close-review").onclick=()=>{$("review").hidden=true;};
$("scope-current").onclick=()=>setScope("current");$("scope-history").onclick=()=>setScope("history");$("newest-page").onclick=()=>loadPage(0);$("previous-page").onclick=()=>loadPage(Math.max(0,pageOffset-30));$("next-page").onclick=()=>loadPage(pageOffset+30);
$("export").onclick=()=>act("/api/export",{scope},result=>{if(result.purpose!=="raw_capture_unreviewed")throw new Error("导出结果不是完整的原始采集清单。");$("export-result").replaceChildren();const link=document.createElement("a");link.href=result.download;link.download="capture_manifest.json";link.textContent=`下载采集清单 · ${result.sample_count} 帧`;$("export-result").append(link);message("采集清单已生成；原图完整保留，训练资格由外部清洗决定。");});
$("take-control").onclick=()=>act("/api/workspace",{action:"open"},r=>{editable=r.editable;message(editable?"此窗口已获得采集控制。":"另一窗口仍在使用，请先关闭该窗口。");});
$("observe-start").onclick=startObservation;$("observe-stop").onclick=()=>{observing=false;observationVersion++;clearPreview();$("empty-preview").textContent="观察已暂停，点击“连接 / 继续观察”恢复。";$("preview-rate").textContent="观察已暂停";$("frame-info").textContent="观察已暂停";return act("/api/preview",{action:"stop"},()=>{observing=false;clearPreview();message("观察已暂停。正在进行的录制不受影响。");});};
window.studioClose=()=>{if(closing||!state)return Promise.resolve();closing=true;hideGesture();return api("/api/workspace",{action:"close"},true).catch(()=>{});};
window.addEventListener("pagehide",()=>window.studioClose());
window.addEventListener("beforeunload",()=>{window.studioClose();});
window.addEventListener("pageshow",event=>{if(event.persisted)location.reload();});
async function initialize(){try{render(await api("/api/state"));const result=await api("/api/workspace",{action:"open"});editable=result.editable;render(result);await startObservation();}catch(error){message(error.message,true);}}
initialize();setInterval(refresh,1000);setInterval(refreshPreview,100);
setInterval(async()=>{if(closing||!state||heartbeatBusy)return;heartbeatBusy=true;try{const result=await api("/api/workspace",{action:"keep"});if(closing)return;editable=result.editable;if(observing)await api("/api/preview",{action:"start"});}catch(error){hideGesture();message(error.message,true);}finally{heartbeatBusy=false;}},4000);

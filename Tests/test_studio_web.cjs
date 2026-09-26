/* Offline behavior checks for the actual HostTools/web/app.js. No browser or board. */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');

const elements = new Map(), listeners = new Map(), posts = [], requests = [];
let clock = 0, nextTimer = 1, objectNumber = 0;
const timers = new Map(), revoked = [];
let current = stateFixture(), frameReply = null, liveReply = null;
let holdLive = false, releaseLive = null;
let liveLatencyMs = 0, holdPage = false, releasePage = null;

function stateFixture(extra = {}) {
  return {ui_token:'token-a',epoch:7,view_session:'session-a',active:false,
    usb:{connected:true},session:null,session_saved:false,active_clip:null,
    pending_clips:[],raw_capture_only:true,total:0,captured_total:0,exportable_total:0,
    included:0,interval_ms:500,history_total:37,history_included:12,
    captured_counts:{},counts:{},recent_clips:[],recent:[],output_root:'test-only',
    model:null,model_error:'',...extra};
}
function element() {
  return {value:'',checked:false,disabled:false,hidden:false,textContent:'',children:[],
    classList:{toggle(){}},append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=nodes;},querySelectorAll(){return [];},
    removeAttribute(name){delete this[name];},scrollIntoView(){}};
}
const dom = {getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},
  createElement:element};
const get = id => dom.getElementById(id);
function response(payload, status=200, headers={}) {
  return {ok:status>=200&&status<300,status,headers:{get:key=>headers[key]??null},
    async json(){return structuredClone(payload);},async blob(){return {fixture:true};}};
}
async function fetchMock(url, options={}) {
  requests.push({url,options});
  const body=options.body===undefined?null:JSON.parse(options.body);
  if(body)posts.push({url,body,options});
  if(url==='/hang')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('abort'),{name:'AbortError'}))));
  if(url==='/api/state')return response(current);
  if(url==='/api/workspace') {
    if(body.action==='open')return response({...current,editable:true});
    return response({ok:true});
  }
  if(url==='/api/preview')return response({ok:true});
  if(url==='/api/clip')return response({ok:true});
  if(url==='/api/export')return response({download:'/exports/capture.json',
    sample_count:current.exportable_total,purpose:'raw_capture_unreviewed'});
  if(url.startsWith('/api/preview.png?')) {
    if(!frameReply)return response({},204);
    const frame=frameReply;frameReply=null;
    return response({},200,{'X-Control-Epoch':String(frame.epoch),
      'X-Frame-Sequence':String(frame.sequence),'X-Frame-ID':String(frame.frame_id)});
  }
  if(url==='/api/live'){
    clock += liveLatencyMs;
    liveLatencyMs = 0;
    const reply=response(liveReply??{preview:{age_ms:null,received_fps:0},recognition:null});
    if(holdLive)return new Promise(resolve=>{releaseLive=()=>resolve(reply);});
    return reply;
  }
  if(url==='/api/session'&&body.action==='new') {
    current=stateFixture({ui_token:current.ui_token,epoch:current.epoch+1,
      view_session:'session-new',session:{name:body.name},history_total:current.history_total,
      history_included:current.history_included});
    return response({ok:true});
  }
  if(url.startsWith('/api/frames?')&&holdPage){holdPage=false;return new Promise(resolve=>{releasePage=()=>resolve(response({samples:[],total:999}));});}
  if(url.startsWith('/api/frames?'))return response({samples:[],total:url.includes('history')?current.history_total:current.total});
  if(url==='/api/history')return response({clips:[]});
  throw new Error('Unexpected request: '+url);
}
const windowMock={studioOwner:'',addEventListener(type,handler){listeners.set(type,handler);}};
const context=vm.createContext({console,Date,Math,Number,Object,Error,AbortController,document:dom,
  window:windowMock,location:{reload(){}},crypto:{randomUUID:()=> '01234567-89ab-cdef-0123-456789abcdef'},
  performance:{now:()=>clock},
  URL:{createObjectURL(){return 'blob:mock-'+(++objectNumber);},revokeObjectURL(url){revoked.push(url);}},
  fetch:fetchMock,setInterval(){},
  setTimeout(fn,delay){const id=nextTimer++;timers.set(id,{fn,at:clock+delay});return id;},
  clearTimeout(id){timers.delete(id);}});
const source=fs.readFileSync(path.join(__dirname,'../HostTools/web/app.js'),'utf8');
vm.runInContext(source,context,{filename:'HostTools/web/app.js'});
const run=source=>vm.runInContext(source,context);
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
function advance(ms){clock+=ms;for(const [id,timer] of [...timers])if(timer.at<=clock){timers.delete(id);timer.fn();}}
function queueFrame(recognition,sequence=1,frame_id=41,epoch=current.epoch){
  frameReply={sequence,frame_id,epoch};
  liveReply={preview:{age_ms:20,received_fps:4},recognition};
}
async function refreshFrame(recognition,sequence=1,frame_id=41,epoch=current.epoch){
  queueFrame(recognition,sequence,frame_id,epoch);
  await run('refreshPreview()');
}
const recognition=(extra={})=>({qualified:true,label:'V字手势',class_name:'V_SIGN',epoch:current.epoch,
  sequence:1,frame_id:41,age_ms:20,...extra});
const failures=[];
async function check(name,fn){try{await fn();console.log('PASS:',name);}catch(error){failures.push({name,error});console.error('FAIL:',name,error.message);}}

(async()=>{
  await settle();
  await check('automatic workspace open, owner POST, preview start',()=>{
    assert.deepEqual(requests.slice(0,3).map(r=>r.url),['/api/state','/api/workspace','/api/preview']);
    assert.equal(windowMock.studioOwner,'0123456789abcdef0123456789abcdef');
    for(const post of posts){assert.equal(post.body.owner,windowMock.studioOwner);
      assert.equal(post.options.headers['X-UI-Token'],'token-a');}
    assert.equal(posts[0].body.action,'open');assert.equal(posts[1].body.action,'start');
  });
  await check('new session starts at zero without folding history into current counters',async()=>{
    get('session-name').value='new session';get('split').value='train';
    get('new-session').onsubmit({preventDefault(){}});
    await settle();
    assert.equal(get('total').textContent,'0');assert.equal(get('included').textContent,'0');
    assert.match(get('history-info').textContent,/37 帧/);
    assert.doesNotMatch(get('history-info').textContent,/训练样本/);
    assert.equal(posts.find(p=>p.url==='/api/session').body.owner,windowMock.studioOwner);
  });
  await check('qualified result matches current epoch, sequence and frame only',async()=>{
    const epoch=current.epoch;
    await refreshFrame(recognition({epoch,sequence:3,frame_id:51}),3,51,epoch);
    assert.equal(get('gesture-badge').hidden,false);
    assert.equal(get('gesture-badge').textContent,'V字手势');
    for(const mismatch of [{epoch:epoch-1},{sequence:4},{frame_id:52},{qualified:false}]){
      await refreshFrame(recognition({epoch,sequence:3,frame_id:51,...mismatch}),3,51,epoch);
      assert.equal(get('gesture-badge').hidden,true,JSON.stringify(mismatch));
    }
  });
  await check('300 ms timer hides a matching badge',async()=>{
    await refreshFrame(recognition({sequence:7,frame_id:70,age_ms:20}),7,70);
    assert.equal(get('gesture-badge').hidden,false);
    advance(279);assert.equal(get('gesture-badge').hidden,false);
    advance(1);assert.equal(get('gesture-badge').hidden,true);
  });
  await check('already older than 300 ms is never shown',async()=>{
    await refreshFrame(recognition({sequence:8,frame_id:80,age_ms:350}),8,80);
    assert.equal(get('gesture-badge').hidden,true);
  });
  await check('network delay consumes the remaining 300 ms freshness budget',async()=>{
    liveLatencyMs=60;
    await refreshFrame(recognition({sequence:8,frame_id:81,age_ms:250}),8,81);
    assert.equal(get('gesture-badge').hidden,true);
  });
  await check('normal UNKNOWN and low-score/nonqualified results remain hidden',async()=>{
    await refreshFrame(recognition({sequence:9,frame_id:90,label:null,
      class_name:'UNKNOWN',qualified:false}),9,90);
    assert.equal(get('gesture-badge').hidden,true,'normal UNKNOWN result');
    await refreshFrame(recognition({sequence:10,frame_id:100,qualified:false,label:'FIST'}),10,100);
    assert.equal(get('gesture-badge').hidden,true,'low score');
  });
  await check('contradictory qualified UNKNOWN label is still never shown',async()=>{
    await refreshFrame(recognition({sequence:10,frame_id:101,label:'UNKNOWN',
      class_name:'UNKNOWN',qualified:true}),10,101);
    assert.equal(get('gesture-badge').hidden,true);
  });
  await check('history frame shows only read-only intent and raw download',async()=>{
    await run('setScope("history")');
    run('selectFrame({record_id:"x",frame_id:4,label:"PALM",excluded:false})');
    assert.equal(get('review-label-text').textContent,'张掌');
    assert.equal(get('download-raw').href,'/media/x.rgb565');
    assert.match(get('review-meta').textContent,/只读/);
    assert.equal(posts.filter(p=>p.url==='/api/annotate').length,0);
  });
  await check('service token restart clears old image and label',async()=>{
    await refreshFrame(recognition({sequence:11,frame_id:110}),11,110);
    assert.equal(get('gesture-badge').hidden,false);
    current=stateFixture({ui_token:'token-b',epoch:current.epoch+1,view_session:'service-new'});
    await run('refresh()');
    assert.equal(get('gesture-badge').hidden,true);
    assert.equal(get('preview').hidden,true);
    assert.equal(run('previewSequence'),0);
    assert.match(get('message').textContent,/服务已重新启动/);
  });
  await check('late live reply from old service token cannot restore a label',async()=>{
    await run('startObservation()');
    queueFrame(recognition({sequence:12,frame_id:120}),12,120);
    holdLive=true;
    const pending=run('refreshPreview()');
    await settle();
    assert.equal(typeof releaseLive,'function');
    current=stateFixture({ui_token:'token-c',epoch:current.epoch+1,view_session:'service-newer'});
    await run('refresh()');
    releaseLive();holdLive=false;releaseLive=null;
    await pending;
    assert.equal(get('gesture-badge').hidden,true);
    assert.equal(get('preview').hidden,true);
  });
  await check('hung HTTP request times out and can be retried',async()=>{
    const pending=run('api("/hang")');
    const rejection=assert.rejects(pending,/连接超时/);
    advance(5001);await rejection;
    assert.equal((await run('api("/api/state")')).ui_token,current.ui_token);
  });
  await check('paused window neither fetches nor redisplays another window preview',async()=>{
    await run('startObservation()');
    queueFrame(recognition({sequence:20,frame_id:200}),20,200);
    holdLive=true;const pending=run('refreshPreview()');await settle();
    get('observe-stop').onclick();await settle();releaseLive();holdLive=false;await pending;
    assert.equal(get('preview').hidden,true);assert.equal(get('gesture-badge').hidden,true);
    assert.equal(get('preview-rate').textContent,'观察已暂停');assert.match(get('empty-preview').textContent,/观察已暂停/);
    const before=requests.length;await run('refreshPreview()');assert.equal(requests.length,before);
    await run('startObservation()');await refreshFrame(recognition({sequence:21,frame_id:201}),21,201);
    assert.equal(get('preview').hidden,false);
  });
  await check('late history page cannot replace current gallery after switching tabs',async()=>{
    holdPage=true;const history=run('setScope("history")');await settle();
    assert.equal(typeof releasePage,'function');
    await run('setScope("current")');releasePage();await history;
    assert.match(get('page-info').textContent,/共 0 帧/);
    assert.equal(run('scope'),'current');
  });
  await check('start records intent without sampling count; finish saves all frames',async()=>{
    get('fps').value='5';get('duration').value='60';get('capture-label').value='PALM';
    get('start-clip').onclick();await settle();
    const start=posts.filter(p=>p.url==='/api/clip').at(-1).body;
    assert.equal(start.action,'start');assert.equal(start.label,'PALM');
    assert.equal(start.fps,5);assert.equal(start.duration_seconds,60);
    assert.equal(Object.hasOwn(start,'selection_count'),false);
    get('stop-clip').onclick();await settle();
    assert.equal(posts.filter(p=>p.url==='/api/clip').at(-1).body.action,'finish');
    current=stateFixture({ui_token:'token-c',pending_clips:[{clip_id:'pending',frame_count:8,processing:true}]});
    await run('refresh()');
    assert.equal(get('session-state').textContent,'正在整理');
    assert.equal(get('save-clip-label').disabled,true);
    assert.match(get('selection-status').textContent,/整理成视频/);
    assert.doesNotMatch(get('pending-meta').textContent,/抽取|代表帧/);
    current=stateFixture({ui_token:'token-c',total:8,captured_total:8,exportable_total:8,
      captured_counts:{PALM:8},recent_clips:[{clip_id:'done',status:'labeled',label:'PALM',frame_count:8,video_file:'clips/test.avi'}]});
    await run('refresh()');
    assert.equal(get('included').textContent,'8');
    assert.match(get('selection-status').textContent,/已整理 8 帧/);
    assert.match(get('clips').children[0].children[0].children[0].textContent,/完整保存 8 帧/);
    assert.match(get('label-counts').textContent,/张掌 8/);
  });
  await check('export describes the full raw capture manifest',async()=>{
    current=stateFixture({ui_token:'token-c',session_saved:true,total:8,captured_total:8,exportable_total:8});
    await run('refresh()');
    get('export').onclick();await settle();
    const request=posts.filter(p=>p.url==='/api/export').at(-1);
    assert.equal(request.body.scope,'current');
    assert.match(get('export-result').children[0].textContent,/8 帧/);
    assert.equal(get('export-result').children[0].download,'capture_manifest.json');
    assert.match(get('message').textContent,/外部清洗/);
  });
  await check('HTML has no sampling or training-eligibility controls',()=>{
    const html=fs.readFileSync(path.join(__dirname,'../HostTools/web/index.html'),'utf8');
    assert.doesNotMatch(html,/selection-count|id="excluded"|id="save-annotation"/);
    assert.match(html,/提前结束并生成视频/);
    assert.match(html,/已整理画面/);
  });
  await check('pagehide and beforeunload close workspace once with current token',async()=>{
    listeners.get('pagehide')();listeners.get('beforeunload')();
    await settle();
    const closes=posts.filter(p=>p.url==='/api/workspace'&&p.body.action==='close');
    assert.equal(closes.length,1);
    assert.equal(closes[0].body.owner,windowMock.studioOwner);
    assert.equal(closes[0].options.headers['X-UI-Token'],'token-c');
    assert.equal(closes[0].options.keepalive,true);
  });
  if(failures.length){console.error(`${failures.length} of 18 studio web groups failed.`);process.exitCode=1;}
  else console.log('PASS: all 18 studio web groups (mock DOM/fetch/timers; no browser or board)');
})().catch(error=>{console.error(error);process.exitCode=1;});

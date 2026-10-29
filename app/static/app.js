let csrf='', voices={}, allRules=[];
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...(opts.body?{'Content-Type':'application/json'}:{}),'X-CSRF-Token':csrf,...opts.headers}});if(!r.ok)throw Error((await r.text()).replace(/<[^>]*>/g,' ').trim().slice(0,220));return r.json()}
function msg(e){$('#message').textContent=e instanceof Error?e.message:e}
function syncFavorite(){let key='favorite_'+$('#engine').value+'_'+$('#voice').value;$('#favorite').checked=localStorage.getItem(key)==='1'}
function selectVoices(){
  let e=$('#engine').value, collection=$('#collection').value;
  $('#collection-control').hidden=e!=='piper';
  const options=(voices[e]||[]).filter(v=>e!=='piper'||(collection==='mls'?v.startsWith('nl_NL-mls-medium#'):!v.includes('#')));
  $('#voice').innerHTML=options.map(v=>`<option value="${esc(v)}">${esc(v.includes('#')?'MLS spreker '+v.split('#')[1]:v)}</option>`).join('');
  let saved=localStorage.getItem('voice_'+e);if(options.includes(saved))$('#voice').value=saved;
  syncFavorite();
}
$('#collection').onchange=()=>{localStorage.setItem('piper_collection',$('#collection').value);selectVoices()};
$('#favorite').onchange=()=>localStorage.setItem('favorite_'+$('#engine').value+'_'+$('#voice').value,$('#favorite').checked?'1':'0');
$('#collection').value=localStorage.getItem('piper_collection')==='mls'?'mls':'individual';
const profiles={standard:{speed:100,steps:12,silence:300},scripture:{speed:90,steps:12,silence:350},extra:{speed:85,steps:12,silence:450}};
function readSettings(){return {speed:Number($('#speed').value)/100,steps:Number($('#steps').value),silence_duration:Number($('#silence').value)/1000}}
function settingsChanged(custom=true){
  $('#speed-value').value=$('#speed').value+'%';$('#steps-value').value=$('#steps').value;$('#silence-value').value=$('#silence').value+' ms';
  if(custom)$('#profile').value='custom';
  localStorage.setItem('supertonic_settings',JSON.stringify({speed:Number($('#speed').value),steps:Number($('#steps').value),silence:Number($('#silence').value),profile:$('#profile').value}));
}
function setProfile(name){const p=profiles[name];if(!p)return;for(const key of ['speed','steps','silence'])$('#'+key).value=p[key];$('#profile').value=name;settingsChanged(false)}
function loadSettings(){
  try{const s=JSON.parse(localStorage.getItem('supertonic_settings'));if(s && Number.isInteger(s.speed) && s.speed>=70 && s.speed<=200 && Number.isInteger(s.steps) && s.steps>=1 && s.steps<=100 && Number.isInteger(s.silence) && s.silence>=0 && s.silence<=10000 && s.silence%50===0 && ['standard','scripture','extra','custom'].includes(s.profile)){for(const key of ['speed','steps','silence'])$('#'+key).value=s[key];$('#profile').value=s.profile;settingsChanged(false);return}}catch(e){}
  setProfile('standard');
}
for(const key of ['speed','steps','silence'])$('#'+key).addEventListener('input',()=>settingsChanged());
$('#profile').addEventListener('change',()=>{if($('#profile').value==='custom')settingsChanged(false);else setProfile($('#profile').value)});
$('#reset-settings').addEventListener('click',()=>setProfile('standard'));
function syncEngineSettings(){$('#voice-settings').hidden=$('#engine').value!=='supertonic'}
function selection(){let engine=$('#engine').value;return {engine,voice:$('#voice').value,source:$('#source').value,language:'nl',settings:engine==='supertonic'?readSettings():{}}}
loadSettings();syncEngineSettings();
async function load(){try{let s=await api('/api/session');if(!s.authenticated)return;csrf=s.csrf;$('#login').hidden=true;$('#workspace').hidden=false;$('#logout').hidden=false;voices=await api('/api/voices');$('#engine').value=localStorage.getItem('engine')||'piper';selectVoices();syncEngineSettings();await refresh()}catch(e){msg(e)}}
$('#loginform').onsubmit=async e=>{e.preventDefault();try{csrf=(await api('/api/login',{method:'POST',body:JSON.stringify({password:$('#password').value})})).csrf;$('#password').value='';await load()}catch(e){msg(e)}};
$('#logout').onclick=async()=>{await api('/api/logout',{method:'POST'});location.reload()};
$('#engine').onchange=()=>{localStorage.setItem('engine',$('#engine').value);selectVoices();syncEngineSettings()};$('#voice').onchange=()=>{localStorage.setItem('voice_'+$('#engine').value,$('#voice').value);syncFavorite()};$('#source').onchange=()=>renderRules();
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{for(const id of ['lab','dictionary'])$('#'+id).hidden=id!==b.dataset.tab});
$('#check-whisper').onclick=async()=>{
  const out=$('#whisper-health');out.textContent='Beschikbaarheid controleren…';
  try{const data=await api('/api/quality/health?model='+encodeURIComponent($('#quality-model').value));
    out.textContent=!data.reachable?'Whisper-service niet bereikbaar':`Service bereikbaar · binary ${data.binary_available?'aanwezig':'ontbreekt'} · model ${data.model_present===true?'aanwezig':data.model_present===false?'ontbreekt':'onbekend'} · checksum ${data.checksum_valid===true?'correct':data.checksum_valid===false?'ongeldig':'niet gecontroleerd'} · ${data.ready?'klaar voor analyse':'niet klaar'}${data.error?' · '+data.error:''}`;
  }catch(e){out.textContent=e.message}
};
$('#generate').onsubmit=async e=>{e.preventDefault();try{await api('/api/jobs',{method:'POST',body:JSON.stringify({...selection(),text:$('#text').value,label:$('#label').value,quality_model:$('#quality-enabled').checked?$('#quality-model').value:null})});msg('Opdracht toegevoegd aan de wachtrij.');await refresh()}catch(e){msg(e)}};
function formatSettings(engine, raw){
  try{const s=JSON.parse(raw);if(engine==='supertonic'){
    const steps=s.steps ?? s.total_steps;
    const silence=s.silence_duration;
    return 'Spreeksnelheid: '+Math.round(s.speed*100)+'%\nGeneratiestappen: '+steps+(s.total_steps!==undefined?' (historische metadata)':'')+'\nPauze tussen tekstfragmenten: '+(silence===undefined?'niet vastgelegd':Math.round(silence*1000)+' ms');
  }return 'Instellingen: '+raw}catch(e){return 'Instellingen: '+raw}
}
// Keep media elements and details nodes attached across background updates.
const jobCards = new Map(), ruleCards = new Map();
function updateJobs(jobs){
  const container=$('#jobs'), ids=new Set(jobs.map(j=>String(j.id)));
  for(const [id, card] of jobCards) if(!ids.has(id)){card.remove();jobCards.delete(id)}
  let empty=container.querySelector('.empty-jobs');
  if(!jobs.length){if(!empty){empty=document.createElement('p');empty.className='empty-jobs';empty.textContent='Nog geen opnamen.';container.append(empty)}return}
  if(empty)empty.remove();
  // Insert only new cards. Moving existing audio nodes can interrupt playback.
  for(const j of [...jobs].reverse()){
    const id=String(j.id); let card=jobCards.get(id);
    if(!card){
      card=document.createElement('article');card.className='item';card.dataset.jobId=id;
      card.innerHTML='<h3></h3><p class="muted"></p><div class="job-audio"></div><details><summary>Tekst en instellingen</summary><p class="original"></p><p class="spoken"></p><pre></pre><p class="quality"></p><button type="button" class="cancel-quality" hidden>Controle stoppen</button></details><label class="quality-controls">Whisper-model <select class="quality-model"><option value="base">Base</option><option value="tiny">Tiny</option><option value="small">Small</option></select></label><button class="quality-start">Controleer audiokwaliteit</button><button class="quality-history">Kwaliteitsrapporten</button><div class="quality-reports"></div><button class="rename">Label wijzigen</button><button class="delete">Verwijderen</button>';
      card.querySelector('.quality-start').onclick=async()=>{try{await api('/api/jobs/'+encodeURIComponent(id)+'/quality',{method:'POST',body:JSON.stringify({model:card.querySelector('.quality-model').value})});msg('Kwaliteitscontrole toegevoegd aan de wachtrij.');refresh()}catch(e){msg(e)}};
      card.querySelector('.quality-history').onclick=()=>showReports(card,id);
      card.querySelector('.rename').onclick=()=>window.renameJob(id);
      card.querySelector('.delete').onclick=()=>window.deleteJob(id);
      container.prepend(card);jobCards.set(id,card);
    }
    card.querySelector('h3').textContent=j.label||'Naamloze opname';
    card.querySelector('.muted').textContent=`${j.engine} · ${j.voice} · ${j.created_at} · ${j.status} ${j.error||''}`;
    card.querySelector('.original').textContent='Origineel: '+j.original;
    card.querySelector('.spoken').textContent='Uitgesproken: '+j.spoken;
    card.querySelector('pre').textContent=formatSettings(j.engine,j.settings)+'\nUitspraakregels: '+j.rules;
    let quality='';
    if(j.quality_status){
      quality='Whisper-controle: '+({queued:'in wachtrij',running:'audio analyseren',failed:'mislukt',done:'handmatig controleren',cancelled:'gestopt',interrupted:'herstel na herstart'}[j.quality_status]||j.quality_status);
      if(j.quality_error)quality+='\n'+j.quality_error;
      if(j.quality_report)quality+=' — open Kwaliteitsrapporten voor de bevindingen.'
    }
    card.querySelector('.quality').textContent=quality;
    const cancel=card.querySelector('.cancel-quality');cancel.hidden=!['queued','running'].includes(j.quality_status);cancel.onclick=async()=>{try{await api('/api/quality/'+encodeURIComponent(j.quality_id)+'/cancel',{method:'POST'});refresh()}catch(e){msg(e)}};
    card.querySelector('.delete').hidden=['queued','running'].includes(j.status);
    card.querySelector('.quality-controls').hidden=j.status!=='done';
    card.querySelector('.quality-start').hidden=j.status!=='done';
    card.querySelector('.quality-start').disabled=['queued','running','interrupted'].includes(j.quality_status);
    card.querySelector('.quality-history').hidden=j.status!=='done';
    const area=card.querySelector('.job-audio');
    if(j.status==='done'&&!area.querySelector('audio')){
      const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src='/api/jobs/'+encodeURIComponent(id)+'/audio';
      const download=document.createElement('a');download.className='download';download.href=audio.src+'?download=1';download.textContent='WAV downloaden';area.append(audio,download);
    }
  }
}
async function showReports(card,id){
  try{
    const reports=await api('/api/jobs/'+encodeURIComponent(id)+'/quality');
    const target=card.querySelector('.quality-reports');target.replaceChildren();
    if(!reports.length){target.textContent='Nog geen kwaliteitsrapporten.';return}
    const names={possible_repetition:'Mogelijke herhaling',possibly_missing:'Mogelijk ontbrekende woorden',unexpected_words:'Onverwachte woorden',possible_substitution:'Onzeker verschil',uncertain:'Onzekere herkenning',near_silence:'Technische waarschuwing'};
    for(const item of reports){
      const box=document.createElement('section');box.className='quality-report';
      const title=document.createElement('h4');title.textContent=item.created_at+' · '+item.model+' · '+item.status;box.append(title);
      if(item.error){const error=document.createElement('p');error.textContent=item.error;box.append(error)}
      if(item.report){try{
        const report=JSON.parse(item.report);
        for(const [label,value] of [['Verwachte uitgesproken tekst',report.expected],['Herkend transcript',report.transcript]]){const p=document.createElement('p');p.textContent=label+': '+(value||'niet beschikbaar');box.append(p)}
        const caution=document.createElement('p');caution.textContent='Whisper kan fouten missen of zelf verkeerd herkennen. Beluister de opname altijd.';box.append(caution);
        const list=document.createElement('ul');
        for(const f of report.findings||[]){const li=document.createElement('li');li.textContent=(names[f.type]||'Aandachtspunt')+': '+(f.message||('verwacht: '+(f.expected||[]).join(' ')+'; herkend: '+(f.heard||[]).join(' ')));
          if(f.time_range){const t=f.time_range;const jump=document.createElement('button');jump.type='button';jump.textContent='Ga naar ongeveer '+(t.start_ms/1000).toFixed(1)+'–'+(t.end_ms/1000).toFixed(1)+' s';jump.onclick=()=>{const audio=card.querySelector('audio');if(audio){audio.currentTime=t.start_ms/1000;audio.focus()}};li.append(' ',jump)}list.append(li)}
        if(!list.children.length){const li=document.createElement('li');li.textContent='Geen tekstverschillen gevonden; dit bewijst geen foutloze opname.';list.append(li)}box.append(list);
      }catch(e){const p=document.createElement('p');p.textContent='Rapport niet leesbaar';box.append(p)}}
      target.append(box);
    }
  }catch(e){msg(e)}
}
let blockedWorker=null;
function showWorkerStatus(status){
  blockedWorker=status.blocked?status:null;
  $('#worker-blocked').hidden=!blockedWorker;
  if(blockedWorker)$('#worker-blocked-text').textContent='De vorige '+status.engine+'-generatie is onderbroken of de verbinding is verbroken. De engine kan nog bezig zijn.';
}
$('#worker-recover').onclick=async()=>{
  if(!blockedWorker)return;
  if(!confirm('Heb je de betrokken enginecontainer volledig gestopt en opnieuw gestart, en gecontroleerd dat hij gereed is?'))return;
  try{await api('/api/worker/recover',{method:'POST',body:JSON.stringify({job_id:blockedWorker.job_id,confirmed_engine_stopped:true})});msg('Wachtrij hervat.');refresh()}catch(e){msg(e)}
};
let refreshRunning=false, refreshPending=false, refreshVersion=0;
async function refresh(poll=false){
  if($('#workspace').hidden||(poll&&refreshRunning))return;
  refreshPending=true;refreshVersion++;
  if(refreshRunning)return;
  refreshRunning=true;
  try{
    while(refreshPending){
      refreshPending=false;const version=refreshVersion;
      try{
        const [jobs,rules,status]=await Promise.all([api('/api/jobs'),api('/api/rules'),api('/api/worker/status')]);
        if(version!==refreshVersion)continue;
        updateJobs(jobs);allRules=rules;renderRules();showWorkerStatus(status);
      }catch(e){if(version===refreshVersion)msg(e)}
    }
  }finally{refreshRunning=false}
}
window.renameJob=async id=>{let label=prompt('Nieuw label');if(label!==null){try{await api('/api/jobs/'+id,{method:'PATCH',body:JSON.stringify({label})});refresh()}catch(e){msg(e)}}};window.deleteJob=async id=>{if(confirm('Deze opname definitief verwijderen?')){try{await api('/api/jobs/'+id,{method:'DELETE'});refresh()}catch(e){msg(e)}}};
function renderRules(){
  const container=$('#rules'), ids=new Set(allRules.map(r=>String(r.id)));
  for(const [id,card] of ruleCards)if(!ids.has(id)){card.remove();ruleCards.delete(id)}
  const q=$('#search').value.toLowerCase();
  for(const r of allRules){
    const id=String(r.id);let card=ruleCards.get(id);
    if(!card){
      card=document.createElement('article');card.className='item';card.dataset.ruleId=id;
      card.innerHTML='<h3></h3><p class="muted"></p><button class="play">▶ Beluisteren</button><button class="edit">Bewerken</button><button class="approve">Goedkeuren</button><button class="deactivate">Deactiveren</button><button class="history">Geschiedenis</button><button class="delete">Verwijderen</button><div class="history-content"></div>';
      card.querySelector('.history-content').id='history-'+id;
      card.querySelector('.play').onclick=()=>window.playRule(r.id);
      card.querySelector('.edit').onclick=()=>window.editRule(r.id);
      card.querySelector('.approve').onclick=()=>window.ruleAction(r.id,'approve');
      card.querySelector('.deactivate').onclick=()=>window.ruleAction(r.id,'deactivate');
      card.querySelector('.history').onclick=()=>window.historyRule(r.id);
      card.querySelector('.delete').onclick=()=>window.deleteRule(r.id);
      container.append(card);ruleCards.set(id,card);
    }
    card.hidden=!(r.language==='nl'&&r.source===$('#source').value&&r.original.toLowerCase().includes(q));
    card.querySelector('h3').textContent=r.original+' → '+r.replacement;
    card.querySelector('.muted').textContent=`${r.status} · versie ${r.version} ${r.note||''} ${r.engine||''} ${r.voice||''}`;
  }
}
$('#search').oninput=renderRules;$('#clear').onclick=()=>{$('#ruleform').reset();$('#ruleid').value=''};
$('#ruleform').onsubmit=async e=>{e.preventDefault();let id=$('#ruleid').value;try{await api('/api/rules'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify({...selection(),engine:$('#ruleengine').value||null,voice:$('#rulevoice').value||null,original:$('#original').value,replacement:$('#replacement').value,note:$('#note').value})});$('#clear').click();await refresh()}catch(e){msg(e)}};
window.editRule=id=>{let r=allRules.find(r=>r.id===id);$('#ruleid').value=id;$('#original').value=r.original;$('#replacement').value=r.replacement;$('#note').value=r.note;$('#ruleengine').value=r.engine||'';updateRuleVoices();$('#rulevoice').value=r.voice||'';window.scrollTo(0,0)};
window.ruleAction=async(id,action)=>{try{await api('/api/rules/'+id,{method:'PUT',body:JSON.stringify({action})});refresh()}catch(e){msg(e)}};window.deleteRule=async id=>{if(confirm('Deze uitspraak verwijderen?')){try{await api('/api/rules/'+id,{method:'DELETE'});refresh()}catch(e){msg(e)}}};window.historyRule=async id=>{try{let h=await api('/api/rules/'+id+'/history');$('#history-'+id).innerHTML='<pre>'+esc(JSON.stringify(h,null,2))+'</pre>'}catch(e){msg(e)}};
const previewRequests=new Map();
window.playRule=async id=>{
  const requestId=(previewRequests.get(id)||0)+1;previewRequests.set(id,requestId);
  try{
    const r=allRules.find(x=>x.id===id);if(!r)return;
    const job=await api('/api/previews',{method:'POST',body:JSON.stringify({...selection(),text:'Dit is de uitspraak van '+r.original+'.',label:'Uitspraaktest',test_rule:id})});
    msg('Uitspraaktest staat in de wachtrij.');
    while(previewRequests.get(id)===requestId){
      await new Promise(resolve=>setTimeout(resolve,2000));
      if(previewRequests.get(id)!==requestId)return;
      const j=await api('/api/previews/'+job.id);
      if(previewRequests.get(id)!==requestId)return;
      if(j.status==='done'){
        const target=document.getElementById('history-'+id);if(!target)return;
        const el=document.createElement('audio');el.controls=true;el.src='/api/jobs/'+encodeURIComponent(j.id)+'/audio';target.replaceChildren(el);el.play().catch(()=>{});return;
      }
      if(j.status==='failed'){msg(j.error);return}
    }
  }catch(e){if(previewRequests.get(id)===requestId)msg(e)}
};
load();setInterval(()=>refresh(true),4000);

function updateRuleVoices(){let engine=$('#ruleengine').value;$('#rulevoice').innerHTML='<option value="">Alle stemmen</option>'+(engine?(voices[engine]||[]).map(v=>`<option>${esc(v)}</option>`).join(''):'')}
$('#ruleengine').onchange=updateRuleVoices;
let importRows=[];
$('#previewimport').onclick=async()=>{try{let f=$('#importfile').files[0];if(!f||f.size>200000)throw Error('Kies een CSV of JSON van maximaal 200 kB');let format=f.name.toLowerCase().endsWith('.json')?'json':f.name.toLowerCase().endsWith('.csv')?'csv':null;if(!format)throw Error('Kies een CSV- of JSON-bestand');importRows=await api('/api/rules/import/preview',{method:'POST',body:JSON.stringify({format,content:await f.text()})});$('#importpreview').textContent=JSON.stringify(importRows,null,2);$('#commitimport').hidden=false}catch(e){msg(e)}};
$('#commitimport').onclick=async()=>{try{let result=await api('/api/rules/import',{method:'POST',body:JSON.stringify({rows:importRows.filter(r=>!r.duplicate)})});msg(result.imported+' voorstellen geïmporteerd');$('#commitimport').hidden=true;refresh()}catch(e){msg(e)}};

let csrf='', voices={}, allRules=[];
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...(opts.body?{'Content-Type':'application/json'}:{}),'X-CSRF-Token':csrf,...opts.headers}});if(!r.ok)throw Error((await r.text()).replace(/<[^>]*>/g,' ').trim().slice(0,220));return r.json()}
function msg(e){$('#message').textContent=e instanceof Error?e.message:e}
function selectVoices(){let e=$('#engine').value;$('#voice').innerHTML=voices[e].map(v=>`<option>${esc(v)}</option>`).join('');let saved=localStorage.getItem('voice_'+e);if(voices[e].includes(saved))$('#voice').value=saved}
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
$('#engine').onchange=()=>{localStorage.setItem('engine',$('#engine').value);selectVoices();syncEngineSettings()};$('#voice').onchange=()=>localStorage.setItem('voice_'+$('#engine').value,$('#voice').value);$('#source').onchange=()=>renderRules();
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{for(const id of ['lab','dictionary'])$('#'+id).hidden=id!==b.dataset.tab});
$('#generate').onsubmit=async e=>{e.preventDefault();try{await api('/api/jobs',{method:'POST',body:JSON.stringify({...selection(),text:$('#text').value,label:$('#label').value})});msg('Opdracht toegevoegd aan de wachtrij.');await refresh()}catch(e){msg(e)}};
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
      card.innerHTML='<h3></h3><p class="muted"></p><div class="job-audio"></div><details><summary>Tekst en instellingen</summary><p class="original"></p><p class="spoken"></p><pre></pre></details><button class="rename">Label wijzigen</button><button class="delete">Verwijderen</button>';
      card.querySelector('.rename').onclick=()=>window.renameJob(id);
      card.querySelector('.delete').onclick=()=>window.deleteJob(id);
      container.prepend(card);jobCards.set(id,card);
    }
    card.querySelector('h3').textContent=j.label||'Naamloze opname';
    card.querySelector('.muted').textContent=`${j.engine} · ${j.voice} · ${j.created_at} · ${j.status} ${j.error||''}`;
    card.querySelector('.original').textContent='Origineel: '+j.original;
    card.querySelector('.spoken').textContent='Uitgesproken: '+j.spoken;
    card.querySelector('pre').textContent=formatSettings(j.engine,j.settings)+'\nUitspraakregels: '+j.rules;
    card.querySelector('.delete').hidden=['queued','running'].includes(j.status);
    const area=card.querySelector('.job-audio');
    if(j.status==='done'&&!area.querySelector('audio')){
      const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src='/api/jobs/'+encodeURIComponent(id)+'/audio';
      const download=document.createElement('a');download.className='download';download.href=audio.src+'?download=1';download.textContent='WAV downloaden';area.append(audio,download);
    }
  }
}
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
        const [jobs,rules]=await Promise.all([api('/api/jobs'),api('/api/rules')]);
        if(version!==refreshVersion)continue;
        updateJobs(jobs);allRules=rules;renderRules();
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

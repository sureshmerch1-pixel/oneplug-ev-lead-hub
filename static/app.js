
let leads=[], sources=[];
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function toast(msg){const t=$('#toast');t.textContent=msg;t.style.display='block';setTimeout(()=>t.style.display='none',3500)}
async function load(){
  leads=await fetch('/api/leads').then(r=>r.json());
  sources=await fetch('/api/sources').then(r=>r.json());
  render();
}
function render(){
  $('#totalLeads').textContent=leads.length;
  $('#hotLeads').textContent=leads.filter(x=>x.priority.startsWith('A')).length;
  $('#newLeads').textContent=leads.filter(x=>x.status==='New').length;
  $('#sourceCount').textContent=sources.filter(x=>x.enabled).length;
  renderLeads(); renderSources();
}
function renderLeads(){
  const q=$('#search').value.toLowerCase(), p=$('#priorityFilter').value, st=$('#statusFilter').value;
  const rows=leads.filter(x=>(!q||JSON.stringify(x).toLowerCase().includes(q))&&(!p||x.priority===p)&&(!st||x.status===st));
  $('#leadRows').innerHTML=rows.map(x=>`
    <tr>
      <td><span class="pill ${x.priority.startsWith('A')?'hot':''}">${esc(x.priority)}</span></td>
      <td><div class="leadtitle">${esc(x.title)}</div><div class="sub">${esc(x.company||x.category)}</div></td>
      <td>${esc(x.location||'—')}</td>
      <td>${esc((x.intent||x.notes||'').slice(0,240))}</td>
      <td class="deadline">${esc(x.deadline||'—')}</td>
      <td><select onchange="setStatus(${x.id},this.value)">${['New','Contacted','Qualified','Proposal','Won','Lost'].map(s=>`<option ${s===x.status?'selected':''}>${s}</option>`).join('')}</select></td>
      <td><div>${esc(x.source_name||'Manual')}</div><div class="sub">${esc(x.published_at||'')}</div></td>
      <td><a class="open" href="${esc(x.lead_url)}" target="_blank" rel="noopener">Open lead ↗</a></td>
    </tr>`).join('');
}
function renderSources(){
  $('#sourceCards').innerHTML=sources.map(s=>`
    <div class="card"><div><strong>${esc(s.name)}</strong> <span class="pill">${esc(s.source_type)}</span><p>${esc(s.url)}</p><div class="meta">Last sync: ${esc(s.last_sync||'Never')} • ${esc(s.last_result||'')}</div></div>
    <div><button onclick="toggleSource(${s.id},${s.enabled?0:1})">${s.enabled?'Pause':'Enable'}</button> <button onclick="deleteSource(${s.id})">Delete</button></div></div>`).join('') || '<p class="sub">No auto sources yet. Add a Google Alert RSS feed or public source above.</p>';
}
async function setStatus(id,status){await fetch('/api/leads/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});load()}
async function toggleSource(id,enabled){await fetch('/api/sources/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!enabled})});load()}
async function deleteSource(id){if(confirm('Delete this source?')){await fetch('/api/sources/'+id,{method:'DELETE'});load()}}
$$('.tab').forEach(b=>b.onclick=()=>{$$('.tab').forEach(x=>x.classList.remove('active'));$$('.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('#'+b.dataset.tab).classList.add('active')})
['search','priorityFilter','statusFilter'].forEach(id=>$('#'+id).addEventListener('input',renderLeads));
$('#syncBtn').onclick=async()=>{const b=$('#syncBtn');b.disabled=true;b.textContent='Syncing…';try{const j=await fetch('/api/sync',{method:'POST'}).then(r=>r.json());toast(`Sync complete: ${j.new_leads} new lead(s)`);await load()}catch(e){toast('Sync failed. Check server/source logs.')}finally{b.disabled=false;b.textContent='↻ Sync sources now'}};
$('#sourceForm').onsubmit=async e=>{e.preventDefault();const body={name:$('#sourceName').value,url:$('#sourceUrl').value,source_type:$('#sourceType').value};const r=await fetch('/api/sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(r.ok){e.target.reset();toast('Source added');load()}else toast('Could not add source')};
$('#addLeadBtn').onclick=()=>$('#leadDialog').showModal();$('#cancelLead').onclick=()=>$('#leadDialog').close();
$('#leadForm').onsubmit=async e=>{e.preventDefault();const body={title:$('#lTitle').value,company:$('#lCompany').value,location:$('#lLocation').value,lead_url:$('#lUrl').value,intent:$('#lIntent').value,priority:$('#lPriority').value,deadline:$('#lDeadline').value,source_name:'Manual',status:'New'};const r=await fetch('/api/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(r.ok){$('#leadDialog').close();e.target.reset();toast('Lead added');load()}else toast('Lead already exists or could not be saved')};
$('#exportBtn').onclick=()=>{const cols=['priority','title','company','location','category','intent','deadline','status','source_name','lead_url','notes'];const csv=[cols.join(','),...leads.map(x=>cols.map(k=>'"'+String(x[k]??'').replaceAll('"','""')+'"').join(','))].join('\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='oneplug_ev_leads.csv';a.click();URL.revokeObjectURL(a.href)};
load();


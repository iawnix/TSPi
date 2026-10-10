"use strict";
const $ = id => document.getElementById(id);
const state = {token:"", workspace:null, next:null, generation:0, detail:null};
const source = {user:"用户任务", runtime:"执行记录", agent:"研究笔记"};
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let authenticate;
async function api(path) {
  const target = new URL(path, location.href);
  if (target.origin !== location.origin || !target.pathname.startsWith("/api/")) throw Error("无效的读取地址");
  const result = await fetch(target, {cache:"no-store", headers: state.token ? {Authorization:`Bearer ${state.token}`} : {}});
  if (result.status === 401) {
    state.token = "";
    if (!authenticate) authenticate = new Promise(resolve => {
      $("auth").showModal();
      $("auth-form").onsubmit = event => {event.preventDefault(); state.token = $("token").value; $("token").value=""; $("auth").close(); authenticate=null; resolve();};
    });
    await authenticate; return api(path);
  }
  const data = await result.json();
  if (!result.ok) throw Error(data.error || "读取失败");
  return data;
}
const route = path => `/api/workspace/${encodeURIComponent(state.workspace)}/${path}`;
function failure(error) {$("status").textContent=error.message; $("status").className="error";}
function recordCard(row) {return `<article class="record"><p class="meta">${esc(source[row.origin] || row.kind)} · ${esc(row.created_at || "")}</p><h3>${esc(row.title)}</h3><pre>${esc(row.excerpt ?? row.content)}</pre><button data-ref="${esc(row.ref)}">查看完整记录</button></article>`;}
async function refresh() {
  const generation=++state.generation;
  if (!state.workspace) return;
  const data=await api(route("snapshot"));
  if (generation !== state.generation) return;
  const view=data.snapshot;
  $("progress").innerHTML="<h2>研究问题</h2>"+view.nodes.map(node=>`<article class="record"><h3>${esc(node.title)}</h3><p class="meta">${esc(node.status)}</p><pre>${esc(node.goal)}</pre><p>${esc(node.progress)}</p><button data-ref="${esc(node.id)}">查看思路、结果与关系</button></article>`).join("");
  $("tasks").innerHTML="<h2>原始任务</h2>"+view.tasks.map(recordCard).join("");
  $("jobs").innerHTML="<h2>运行中或待收集的计算</h2>"+[...view.running_jobs,...view.uncollected_jobs].map(job=>`<p><code>${esc(job.job_id)}</code> · ${esc(job.state)} · ${esc(job.collection_state)}</p>`).join("");
  $("status").className=""; $("status").textContent=Object.keys(view.bounds.omitted).length ? "当前为部分进度快照。请检索下方记录查看完整历史。" : "已读取最新进度";
  await search(false,generation);
}
async function search(append=false,generation=state.generation) {
  const params=new URLSearchParams({query:$("query").value,offset:String(append ? state.next : 0),limit:"20"});
  if ($("origin").value) params.set("origin",$("origin").value);
  const data=await api(route(`records?${params}`));
  if(generation!==state.generation)return;
  if (!append) $("records").replaceChildren();
  $("records").insertAdjacentHTML("beforeend",data.records.map(recordCard).join(""));
  state.next=data.next_offset; $("more").hidden=state.next===null;
}
async function detail(ref,offset=0) {
  const workspace=state.workspace;
  const result=await api(route(`record/${encodeURIComponent(ref)}?offset=${offset}`));
  if(workspace!==state.workspace)return;
  if(!offset) {
    $("detail-content").textContent="";
    $("detail-links")?.remove();
    if(result.node) {
      const navigation=document.createElement("div"); navigation.id="detail-links";
      navigation.innerHTML=[...(result.relations || []).map(link=>({id:link.source===ref ? link.target : link.source,title:link.kind})),...(result.results || []).map(item=>({id:item.id,title:item.summary}))].map(item=>`<button data-ref="${esc(item.id)}">${esc(item.title)}</button>`).join("");
      $("detail-content").before(navigation);
    }
  }
  $("detail-content").textContent+=result.text;
  state.detail={ref,offset:result.next_offset}; $("detail-more").hidden=result.next_offset===null;
  if (!$("detail").open) $("detail").showModal();
}
document.addEventListener("click",event=>{const ref=event.target.closest("[data-ref]")?.dataset.ref;if(ref)detail(ref).catch(failure);});
$("close").onclick=()=>$("detail").close();
$("detail-more").onclick=()=>detail(state.detail.ref,state.detail.offset).catch(failure);
$("more").onclick=()=>search(true).catch(failure);
$("search").onsubmit=event=>{event.preventDefault();search(false,++state.generation).catch(failure);};
$("refresh").onclick=()=>refresh().catch(failure);
$("workspace").onchange=()=>{state.workspace=$("workspace").value;refresh().catch(failure);};
(async()=>{const catalog=await api("/api/workspaces");$("workspace").innerHTML=catalog.workspaces.map(row=>`<option value="${esc(row.workspace_id)}">${esc(row.label)}</option>`).join("");state.workspace=catalog.default_workspace;$("workspace").value=state.workspace || "";if(state.workspace)await refresh();else $("status").textContent="尚无已登记的工作区";})().catch(failure);

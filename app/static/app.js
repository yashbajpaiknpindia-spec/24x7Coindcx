function showToast(message){const el=document.getElementById('toast');if(!el)return;el.textContent=message;el.classList.add('visible');setTimeout(()=>el.classList.remove('visible'),3600)}
function moneyINR(v){return '₹'+Number(v||0).toLocaleString('en-IN',{maximumFractionDigits:2})}
async function refreshDash(){try{const r=await fetch('/api/dashboard');if(!r.ok)return;const d=await r.json();document.querySelectorAll('[data-refresh-key]').forEach(el=>{const parts=el.dataset.refreshKey.split('.');let v=d;parts.forEach(p=>v=v?.[p]);if(v!==undefined)el.textContent=v;})}catch(e){/* dashboard is still useful without auto-refresh */}}

function initResponsiveTables(){
 document.querySelectorAll('.table-wrap table').forEach((table,index)=>{
  const wrap=table.closest('.table-wrap');
  if(!wrap||wrap.dataset.tableEnhanced==='1')return;
  wrap.dataset.tableEnhanced='1';
  const hint=document.createElement('div');
  hint.className='table-scroll-hint';
  hint.textContent='Swipe horizontally to view all columns.';
  wrap.parentNode.insertBefore(hint,wrap);
  const updateHint=()=>{hint.hidden=wrap.scrollWidth<=wrap.clientWidth+4};
  updateHint();
  window.addEventListener('resize',updateHint,{passive:true});
  const body=table.tBodies[0];
  if(!body)return;
  const rows=Array.from(body.rows);
  const pageSize=25;
  if(rows.length<=pageSize)return;
  const tools=document.createElement('div');
  tools.className='table-tools';
  tools.innerHTML='<label>Filter rows <input type="search" autocomplete="off" placeholder="Search this table…" aria-label="Search table rows"></label><span class="table-count" aria-live="polite"></span><div class="table-pager"><button type="button" data-page-prev>Previous</button><span class="table-count" data-page-label></span><button type="button" data-page-next>Next</button></div>';
  wrap.parentNode.insertBefore(tools,wrap);
  const input=tools.querySelector('input');
  const count=tools.querySelector('.table-count');
  const label=tools.querySelector('[data-page-label]');
  const prev=tools.querySelector('[data-page-prev]');
  const next=tools.querySelector('[data-page-next]');
  let page=0,filtered=rows;
  const render=()=>{
   const query=input.value.trim().toLocaleLowerCase();
   filtered=rows.filter(row=>!query||row.textContent.toLocaleLowerCase().includes(query));
   const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
   page=Math.min(page,pages-1);
   const visible=new Set(filtered.slice(page*pageSize,(page+1)*pageSize));
   rows.forEach(row=>{row.hidden=!visible.has(row)});
   const start=filtered.length?page*pageSize+1:0;
   const end=Math.min((page+1)*pageSize,filtered.length);
   count.textContent='Showing '+start+'–'+end+' of '+filtered.length+' rows';
   label.textContent='Page '+(page+1)+' / '+pages;
   prev.disabled=page===0;
   next.disabled=page>=pages-1;
  };
  input.addEventListener('input',()=>{page=0;render()});
  prev.addEventListener('click',()=>{if(page>0){page--;render()}});
  next.addEventListener('click',()=>{if((page+1)*pageSize<filtered.length){page++;render()}});
  render();
 });
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initResponsiveTables);
else initResponsiveTables();

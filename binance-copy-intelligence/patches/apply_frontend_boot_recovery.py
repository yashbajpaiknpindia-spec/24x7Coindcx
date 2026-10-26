from pathlib import Path
import re

root=Path("/app")
html_path=root/"templates"/"index.html"
html=html_path.read_text()

if "BINANCE_INTEL_FRONTEND_RECOVERY_V1" not in html:
    pattern=re.compile(r'(?P<tag><script\b[^>]*\bsrc\s*=\s*(?P<q>["\'])(?P<src>[^"\']*app\.js[^"\']*)(?P=q)[^>]*>\s*</script>)',re.I|re.S)
    matches=list(pattern.finditer(html))
    if len(matches)!=1:
        raise RuntimeError(f"Expected one app.js script to instrument; found {len(matches)}")

    before=r"""
<script id="BINANCE_INTEL_FRONTEND_DIAGNOSTICS_V1">
(function(){
  function ensureBanner(){
    var el=document.getElementById("bi-live-diagnostic");
    if(el)return el;
    el=document.createElement("div");el.id="bi-live-diagnostic";
    el.setAttribute("role","status");el.setAttribute("aria-live","polite");
    el.style.cssText="display:block;position:relative;z-index:9999;margin:8px 16px;padding:10px 14px;border-radius:9px;font:13px/1.45 system-ui,sans-serif;background:#112331;color:#dceaf4;border:1px solid #2e5262;white-space:pre-wrap;overflow-wrap:anywhere";
    var main=document.querySelector("main")||document.body;
    main.insertBefore(el,main.firstChild);
    return el;
  }
  window.__biShowDiagnostic=function(message,isError){
    try{
      var el=ensureBanner();
      el.style.background=isError?"#3b2027":"#112b2a";
      el.style.color=isError?"#ffe0e5":"#d8fff1";
      el.style.borderColor=isError?"#a34a58":"#2d7969";
      el.textContent=(isError?"DATA LOAD ERROR · ":"DATA CONNECTION · ")+String(message||"Unknown issue").slice(0,1600);
      el.style.display="block";
    }catch(_){}
  };
  window.addEventListener("error",function(e){
    var message=(e&&e.message)||"JavaScript runtime error";
    var where=e&&e.filename?(" · "+e.filename.split("/").pop()+":"+(e.lineno||"?")):"";
    window.__biShowDiagnostic(message+where,true);
  });
  window.addEventListener("unhandledrejection",function(e){
    var r=e&&e.reason;window.__biShowDiagnostic("Unhandled dashboard promise: "+(r&&r.message?r.message:String(r||"unknown")),true);
  });
})();
</script>
"""
    after=r"""
<script id="BINANCE_INTEL_BOOT_RECOVERY_V1">
(function(){
  var active=false,lastOk=0,lastMessage="";
  function show(msg,bad){if(window.__biShowDiagnostic)window.__biShowDiagnostic(msg,bad);}
  async function safeCall(name,args){
    try{
      var fn=window[name];
      if(typeof fn!=="function")return {name:name,available:false};
      var value=fn.apply(window,args||[]);
      if(value&&typeof value.then==="function")await value;
      return {name:name,available:true,ok:true};
    }catch(e){
      show(name+"() failed: "+(e&&e.message||e),true);
      return {name:name,available:true,ok:false,error:String(e&&e.message||e)};
    }
  }
  async function probe(){
    var out={};
    for(var path of ["/health","/api/status"]){
      try{
        var r=await fetch(path,{credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
        var raw=await r.text(),body=null;
        try{body=JSON.parse(raw)}catch(_){}
        out[path]={http:r.status,ok:r.ok,body:body};
        if(!r.ok){
          var detail=body&&(body.error||body.message||body.reason);
          show(path+" returned HTTP "+r.status+(detail?": "+detail:"")+". The dashboard cannot load until this request succeeds.",true);
          return {ok:false,detail:out};
        }
        if(path==="/api/status"&&body&&typeof body==="object"&&(body.error||body.authenticated===false)){
          show(path+" says "+(body.error||"authentication required")+". Lock the workspace and sign in again.",true);
          return {ok:false,detail:out};
        }
      }catch(e){
        out[path]={error:String(e&&e.message||e)};
        show("Could not reach "+path+": "+(e&&e.message||e),true);
        return {ok:false,detail:out};
      }
    }
    return {ok:true,detail:out};
  }
  var loaders={
    "overview":[["refreshStatus",[]],["loadRunsOnly",[]]],
    "traders":[["loadTraders",[]]],
    "portfolio-lab":[["loadPortfolioLab",[]]],
    "multi-trader":[["loadMultiTrader",[false]],["loadMTHistory",[]]],
    "history":[["loadPaths",[]]],
    "system":[["loadSystem",[]]],
    "reports":[["loadReports",[]],["loadRunsOnly",[]]],
    "data":[["loadData",[]],["loadRunsOnly",[]]]
  };
  async function loadView(name){
    var list=loaders[name]||[];
    var results=[];
    for(var pair of list){
      var r=await safeCall(pair[0],pair[1]);
      if(r.available)results.push(r);
    }
    return results;
  }
  function currentView(){
    var el=document.querySelector(".view.active,[id^='view-'].active");
    if(el&&el.id)return el.id.replace(/^view-/,"");
    var nav=document.querySelector("[data-view].active,[data-view][aria-current='page']");
    return nav?nav.getAttribute("data-view"):"overview";
  }
  async function boot(){
    if(active)return;active=true;
    var p=await probe();
    if(!p.ok){active=false;return;}
    var name=currentView()||"overview";
    var results=await loadView(name);
    var available=results.length;
    if(!available){
      // In a non-module script function declarations are normally global; this also
      // catches a stale/partially executed bundle without silently leaving placeholders.
      results=await loadView("overview");
    }
    lastOk=Date.now();
    lastMessage="API reachable (HTTP 200); startup recovery invoked "+results.map(function(x){return x.name+(x.ok?"()":"() failed")}).join(", ")+".";
    show(lastMessage,false);
    active=false;
  }
  document.addEventListener("click",function(event){
    var target=event.target&&event.target.closest?event.target.closest("[data-view]"):null;
    if(!target)return;
    var name=target.getAttribute("data-view");
    setTimeout(function(){loadView(name).then(function(rows){
      if(rows.some(function(x){return !x.ok}))return;
      lastOk=Date.now();
    });},350);
  },true);
  function start(){setTimeout(function(){boot().catch(function(e){active=false;show("Startup recovery failed: "+(e&&e.message||e),true)});},900);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
  window.addEventListener("pageshow",function(){if(!lastOk||Date.now()-lastOk>15000){active=false;boot().catch(function(e){active=false;show(String(e),true)})}});
})();
</script>
"""
    m=matches[0]
    replacement=before+"\n"+m.group("tag")+"\n"+after
    html=html[:m.start()]+replacement+html[m.end():]
    html_path.write_text(html)

print("Frontend boot recovery installed: startup API probe, visible auth/runtime diagnostics, and per-page loader recovery.")

from pathlib import Path

root=Path("/app")
html_path=root/"templates"/"index.html"
html=html_path.read_text()

if "BINANCE_INTEL_NAVIGATION_FAILSAFE_V2" not in html:
    views=("overview","traders","portfolio-lab","multi-trader","history","reports","data","system")
    missing=[v for v in views if f'id="view-{v}"' not in html]
    if missing:
        raise RuntimeError(f"Expected dashboard sections are missing: {missing}")
    nav_missing=[v for v in views if f'data-view="{v}"' not in html]
    if nav_missing:
        raise RuntimeError(f"Expected dashboard navigation links are missing: {nav_missing}")

    script = r"""
<script id="BINANCE_INTEL_NAVIGATION_FAILSAFE_V2">
(function(){
  "use strict";
  var titles={
    "overview":"Overview","traders":"Trader universe","portfolio-lab":"Portfolio Lab",
    "multi-trader":"Multi-Trader Mode","history":"Trade behaviour",
    "reports":"Reports & exports","data":"Data import","system":"Source & system"
  };
  function diagnose(message,bad){
    if(window.__biShowDiagnostic){window.__biShowDiagnostic(message,!!bad);return;}
    var el=document.getElementById("bi-live-diagnostic");
    if(!el){
      el=document.createElement("div");el.id="bi-live-diagnostic";
      el.style.cssText="position:relative;z-index:9999;margin:8px 16px;padding:10px 14px;border-radius:8px;font:14px/1.5 system-ui;background:#112331;color:#fff;white-space:pre-wrap";
      (document.querySelector("main")||document.body).insertBefore(el,(document.querySelector("main")||document.body).firstChild);
    }
    el.textContent=(bad?"PAGE LOAD ERROR · ":"PAGE · ")+String(message).slice(0,1400);
    el.style.background=bad?"#3b2027":"#112b2a";
  }
  function activate(name){
    var section=document.getElementById("view-"+name);
    if(!section){diagnose("No section exists for page '"+name+"'.",true);return false;}
    document.querySelectorAll(".view").forEach(function(el){
      var on=el===section;
      el.classList.toggle("active",on);
      if(on){el.removeAttribute("aria-hidden");}
      else{el.setAttribute("aria-hidden","true");}
    });
    document.querySelectorAll(".nav-link[data-view]").forEach(function(el){
      var on=el.getAttribute("data-view")===name;
      el.classList.toggle("active",on);
      if(on)el.setAttribute("aria-current","page");else el.removeAttribute("aria-current");
    });
    var title=document.getElementById("page-title");
    if(title)title.textContent=titles[name]||name;
    try{if(typeof state!=="undefined"&&state)state.view=name;}catch(_){}
    return true;
  }
  async function callRequired(label,fn){
    if(typeof fn!=="function")throw new Error("The "+label+" loader is not available in the current JavaScript bundle.");
    await Promise.resolve(fn());
    return label;
  }
  async function load(name){
    if(!activate(name))return;
    var called=[];
    try{
      switch(name){
        case "overview":
          if(typeof refreshStatus==="function")called.push(await callRequired("overview status",refreshStatus));
          if(typeof loadRunsOnly==="function")called.push(await callRequired("overview scan history",loadRunsOnly));
          break;
        case "traders":
          called.push(await callRequired("Trader universe",function(){return loadTraders()}));
          break;
        case "portfolio-lab":
          called.push(await callRequired("Portfolio Lab",function(){return loadPortfolioLab()}));
          break;
        case "multi-trader":
          called.push(await callRequired("Multi-Trader",function(){return loadMultiTrader(false)}));
          if(typeof loadMTHistory==="function")called.push(await callRequired("Multi-Trader history",loadMTHistory));
          break;
        case "history":
          called.push(await callRequired("Trade behaviour",function(){return loadPaths()}));
          break;
        case "system":
          called.push(await callRequired("Source & system",function(){return loadSystem()}));
          break;
        case "reports":
          if(typeof loadReports==="function")called.push(await callRequired("Reports",loadReports));
          else if(typeof loadRunsOnly==="function")called.push(await callRequired("Reports / scan history",loadRunsOnly));
          break;
        case "data":
          if(typeof loadData==="function")called.push(await callRequired("Data import",loadData));
          else if(typeof loadDataImport==="function")called.push(await callRequired("Data import",loadDataImport));
          break;
      }
      diagnose(titles[name]+": page activated"+(called.length?"; refreshed "+called.join(", "):"; static controls ready")+".",false);
    }catch(e){
      diagnose(titles[name]+" opened but data loading failed: "+String(e&&e.message||e)+". The page remains visible so the error is inspectable.",true);
      try{console.error("BINANCE_INTEL_PAGE_LOAD_FAILURE",name,e);}catch(_){}
    }
  }
  // Capture navigation before a broken legacy click handler can cancel or misroute it.
  document.addEventListener("click",function(event){
    var nav=event.target&&event.target.closest?event.target.closest(".nav-link[data-view]"):null;
    if(!nav)return;
    var name=nav.getAttribute("data-view");
    if(!Object.prototype.hasOwnProperty.call(titles,name))return;
    event.preventDefault();
    event.stopImmediatePropagation();
    load(name).catch(function(e){diagnose(titles[name]+" failed: "+String(e&&e.message||e),true);});
  },true);
  // Restore the initial overview data even if the original bundle's initializer aborted.
  function start(){
    var name=Object.keys(titles).find(function(k){var el=document.getElementById("view-"+k);return el&&el.classList.contains("active");})||"overview";
    load(name).catch(function(e){diagnose(titles[name]+" startup failed: "+String(e&&e.message||e),true);});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",function(){setTimeout(start,100);},{once:true});
  else setTimeout(start,100);
})();
</script>
"""
    if "</body>" not in html:
        raise RuntimeError("Cannot install navigation failsafe: missing </body>")
    html=html.replace("</body>",script+"\n</body>",1)
    html_path.write_text(html)

print("Navigation failsafe installed: all eight views explicitly activate and each data page runs its loader with visible failures.")

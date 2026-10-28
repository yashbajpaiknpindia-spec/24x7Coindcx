from pathlib import Path

APP_PATH = Path("/app/app.py")
source = APP_PATH.read_text()

truthy_old = '    can_purchase = bool(product.get("canPurchase", False))'
truthy_new = '    can_raw = product.get("canPurchase", False)\n    can_purchase = (can_raw is True) or (str(can_raw).strip().lower() in ("true", "1", "yes"))'
if truthy_old in source:
    source = source.replace(truthy_old, truthy_new, 1)

load_old = '''async function load(){
 try{const state=await req("/api/dual-investment/state");render(state);
 if(!state.latest_scan){await scanNow(true)}
 }catch(e){setStatus("Could not load stored paper state: "+e.message+". Attempting an API scan.");await scanNow(true)}
}
'''
load_new = '''async function load(){
 try{
   const state=await req("/api/dual-investment/state");
   render(state);
   const age=state.latest_scan&&state.latest_scan.started_at_utc?Date.now()-Date.parse(state.latest_scan.started_at_utc):Infinity;
   if(!state.latest_scan||!Number.isFinite(age)||age>300000){await scanNow(true)}
 }catch(e){
   setStatus("Could not load stored paper state: "+e.message+". Attempting an API scan.");
   await scanNow(true)
 }
}
'''
if load_old in source:
    source = source.replace(load_old, load_new, 1)
elif load_new not in source:
    raise RuntimeError("Cannot enable five-minute page-session scan refresh: load() anchor not found")

APP_PATH.write_text(source)
print("Applied Dual Investment scan refresh and API boolean-normalisation fixes.")

#!/usr/bin/env python3
"""Read-only CoinDCX public 1m candle downloader; no keys and no order endpoints."""
import csv, gzip, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import requests

ROOT=Path("research_artifacts/six_month_scalping_audit")
PART=ROOT/"partial"; OUT=ROOT/"candles"
START=datetime(2026,4,20,23,29,tzinfo=timezone.utc)
END=datetime(2026,10,19,23,29,tzinfo=timezone.utc) # exclusive; last expected close 23:28
ASSETS=["BTC","ETH","SOL","ZEC","XRP","BNB","DOGE","NEAR","SUI","UNI"]
PRODUCTS=["spot","futures"]; HOURS=12; WORKERS=4; MIN_GAP=.12; RETRIES=6
FIELDS=["time","open","high","low","close","volume"]
PART.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
rl=threading.Lock(); next_call=0.0; pl=threading.Lock()
def log(s):
    with pl: print(datetime.now(timezone.utc).isoformat(timespec="seconds"),s,flush=True)
def throttle():
    global next_call
    with rl:
        now=time.monotonic(); slot=max(now,next_call); next_call=slot+MIN_GAP
    if slot>now: time.sleep(slot-now)
def ms(dt): return int(dt.timestamp()*1000)
def candle_ms(v):
    n=int(float(v)); return n*1000 if n<100_000_000_000 else n
def get_json(sess,url,params):
    err=None
    for i in range(RETRIES):
        throttle()
        try:
            r=sess.get(url,params=params,timeout=(8,35))
            if r.status_code==429 or r.status_code>=500:
                wait=float(r.headers.get("Retry-After",min(2**i,30)))
                log(f"HTTP {r.status_code}; backoff {wait:.1f}s"); time.sleep(wait); err=RuntimeError(r.text[:150]); continue
            r.raise_for_status(); return r.json()
        except Exception as e:
            err=e
            if i<RETRIES-1: time.sleep(min(2**i,20))
    raise RuntimeError(f"request failed after retries: {url} {params}: {err}")
def rows_from(payload,product,start,end):
    if product=="futures":
        if not isinstance(payload,dict) or payload.get("s") not in (None,"ok"): raise ValueError(f"bad futures response {str(payload)[:150]}")
        data=payload.get("data",[])
    else: data=payload
    if not isinstance(data,list): raise ValueError(f"bad payload type {type(data)}")
    found={}
    for x in data:
        if not isinstance(x,dict) or "time" not in x: continue
        t=candle_ms(x["time"])
        if not ms(start)<=t<ms(end): continue
        row={"time":t}
        for c in FIELDS[1:]: row[c]=x.get(c, x.get("vol") if c=="volume" else None)
        found[t]=row
    return [found[t] for t in sorted(found)]
def fetch_chunk(sess,prod,pair,a,b):
    if prod=="spot":
        url="https://api.coindcx.com/market_data/candles"
        params={"pair":pair,"interval":"1m","startTime":ms(a),"endTime":ms(b)-1,"limit":1000}
    else:
        url="https://public.coindcx.com/market_data/candlesticks"
        params={"pair":pair,"from":int(a.timestamp()),"to":int((b-timedelta(seconds=1)).timestamp()),"resolution":"1","pcode":"f"}
    return rows_from(get_json(sess,url,params),prod,a,b)
CHUNKS=[]
x=START
while x<END:
    y=min(x+timedelta(hours=HOURS),END); CHUNKS.append((x,y)); x=y
def save_state(path,state):
    tmp=path.with_suffix(".tmp"); tmp.write_text(json.dumps(state,indent=2)); tmp.replace(path)
def one_series(prod,asset):
    pair=f"B-{asset}_USDT"; stem=f"{prod}_{asset}_1m"
    raw=PART/f"{stem}.csv"; statefile=PART/f"{stem}.json"; final=OUT/f"{stem}.csv.gz"
    st=json.loads(statefile.read_text()) if statefile.exists() else {"next":0,"empty":0,"calls":0}
    if int(st.get("next",0))==0 and raw.exists(): raw.unlink()
    if not raw.exists():
        with raw.open("w",newline="") as f: csv.DictWriter(f,fieldnames=FIELDS).writeheader()
    sess=requests.Session(); sess.headers.update({"User-Agent":"CoinDCX-public-candle-research/1.0"})
    try:
        for i in range(int(st.get("next",0)),len(CHUNKS)):
            a,b=CHUNKS[i]
            try: rr=fetch_chunk(sess,prod,pair,a,b)
            except Exception as e:
                st.update({"last_error":str(e),"failed_chunk":i,"updated":datetime.now(timezone.utc).isoformat()}); save_state(statefile,st); raise
            if rr:
                # Append one complete chunk; if interrupted between append and checkpoint,
                # final timestamp de-duplication makes a retry safe.
                with raw.open("a",newline="") as f:
                    w=csv.DictWriter(f,fieldnames=FIELDS); w.writerows(rr); f.flush(); os.fsync(f.fileno())
            else: st["empty"]=int(st.get("empty",0))+1
            st["next"]=i+1; st["calls"]=int(st.get("calls",0))+1; st["updated"]=datetime.now(timezone.utc).isoformat(); save_state(statefile,st)
            if (i+1)%60==0 or i==len(CHUNKS)-1: log(f"{stem}: chunk {i+1}/{len(CHUNKS)} ({len(rr)} rows)")
        df=pd.read_csv(raw)
        if len(df):
            for c in FIELDS: df[c]=pd.to_numeric(df[c],errors="coerce")
            df=df.dropna(subset=FIELDS).drop_duplicates("time").sort_values("time")
            df=df[(df.open>0)&(df.high>=df[["open","low","close"]].max(axis=1))&(df.low<=df[["open","high","close"]].min(axis=1))&(df.volume>=0)]
        else: df=pd.DataFrame(columns=FIELDS)
        df.to_csv(final,index=False,compression="gzip")
        t=df.time.astype("int64") if len(df) else pd.Series(dtype="int64")
        expected=int((END-START).total_seconds()/60)
        span_expected=(int((t.max()-t.min())/60000)+1) if len(t) else 0
        gaps=int((t.diff().dropna()!=60000).sum()) if len(t)>1 else 0
        return {"product":prod,"asset":asset,"pair":pair,"bars":len(df),"expected_window_bars":expected,
          "window_coverage_pct":round(100*len(df)/expected,4),"span_coverage_pct":round(100*len(df)/span_expected,4) if span_expected else 0,
          "internal_gaps":gaps,"start_utc":datetime.fromtimestamp(int(t.min())/1000,tz=timezone.utc).isoformat() if len(t) else None,
          "end_utc":datetime.fromtimestamp(int(t.max())/1000,tz=timezone.utc).isoformat() if len(t) else None,
          "chunks_completed":st.get("next",0),"chunks_expected":len(CHUNKS),"empty_chunks":st.get("empty",0),"complete":st.get("next",0)==len(CHUNKS),"path":str(final)}
    finally: sess.close()
def main():
    log(f"Public-only 1m collection [{START.isoformat()}, {END.isoformat()}); {len(CHUNKS)} chunks/series; rate <= {1/MIN_GAP:.1f} req/s")
    results=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fs={ex.submit(one_series,p,a):(p,a) for p in PRODUCTS for a in ASSETS}
        for f in as_completed(fs):
            p,a=fs[f]
            try:
                r=f.result(); results.append(r); log(f"DONE {p}/{a}: {r['bars']:,} bars, window={r['window_coverage_pct']}%, internal gaps={r['internal_gaps']}, complete={r['complete']}")
            except Exception as e:
                results.append({"product":p,"asset":a,"pair":f"B-{a}_USDT","complete":False,"error":str(e)}); log(f"ERROR {p}/{a}: {e}")
    aud=pd.DataFrame(results).sort_values(["product","asset"]); aud.to_csv(ROOT/"data_audit.csv",index=False)
    manifest={"source":"CoinDCX public REST candles only; no auth, keys or orders",
      "start_utc":START.isoformat(),"end_exclusive_utc":END.isoformat(),"last_expected_candle_utc":(END-timedelta(minutes=1)).isoformat(),
      "products":PRODUCTS,"assets":ASSETS,"chunks_hours":HOURS,"chunks_per_series":len(CHUNKS),"workers":WORKERS,
      "global_request_spacing_seconds":MIN_GAP,"strategy_time_splits":{"train":"2026-04-20T23:29Z/2026-07-20T23:29Z","validation":"2026-07-20T23:29Z/2026-08-20T23:29Z","locked_month":"2026-08-20T23:29Z/2026-09-19T23:29Z","known_recent":"2026-09-19T23:29Z/2026-10-19T23:29Z"},
      "caveats":["current 10-asset universe has survivorship bias","OHLCV not orderbook, full trade prints, or executable fills","funding not included","locked month must not guide parameter selection"]}
    (ROOT/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print(aud.to_string(index=False))
    bad=aud[(~aud.complete.fillna(False)) | (aud.window_coverage_pct.fillna(0)<95)]
    if len(bad): log(f"WARNING: {len(bad)} series are incomplete or under 95% window coverage."); sys.exit(2)
if __name__=="__main__": main()

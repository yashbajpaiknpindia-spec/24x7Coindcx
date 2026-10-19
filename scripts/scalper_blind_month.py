import csv,gzip,json,math,os,sys,time,statistics
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests

OUT=Path("blind_test_output"); DATA=OUT/"candles"; DATA.mkdir(parents=True,exist_ok=True)
ASSETS=["BTC","ETH","SOL","ZEC","XRP","BNB","DOGE","NEAR","SUI","UNI"]
PRODUCTS=["spot","futures"]; DAYS=30; BLIND_DAYS=7
MIN_TURNOVER=250000.0; SPREAD_BPS=8.0; SLIP_SIDE=0.05
SPOT_FEE=0.15; FUT_FEE=0.075; GST=18.0; TAX=31.2
TARGET=0.15; STOP=0.40; HOLD=15; NOTIONAL=30.0
def iso(ms): return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
def get_json(url,params):
    err=None
    for n in range(6):
        try:
            r=requests.get(url,params=params,timeout=25,headers={"User-Agent":"CoinDCX-public-scalper-research/1.0"})
            if r.status_code in (429,500,502,503,504): time.sleep(min(2*(n+1),10)); continue
            r.raise_for_status(); return r.json()
        except Exception as e: err=e; time.sleep(min(n+1,8))
    raise RuntimeError(str(err))
def norm(rows):
    if isinstance(rows,dict): rows=rows.get("data",rows.get("candles",rows.get("result",[])))
    out=[]
    for r in rows if isinstance(rows,list) else []:
        try:
            t=int(float(r.get("time",r.get("t",r.get("timestamp",0)))))
            if t<10000000000:t*=1000
            o,h,l,c,v=[float(r.get(a,r.get(b,0)) or 0) for a,b in [("open","o"),("high","h"),("low","l"),("close","c"),("volume","v")]]
            if t>0 and min(o,h,l,c)>0 and h>=max(o,c) and l<=min(o,c) and h>=l and all(math.isfinite(x) for x in (o,h,l,c,v)):
                out.append({"time":t,"open":o,"high":h,"low":l,"close":c,"volume":max(0,v)})
        except Exception: pass
    return sorted({x["time"]:x for x in out}.values(),key=lambda x:x["time"])
def fetch(job,start,end):
    product,asset=job; pair="B-"+asset+"_USDT"; cursor=start; rows=[]; calls=0
    while cursor<=end:
        right=min(end,cursor+999*60000)
        if product=="spot":
            url="https://api.coindcx.com/market_data/candles"
            params={"pair":pair,"interval":"1m","startTime":cursor,"endTime":right,"limit":1000}
        else:
            url="https://public.coindcx.com/market_data/candlesticks"
            params={"pair":pair,"from":cursor//1000,"to":right//1000,"resolution":"1","pcode":"f"}
        rows += [x for x in norm(get_json(url,params)) if cursor<=x["time"]<=right]
        calls+=1; cursor=right+60000; time.sleep(.12)
    rows=sorted({x["time"]:x for x in rows}.values(),key=lambda x:x["time"])
    path=DATA/(product+"_"+asset+"_1m.csv.gz")
    with gzip.open(path,"wt",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader();w.writerows(rows)
    expected=(end-start)//60000+1
    gaps=sum(b["time"]-a["time"]!=60000 for a,b in zip(rows,rows[1:]))
    return {"product":product,"asset":asset,"path":str(path),"bars":len(rows),"expected":expected,"coverage":len(rows)/max(expected,1),"gaps":gaps,"calls":calls}
def read(path):
    with gzip.open(path,"rt") as f:return [{k:(int(r[k]) if k=="time" else float(r[k])) for k in ("time","open","high","low","close","volume")} for r in csv.DictReader(f)]
def costs(product):
    fee=(SPOT_FEE if product=="spot" else FUT_FEE)*2*(1+GST/100)
    slip=SLIP_SIDE*2
    spread=SPREAD_BPS/100
    return fee,slip,spread
def net(product,gross):
    fee,slip,spread=costs(product); n=gross-fee-slip-spread
    if gross>0:n-=(gross if product=="spot" else max(0,gross-fee-slip))*TAX/100
    return n
def estimated(product,move):
    fee,slip,spread=costs(product);g=max(0,move)-spread
    if product=="spot":return g-fee-slip-max(0,g)*TAX/100
    p=g-fee-slip;return p-max(0,p)*TAX/100
VARIANTS={
 "current_proxy":{"floor":.05,"veto":True,"confirm1":False},
 "reversal_veto_relaxed":{"floor":.05,"veto":False,"confirm1":False},
 "lower_noise_floor":{"floor":.02,"veto":True,"confirm1":False},
 "one_minute_confirm":{"floor":.05,"veto":True,"confirm1":True}}
def replay(rows,product,cfg,start,end,name,asset):
    if len(rows)<1500:return []
    q=[r["close"]*r["volume"] for r in rows]; roll=[]; acc=0
    for i,v in enumerate(q):
        acc+=v
        if i>=1440:acc-=q[i-1440]
        roll.append(acc)
    out=[];next_allowed=start
    for i in range(1441,len(rows)-HOLD-2):
        b=rows[i];t=b["time"]
        if t<start or t>end or t<next_allowed or roll[i]<MIN_TURNOVER:continue
        if any(rows[j+1]["time"]-rows[j]["time"]!=60000 for j in range(i-10,i+HOLD+1)):continue
        r5=(b["close"]/rows[i-5]["close"]-1)*100
        prev=(rows[i-5]["close"]/rows[i-10]["close"]-1)*100
        r1=(b["close"]/rows[i-1]["close"]-1)*100
        if not r5 or abs(r5)<cfg["floor"]:continue
        side="buy" if r5>0 else "sell"
        if product=="spot" and side=="sell":continue
        d=1 if side=="buy" else -1; aligned=d*prev
        if cfg["veto"] and aligned < -cfg["floor"]:continue
        if cfg["confirm1"] and d*r1<=0:continue
        cont=max(0,.65*abs(r5)+.35*max(0,aligned))
        if estimated(product,cont)<TARGET:continue
        if abs(r5)>=.75 and abs(r5)>max(abs(prev)*1.8,.25):continue
        entrybar=rows[i+1];entry=entrybar["open"]; exit_i=min(i+HOLD+1,len(rows)-1);reason="time"; gross=((rows[exit_i]["close"]/entry-1)*100)*d
        for j in range(i+1,min(i+HOLD+2,len(rows))):
            x=rows[j]
            fav=((x["high"]/entry-1)*100 if side=="buy" else (entry/x["low"]-1)*100)
            adv=((x["low"]/entry-1)*100 if side=="buy" else (entry/x["high"]-1)*100)
            th=net(product,fav)>=TARGET; sh=net(product,adv)<=-STOP
            if sh or th:
                exit_i=j
                if sh:reason="stop"; gross=-(STOP+sum(costs(product)))
                else:
                    reason="target";lo,hi=0.,10.
                    for _ in range(45):
                        m=(lo+hi)/2
                        if net(product,m)>=TARGET:hi=m
                        else:lo=m
                    gross=hi
                break
        n=net(product,gross)
        if reason=="target":n=TARGET
        if reason=="stop":n=-STOP
        out.append({"variant":name,"product":product,"asset":asset,"side":side,"entry_time":entrybar["time"],"exit_time":rows[exit_i]["time"],"gross_move_pct":gross,"net_pct":n,"net_usdt":NOTIONAL*n/100,"reason":reason,"r5":r5,"prev5":prev,"continuation":cont,"estimated_net":estimated(product,cont),"turnover_proxy":roll[i]})
        next_allowed=rows[exit_i]["time"]+5*60000
    return out
def metric(ts):
    if not ts:return {"trades":0,"win_rate_pct":None,"pf":None,"net_usdt":0,"max_dd_usdt":0,"targets":0,"stops":0,"time_exits":0}
    ns=[x["net_usdt"] for x in ts]; wins=sum(x for x in ns if x>0);loss=sum(x for x in ns if x<0);eq=peak=dd=0
    for x in ns:eq+=x;peak=max(peak,eq);dd=min(dd,eq-peak)
    return {"trades":len(ts),"win_rate_pct":round(100*sum(x>0 for x in ns)/len(ns),2),"pf":round(wins/abs(loss),4) if loss else (99 if wins else None),"net_usdt":round(sum(ns),4),"max_dd_usdt":round(dd,4),"targets":sum(x["reason"]=="target" for x in ts),"stops":sum(x["reason"]=="stop" for x in ts),"time_exits":sum(x["reason"]=="time" for x in ts)}
def main():
    end=(int(time.time()*1000)//60000)*60000-60000;start=end-DAYS*86400000+60000;blind=end-BLIND_DAYS*86400000+60000
    print("WINDOW",iso(start),iso(end),"BLIND_START",iso(blind),flush=True)
    jobs=[(p,a) for p in PRODUCTS for a in ASSETS];results=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        fs={pool.submit(fetch,j,start,end):j for j in jobs}
        for f in as_completed(fs):
            try:r=f.result();results.append(r);print("FETCH",r["product"],r["asset"],r["bars"],"/",r["expected"],"coverage",round(100*r["coverage"],2),"gaps",r["gaps"],"calls",r["calls"],flush=True)
            except Exception as e:results.append({"product":fs[f][0],"asset":fs[f][1],"error":str(e),"bars":0,"coverage":0});print("FETCH_ERROR",fs[f],str(e),flush=True)
    good=[r for r in results if r.get("coverage",0)>=.95 and r.get("bars",0)>=DAYS*1440*.95]
    manifest={"source":"CoinDCX public REST 1m candles","start_utc":iso(start),"end_utc":iso(end),"blind_start_utc":iso(blind),"series_requested":len(jobs),"series_usable":len(good),"series":results,"limitations":["Historical bid/ask/depth unavailable; assumes 8 bps full spread.","Current liquid asset list creates survivorship bias.","1m OHLC cannot establish intraminute path; stop assumed first if both barriers touch.","No futures funding cost; no leverage or live orders."]}
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2))
    if len(good)<16:
        (OUT/"REPORT.md").write_text("# Blind test inconclusive\nInsufficient API coverage: fewer than 16 of 20 series reached 95%. No strategy selected; no production changes.")
        print("INCONCLUSIVE: insufficient candle coverage",flush=True);return 2
    trades=[]
    for r in good:
        rows=read(r["path"])
        for v,cfg in VARIANTS.items():
            trades+=replay(rows,r["product"],cfg,start,blind-60000,v,r["asset"])
            trades+=replay(rows,r["product"],cfg,blind,end,v,r["asset"])
    train={v:metric([t for t in trades if t["variant"]==v and t["entry_time"]<blind]) for v in VARIANTS}
    blindm={v:metric([t for t in trades if t["variant"]==v and t["entry_time"]>=blind]) for v in VARIANTS}
    # Select on train only. Minimum samples and PF threshold guard against tiny PF spikes.
    candidates=[v for v in VARIANTS if v!="current_proxy" and train[v]["trades"]>=50 and train[v]["pf"] is not None and train[v]["pf"]>1.25 and train[v]["net_usdt"]>0]
    selected=max(candidates,key=lambda v:(train[v]["pf"],train[v]["net_usdt"])) if candidates else None
    passed=bool(selected and blindm[selected]["trades"]>=30 and blindm[selected]["pf"] is not None and blindm[selected]["pf"]>1.25 and blindm[selected]["net_usdt"]>0)
    # Stress every blind trade by +8 bps spread and +5 bps/side slippage.
    stress={}
    for v in VARIANTS:
        sub=[]
        for t in [x for x in trades if x["variant"]==v and x["entry_time"]>=blind]:
            fee,slip,spread=costs(t["product"]);g=t["gross_move_pct"];n=g-fee-(slip+.10)-(spread+.08)
            if g>0:n-=(g if t["product"]=="spot" else max(0,g-fee-(slip+.10)))*TAX/100
            sub.append({**t,"net_usdt":NOTIONAL*n/100})
        stress[v]=metric(sub)
    with open(OUT/"trades.csv","w",newline="") as f:
        cols=["variant","product","asset","side","entry_time","exit_time","gross_move_pct","net_pct","net_usdt","reason","r5","prev5","continuation","estimated_net","turnover_proxy"]
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(sorted(trades,key=lambda x:(x["entry_time"],x["variant"],x["product"],x["asset"])))
    lines=["# CoinDCX scalper — 30-day public API blind test","",f"- 1m data window: {iso(start)} to {iso(end)} UTC.",f"- Training: first {DAYS-BLIND_DAYS} days; blind: final {BLIND_DAYS} days from {iso(blind)}.",f"- Coverage: {len(good)}/{len(jobs)} series passed 95%; {sum(r['bars'] for r in good):,} candles in usable series.","- Replays current signal formula plus three predeclared variants; entry is next-minute open; assumed full spread 8 bps, configured fees + 18% GST, 5 bps/side slippage, 31.2% tax reserve, +0.15% net target, -0.40% net stop, 15-minute max hold, 5-minute cooldown.","- Stop-first assumption when both barriers touch in one minute; no funding; no leverage.","- Limitations: public candles do not provide historical orderbook/depth, fixed spread is a proxy, current liquid universe has survivorship bias, and one-minute bars cannot prove executable intraminute fills.","","## Training results (selection only)","","| Variant | Trades | Win % | PF | Net USDT | Max DD USDT |","|---|---:|---:|---:|---:|---:|"]
    for v,m in train.items():lines.append(f"| {v} | {m['trades']} | {m['win_rate_pct']} | {m['pf']} | {m['net_usdt']} | {m['max_dd_usdt']} |")
    lines+=["","## Blind results (not used for selection)","","| Variant | Trades | Win % | PF | Net USDT | Max DD USDT | Stress PF | Stress net USDT |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for v,m in blindm.items():lines.append(f"| {v} | {m['trades']} | {m['win_rate_pct']} | {m['pf']} | {m['net_usdt']} | {m['max_dd_usdt']} | {stress[v]['pf']} | {stress[v]['net_usdt']} |")
    lines+=["","## Decision","",f"- Variant selected using training only: {selected or 'none'}.",f"- Blind acceptance: {'PASS' if passed else 'FAIL'}; requires at least 30 blind trades, PF > 1.25 and positive net. Stress results require separate review.","- A failed/inconclusive result does not justify loosening live gates. No strategy config or production database was modified.","","## API coverage","","| Product | Asset | Bars | Expected | Coverage % | Gaps | Calls |","|---|---|---:|---:|---:|---:|---:|"]
    for r in sorted(results,key=lambda x:(x["product"],x["asset"])):lines.append(f"| {r['product']} | {r['asset']} | {r.get('bars',0)} | {r.get('expected',0)} | {100*r.get('coverage',0):.2f} | {r.get('gaps','—')} | {r.get('calls','—')} |")
    (OUT/"REPORT.md").write_text("\n".join(lines)+"\n")
    (OUT/"summary.json").write_text(json.dumps({"manifest":manifest,"train":train,"blind":blindm,"stress_blind":stress,"selected":selected,"blind_pass":passed,"variants":VARIANTS},indent=2))
    print((OUT/"REPORT.md").read_text(),flush=True)
    return 0 if passed else 1
if __name__=="__main__":sys.exit(main())

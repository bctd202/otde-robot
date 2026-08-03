from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import LiveWaitCandidate, ParlayPaperPosition, SignalPerformance

STRATEGY_VERSION="parlay-v1"
STRATEGY_SNAPSHOT={"engine":"app.services.parlay.rank_parlays","structure":"15m","confirmation":"5m","paper_only":True}

def _utc(value: datetime)->datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

def track_candidates(db:Session,candidates:list)->None:
    now=datetime.now(timezone.utc)
    for c in candidates:
        if c.signal_status not in {"WATCH","BUY","MISSED"} or c.direction not in {"call","put"}: continue
        stamp=_utc(c.generated_at); day=stamp.date(); wait_key=f"{c.symbol}:{c.direction}:{day.isoformat()}"
        existing=db.scalar(select(SignalPerformance).where(SignalPerformance.source=="LIVE",SignalPerformance.dedupe_key==wait_key))
        waiting=db.get(LiveWaitCandidate,wait_key)
        if existing is None and c.signal_status=="WATCH":
            if waiting is None:
                db.add(LiveWaitCandidate(key=wait_key,ticker=c.symbol,direction=c.direction.upper(),first_seen_at=stamp,
                    condition_snapshot={"reasons":c.reasons,"score":c.score,"setup_type":"directional-liquidity"}))
            continue
        if existing is None and c.signal_status in {"BUY","MISSED"}:
            contract=c.contract.model_dump(mode="json") if c.contract else None
            existing=SignalPerformance(signal_id=str(uuid4()),source="LIVE",dedupe_key=wait_key,ticker=c.symbol,
                direction=c.direction.upper(),backend_status=c.signal_status,setup_type="directional-liquidity",
                strategy_version=STRATEGY_VERSION,strategy_snapshot=STRATEGY_SNAPSHOT,condition_snapshot={"reasons":c.reasons,"rejections":c.rejection_reasons},
                trading_date=day,first_wait_at=waiting.first_seen_at if waiting else None,triggered_at=stamp,entry_price=c.underlying_trigger or c.underlying_price,
                stop_price=c.underlying_invalidation,target_price=c.first_underlying_target,exit_reason="MISSED" if c.signal_status=="MISSED" else "OPEN",
                result_r=None,mfe_r=0,mae_r=0,score=c.score,user_entered=False,option_snapshot=contract,created_at=now,updated_at=now)
            db.add(existing)
        elif existing and existing.exit_reason=="OPEN":
            update_outcome(existing,c.underlying_price,c.underlying_price,stamp)
    db.commit()

def update_outcome(row:SignalPerformance,high:float,low:float,stamp:datetime,cutoff=False)->None:
    risk=abs(row.entry_price-row.stop_price)
    if not risk:return
    favorable=(high-row.entry_price)/risk if row.direction=="CALL" else (row.entry_price-low)/risk
    adverse=(row.entry_price-low)/risk if row.direction=="CALL" else (high-row.entry_price)/risk
    row.mfe_r=round(max(row.mfe_r,favorable),4); row.mae_r=round(max(row.mae_r,adverse),4); row.updated_at=_utc(stamp)
    target_hit=high>=row.target_price if row.direction=="CALL" else low<=row.target_price
    stop_hit=low<=row.stop_price if row.direction=="CALL" else high>=row.stop_price
    if target_hit and stop_hit: reason,price="STOP",row.stop_price; row.conservative_same_candle=True
    elif stop_hit: reason,price="STOP",row.stop_price
    elif target_hit: reason,price="TARGET",row.target_price
    elif cutoff: reason,price="TIMED_EXIT",(high+low)/2
    else:return
    row.exit_reason=reason;row.exit_price=price;row.exit_at=_utc(stamp)
    signed=(price-row.entry_price) if row.direction=="CALL" else (row.entry_price-price)
    row.result_r=round(signed/risk,4);row.duration_minutes=max(0,int((row.exit_at-_utc(row.triggered_at)).total_seconds()/60))

def link_paper_position(db:Session,position:ParlayPaperPosition)->None:
    row=db.scalar(select(SignalPerformance).where(SignalPerformance.source=="LIVE",SignalPerformance.ticker==position.symbol,SignalPerformance.exit_reason=="OPEN").order_by(SignalPerformance.triggered_at.desc()))
    if row: row.user_entered=True;row.paper_position_id=position.id;row.updated_at=datetime.now(timezone.utc);db.commit()

def metrics(rows:list[SignalPerformance])->dict:
    completed=[r for r in rows if r.exit_reason!="OPEN" and r.result_r is not None]
    values=[float(r.result_r) for r in completed if r.result_r is not None]; wins=[v for v in values if v>0]; losses=[v for v in values if v<0]
    equity=peak=drawdown=0.0
    for value in values: equity+=value;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return {"total_triggered_signals":len(rows),"open_signals":sum(r.exit_reason=="OPEN" for r in rows),"targets_hit":sum(r.exit_reason=="TARGET" for r in rows),"stops_hit":sum(r.exit_reason=="STOP" for r in rows),"timed_exits":sum(r.exit_reason=="TIMED_EXIT" for r in rows),"invalidated_missed":sum(r.exit_reason in {"INVALIDATED","MISSED"} for r in rows),"win_rate":round(100*len(wins)/len(completed),1) if completed else 0,"average_r":round(sum(values)/len(values),3) if values else 0,"cumulative_r":round(sum(values),3),"profit_factor":round(sum(wins)/abs(sum(losses)),2) if losses else None,"maximum_drawdown_r":round(drawdown,3),"average_duration":round(sum(r.duration_minutes or 0 for r in completed)/len(completed),1) if completed else 0,"average_mfe":round(sum(r.mfe_r for r in completed)/len(completed),3) if completed else 0,"average_mae":round(sum(r.mae_r for r in completed)/len(completed),3) if completed else 0}

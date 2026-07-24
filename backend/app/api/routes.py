from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import Signal, TradeOutcome
from app.db.session import get_db
from app.market_data.factory import get_provider
from app.schemas.market import DashboardOut
from app.services.market_calendar import market_session
from app.services.setup_engine import levels_for, lottery_candidates, structured_setups

router = APIRouter()

@router.get("/health")
def health(): return {"status":"ok","paper_only": True}

@router.get("/dashboard", response_model=DashboardOut)
def dashboard():
    settings=get_settings(); provider=get_provider(); symbols=settings.symbol_list
    status=provider.status(); quotes=provider.quotes(symbols)
    levels={}; bias={}; setups=[]; lottos=[]
    for q in quotes:
        candles=provider.candles(q.symbol,"1m"); chain=provider.option_chain(q.symbol)
        levels[q.symbol]=levels_for(candles)
        bias[q.symbol]="bullish" if candles[-1].close > levels[q.symbol]["vwap"] else "neutral"
        setups += structured_setups(q.symbol,candles,q,chain)
        lottos += lottery_candidates(q.symbol,candles,q,chain)
    return DashboardOut(provider_status=status, quotes=quotes, market_session=market_session(status.latest_timestamp), volatility_proxy=14.2, levels=levels, directional_bias=bias, news_warning="Economic calendar adapter unavailable in Phase 1; no events fabricated.", normal_setups=setups, lottery_setups=sorted(lottos, key=lambda x: x.setup_score, reverse=True)[:3], no_trade=(not setups and not lottos), paper_account={"mode":"PAPER ONLY", "equity": settings.paper_account_size, "kill_switch": False, "structured_risk_percent": settings.structured_risk_percent, "lottery_daily_limit": 40})

@router.get("/candles/{symbol}")
def candles(symbol: str, timeframe: str="1m"):
    settings = get_settings()
    symbol = symbol.upper()
    if symbol not in settings.symbol_list:
        raise HTTPException(status_code=404, detail="Symbol is not configured")
    if timeframe not in {"1m", "5m"}:
        raise HTTPException(status_code=422, detail="Timeframe must be 1m or 5m")
    return get_provider().candles(symbol, timeframe)

@router.get("/journal")
def journal(db: Session = Depends(get_db)):
    signals = db.scalars(select(Signal).order_by(Signal.generated_at.desc())).all()
    return [{"id": signal.id, "symbol": signal.symbol, "signal_type": signal.signal_type,
             "status": signal.status, "generated_at": signal.generated_at,
             "payload": signal.payload} for signal in signals]

@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    outcomes = db.scalars(select(TradeOutcome)).all()
    returns = [float(row.payload.get("return_pct", 0)) for row in outcomes]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    sample_size = len(returns)
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    return {
        "minimum_sample_size": 30,
        "sample_size": sample_size,
        "statistically_promising": sample_size >= 30,
        "win_rate": round(len(winners) / sample_size * 100, 1) if sample_size else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "average_winner": round(gross_profit / len(winners), 1) if winners else 0,
        "average_loser": round(sum(losers) / len(losers), 1) if losers else 0,
        "expectancy": round(sum(returns) / sample_size, 1) if sample_size else 0,
        "message": "Seeded paper results are illustrative, not statistically promising."
    }

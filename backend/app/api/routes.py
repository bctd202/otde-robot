from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import ParlayPaperPosition, Signal, TradeOutcome
from app.db.session import get_db
from app.market_data.factory import get_provider
from app.schemas.market import DashboardOut, ParlayResponse, ScannerHealth
from app.schemas.paper_positions import (PaperPositionCreate, PaperPositionExit,
                                         PaperPositionOut, PaperPositionsResponse)
from app.services.market_calendar import market_session
from app.services.setup_engine import levels_for, lottery_candidates, structured_setups
from app.services.parlay import rank_parlays
from app.services.paper_positions import (create_position, market_mark,
                                          expire_if_past_expiration,
                                          refresh_position, serialize)

router = APIRouter()


@router.post("/paper-positions", response_model=PaperPositionOut, status_code=201)
def paper_position_create(payload: PaperPositionCreate, db: Session = Depends(get_db)):
    try:
        position = create_position(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already exists" in str(exc) else 422, detail=str(exc)) from exc
    return serialize(position, option_price=position.entry_option_price,
                     underlying_price=position.entry_underlying_price,
                     freshness="entry_snapshot")


@router.get("/paper-positions", response_model=PaperPositionsResponse)
def paper_positions(db: Session = Depends(get_db)):
    rows = db.scalars(select(ParlayPaperPosition).order_by(ParlayPaperPosition.opened_at.desc()).limit(50)).all()
    provider = get_provider()
    output = [refresh_position(db, row, provider) if row.lifecycle_status == "ACTIVE" else
              serialize(row, option_price=row.last_option_price, underlying_price=row.last_underlying_price)
              for row in rows]
    return PaperPositionsResponse(positions=output)


@router.post("/paper-positions/{position_id}/exit", response_model=PaperPositionOut)
def paper_position_exit(position_id: int, payload: PaperPositionExit, db: Session = Depends(get_db)):
    position = db.get(ParlayPaperPosition, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Paper position not found")
    if expire_if_past_expiration(db, position):
        raise HTTPException(status_code=409, detail="Expired paper positions cannot be exited")
    if position.lifecycle_status == "CLOSED":
        raise HTTPException(status_code=409, detail="Paper position is already closed")
    option_price, underlying_price, freshness = market_mark(position, get_provider())
    if option_price is None:
        raise HTTPException(status_code=409, detail="No current defensible paper exit price is available")
    position.exit_option_price = option_price
    position.exit_underlying_price = underlying_price
    position.exit_reason = payload.reason
    position.closed_at = datetime.now(timezone.utc)
    position.lifecycle_status = "CLOSED"
    position.data_freshness = freshness
    db.commit()
    db.refresh(position)
    return serialize(position)

@router.get("/parlays", response_model=ParlayResponse)
def parlays():
    settings = get_settings()
    provider = get_provider()
    universe = settings.parlay_symbol_list
    candidates = rank_parlays(provider, universe)
    return ParlayResponse(
        provider_status=provider.status(),
        universe=universe,
        candidates=candidates,
        scanner_health=ScannerHealth(
            candidate_count=len(candidates),
            unavailable_candidate_count=sum(candidate.signal_status == "UNAVAILABLE" for candidate in candidates),
            provider_status=provider.status().status,
        ),
    )

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

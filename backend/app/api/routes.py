from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import (BacktestRun, DailyWatchSymbol, ParlayPaperPosition,
                           ScannerRuntime, Signal, SignalAlert,
                           SignalPerformance, TradeOutcome)
from app.db.session import get_db
from app.market_data.factory import get_provider
from app.schemas.market import (DashboardOut, DailyWatchCreate,
                                DailyWatchResponse, ParlayResponse,
                                ScannerHealth, SignalAlertOut,
                                SignalAlertsResponse)
from app.schemas.paper_positions import (PaperPositionCreate, PaperPositionExit,
                                         PaperPositionOut, PaperPositionsResponse)
from app.services.market_calendar import market_session
from app.services.setup_engine import levels_for, lottery_candidates, structured_setups
from app.services.paper_positions import (create_position, market_mark,
                                          cached_position,
                                          expire_if_past_expiration,
                                          refresh_position, serialize)
from app.services.backtest import run_backtest
from app.services.performance import link_paper_position, metrics
from app.services.signal_engine import (ENGINE_KEY, cached_candidates,
                                        latest_scan, mark_lifecycle_entered,
                                        run_signal_scan)

router = APIRouter()

def _trading_date() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()

def _daily_watch_symbols(db: Session) -> list[str]:
    return list(db.scalars(select(DailyWatchSymbol.symbol).where(
        DailyWatchSymbol.trading_date == _trading_date()).order_by(DailyWatchSymbol.id)).all())

@router.get("/daily-watch", response_model=DailyWatchResponse)
def daily_watch(db: Session = Depends(get_db)):
    symbols = _daily_watch_symbols(db)
    limit = get_settings().parlay_flex_limit
    return DailyWatchResponse(trading_date=_trading_date(), symbols=symbols,
                              slots_used=len(symbols), slot_limit=limit)

@router.post("/daily-watch", response_model=DailyWatchResponse, status_code=201)
def daily_watch_add(payload: DailyWatchCreate, db: Session = Depends(get_db)):
    symbol = payload.symbol.strip().upper()
    settings = get_settings()
    if not symbol or len(symbol) > 12 or not symbol.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Enter a valid ticker symbol")
    symbols = _daily_watch_symbols(db)
    if symbol in settings.parlay_symbol_list:
        raise HTTPException(status_code=409, detail=f"{symbol} is already in the permanent universe")
    if symbol not in symbols:
        if len(symbols) >= settings.parlay_flex_limit:
            raise HTTPException(status_code=409, detail="Both Watch Today slots are already in use")
        provider = get_provider()
        try:
            if not provider.quotes([symbol]):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{symbol} was not recognized by the market-data provider")
        db.add(DailyWatchSymbol(trading_date=_trading_date(), symbol=symbol,
                                created_at=datetime.now(timezone.utc)))
        db.commit()
        symbols = _daily_watch_symbols(db)
    return DailyWatchResponse(trading_date=_trading_date(), symbols=symbols,
                              slots_used=len(symbols), slot_limit=settings.parlay_flex_limit)

@router.delete("/daily-watch/{symbol}", response_model=DailyWatchResponse)
def daily_watch_remove(symbol: str, db: Session = Depends(get_db)):
    row = db.scalar(select(DailyWatchSymbol).where(
        DailyWatchSymbol.trading_date == _trading_date(), DailyWatchSymbol.symbol == symbol.upper()))
    if row is not None:
        db.delete(row); db.commit()
    symbols = _daily_watch_symbols(db); limit = get_settings().parlay_flex_limit
    return DailyWatchResponse(trading_date=_trading_date(), symbols=symbols,
                              slots_used=len(symbols), slot_limit=limit)


@router.post("/paper-positions", response_model=PaperPositionOut, status_code=201)
def paper_position_create(payload: PaperPositionCreate, db: Session = Depends(get_db)):
    try:
        position = create_position(db, payload, get_provider())
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already exists" in str(exc) else 422, detail=str(exc)) from exc
    link_paper_position(db, position)
    mark_lifecycle_entered(db, position)
    return serialize(position, option_price=position.entry_option_price,
                     underlying_price=position.entry_underlying_price,
                     freshness="entry_snapshot")


@router.get("/paper-positions", response_model=PaperPositionsResponse)
def paper_positions(refresh: bool = False, db: Session = Depends(get_db)):
    rows = db.scalars(select(ParlayPaperPosition).order_by(ParlayPaperPosition.opened_at.desc()).limit(50)).all()
    provider = get_provider() if refresh else None
    output = []
    for row in rows:
        expire_if_past_expiration(db, row)
        output.append(refresh_position(db, row, provider) if provider is not None and row.lifecycle_status == "ACTIVE"
                      else cached_position(row))
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
def parlays(db: Session = Depends(get_db)):
    settings = get_settings()
    provider = get_provider()
    universe = list(dict.fromkeys(settings.parlay_symbol_list + _daily_watch_symbols(db)))
    scan = latest_scan(db)
    if scan is None or scan.universe != universe:
        scan = run_signal_scan(db, provider, universe, force=True)
    candidates = cached_candidates(scan, db) if scan is not None else []
    runtime = db.get(ScannerRuntime, ENGINE_KEY)
    status = provider.status()
    return ParlayResponse(
        provider_status=status,
        universe=universe,
        candidates=candidates,
        scanner_health=ScannerHealth(
            candidate_count=len(candidates),
            unavailable_candidate_count=sum(candidate.signal_status == "UNAVAILABLE" for candidate in candidates),
            provider_status=status.status,
            engine_status=runtime.status if runtime else "starting",
            last_completed_scan_at=runtime.last_scan_completed_at if runtime else None,
            evaluation_candle_at=runtime.last_evaluation_candle_at if runtime else None,
            next_evaluation_at=runtime.next_evaluation_at if runtime else None,
            last_error=runtime.last_error if runtime else None,
            api_budget=provider.budget_status() if hasattr(provider, "budget_status") else {},
        ),
    )


@router.get("/signal-alerts", response_model=SignalAlertsResponse)
def signal_alerts(after_id: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    bounded_limit = max(1, min(limit, 200))
    rows = list(db.scalars(select(SignalAlert).where(SignalAlert.id > max(0, after_id))
        .order_by(SignalAlert.id.desc()).limit(bounded_limit)).all())
    alerts = [SignalAlertOut.model_validate({column.name: getattr(row, column.name)
        for column in row.__table__.columns}) for row in reversed(rows)]
    return SignalAlertsResponse(alerts=alerts, latest_id=max((row.id for row in rows), default=after_id))


def _ledger(row: SignalPerformance) -> dict:
    payload = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    risk = abs(row.entry_price - row.stop_price)
    risk_pct = risk / row.entry_price * 100 if row.entry_price else 0
    if payload.get("result_return_pct") is None and row.exit_price is not None and row.entry_price:
        signed = row.exit_price - row.entry_price if row.direction == "CALL" else row.entry_price - row.exit_price
        payload["result_return_pct"] = round(signed / row.entry_price * 100, 4)
    payload["initial_risk_points"] = round(risk, 4)
    payload["initial_risk_pct"] = round(risk_pct, 4)
    payload["mfe_return_pct"] = round(row.mfe_r * risk_pct, 4)
    payload["mae_return_pct"] = round(row.mae_r * risk_pct, 4)
    return payload


@router.get("/performance")
def performance(source: str | None = None, ticker: str | None = None, direction: str | None = None,
                setup_type: str | None = None, strategy_mode: str | None = None,
                exit_reason: str | None = None, user_entered: bool | None = None,
                start: date | None = None, end: date | None = None, min_score: float | None = None,
                max_score: float | None = None, db: Session = Depends(get_db)):
    query = select(SignalPerformance).order_by(SignalPerformance.triggered_at.desc())
    for condition in (SignalPerformance.source == source if source else None,
        SignalPerformance.ticker == ticker.upper() if ticker else None,
        SignalPerformance.direction == direction.upper() if direction else None,
        SignalPerformance.setup_type == setup_type if setup_type else None,
        SignalPerformance.strategy_mode == strategy_mode if strategy_mode else None,
        SignalPerformance.exit_reason == exit_reason if exit_reason else None,
        SignalPerformance.user_entered == user_entered if user_entered is not None else None,
        SignalPerformance.trading_date >= start if start else None, SignalPerformance.trading_date <= end if end else None,
        SignalPerformance.score >= min_score if min_score is not None else None,
        SignalPerformance.score <= max_score if max_score is not None else None):
        if condition is not None: query = query.where(condition)
    rows = list(db.scalars(query).all())
    return {"metrics": metrics(rows), "signals": [_ledger(row) for row in rows], "timezone": "America/New_York",
        "underlying_only": True, "paper_only": True}


@router.get("/backtests")
def backtests(db: Session = Depends(get_db)):
    runs = db.scalars(select(BacktestRun).order_by(BacktestRun.started_at.desc()).limit(30)).all()
    return [{column.name: getattr(run, column.name) for column in run.__table__.columns} for run in runs]


@router.post("/backtests", status_code=201)
def backtest_create(payload: dict, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        start, end = date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"])
        tickers = [str(value).upper() for value in payload.get("tickers", settings.parlay_symbol_list)
                   if str(value).upper() in settings.parlay_symbol_list]
        if not tickers or start > end: raise ValueError("Invalid date range or ticker selection")
        run = run_backtest(db, get_provider(), start, end, tickers)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409 if "already running" in str(exc) else 422, detail=str(exc)) from exc
    return {column.name: getattr(run, column.name) for column in run.__table__.columns}

@router.get("/health")
def health(): return {"status":"ok","paper_only": True}

@router.get("/dashboard", response_model=DashboardOut)
def dashboard():
    settings=get_settings(); provider=get_provider(); symbols=settings.symbol_list
    status=provider.status(); quotes=provider.quotes(symbols)
    levels={}; bias={}; setups=[]; lottos=[]
    for q in quotes:
        try: candles=provider.candles(q.symbol,"1m")
        except (KeyError, TypeError, ValueError): candles=[]
        if len(candles) < 12: continue
        try:
            from app.services.contracts import annotate_chain
            raw_chain=provider.option_chain(q.symbol)
            chain=annotate_chain(raw_chain,q.symbol,provider.status().latest_timestamp)
        except (KeyError, TypeError, ValueError): chain=[]
        levels[q.symbol]=levels_for(candles)
        bias[q.symbol]="bullish" if candles[-1].close > levels[q.symbol]["vwap"] else "neutral"
        setups += structured_setups(q.symbol,candles,q,chain,status)
        lottos += lottery_candidates(q.symbol,candles,q,chain,status)
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

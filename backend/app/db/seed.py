"""Seed a repeatable mock trading day for the local Phase 1 demo."""
from datetime import date, timedelta

from sqlalchemy import delete

from app.db.models import (
    Candle, LiquidityLevel, MarketSnapshot, OptionContract, OptionQuote, Setup,
    Signal, TradeOutcome, TradingDay,
)
from app.db.session import SessionLocal
from app.market_data.mock import MockMarketDataProvider
from app.services.setup_engine import levels_for, lottery_candidates, structured_setups


def seed() -> None:
    provider = MockMarketDataProvider()
    with SessionLocal() as db:
        for model in (TradeOutcome, Signal, Setup, LiquidityLevel, OptionQuote,
                      OptionContract, Candle, MarketSnapshot, TradingDay):
            db.execute(delete(model))
        db.add(TradingDay(date=date.today(), session="regular"))

        for quote in provider.quotes(["SPY", "QQQ", "IWM"]):
            db.add(MarketSnapshot(symbol=quote.symbol, price=quote.price, provider="mock",
                                  status="healthy", timestamp=quote.timestamp))
            candles = provider.candles(quote.symbol)
            for candle in candles:
                db.add(Candle(**candle.model_dump()))
            levels = levels_for(candles)
            for level_type, price in levels.items():
                if isinstance(price, (int, float)):
                    db.add(LiquidityLevel(symbol=quote.symbol, level_type=level_type,
                                          price=price, timestamp=quote.timestamp))

            chain = provider.option_chain(quote.symbol)
            for item in chain:
                contract = OptionContract(symbol=item.symbol, option_symbol=item.option_symbol,
                                          expiration=item.expiration, strike=item.strike, right=item.right)
                db.add(contract)
                db.flush()
                db.add(OptionQuote(contract_id=contract.id, bid=item.bid, ask=item.ask,
                                   last=item.last, volume=item.volume,
                                   open_interest=item.open_interest, iv=item.iv,
                                   delta=item.delta, gamma=item.gamma, theta=item.theta,
                                   vega=item.vega, timestamp=item.timestamp))

            generated = structured_setups(quote.symbol, candles, quote, chain)
            lottos = lottery_candidates(quote.symbol, candles, quote, chain)
            for item in generated:
                setup = Setup(symbol=item.symbol, setup_type=item.setup_type, name=item.name,
                              direction=item.direction, grade=item.grade, score=item.score,
                              entry_trigger=item.entry_trigger, invalidation=item.invalidation,
                              target1=item.target1, target2=item.target2,
                              reward_risk=item.reward_risk, status="generated",
                              generated_at=item.generated_at, expires_at=item.expires_at,
                              details={"confluences": item.confluences})
                db.add(setup)
                db.flush()
                db.add(Signal(setup_id=setup.id, symbol=item.symbol,
                              signal_type="structured", status="paper_taken",
                              generated_at=item.generated_at,
                              payload={"entry": item.entry_trigger, "grade": item.grade}))
            if lottos:
                lotto = lottos[0]
                db.add(Signal(symbol=quote.symbol, signal_type="lottery",
                              status="not_taken", generated_at=quote.timestamp,
                              payload={"strike": lotto.strike, "right": lotto.right,
                                       "score": lotto.setup_score, "maximum_loss": lotto.total_debit}))

        no_trade = Signal(symbol="ALL", signal_type="no_trade", status="recorded",
                          generated_at=provider.now - timedelta(days=1),
                          payload={"reason": "No deterministic filters qualified"})
        db.add(no_trade)
        db.flush()
        seeded_returns = [32.0, -18.0, 54.0, -20.0, 12.0, -100.0]
        signals = db.query(Signal).all()
        for index, value in enumerate(seeded_returns):
            signal = signals[index % len(signals)]
            db.add(TradeOutcome(signal_id=signal.id,
                                max_favorable_excursion=max(value, 0),
                                max_adverse_excursion=min(value, 0),
                                max_return_multiple=max(0, 1 + value / 100),
                                payload={"return_pct": value, "source": "seeded_paper_demo"}))
        db.commit()
        print(f"Seeded mock day with {len(signals)} signals and {len(seeded_returns)} outcomes.")


if __name__ == "__main__":
    seed()

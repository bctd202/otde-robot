from datetime import timedelta
from app.core.config import get_settings
from app.schemas.market import LotteryOut, SetupOut
from app.services.indicators import equal_levels, opening_range, spread_pct, swings, vwap


def levels_for(candles):
    or5 = opening_range(candles, 5)
    highs, lows = swings(candles)
    return {"previous_day_high": max(c.high for c in candles)+0.8, "previous_day_low": min(c.low for c in candles)-0.8, "opening_range_high": or5["high"], "opening_range_low": or5["low"], "session_high": max(c.high for c in candles), "session_low": min(c.low for c in candles), "vwap": vwap(candles), "equal_highs": equal_levels(highs), "equal_lows": equal_levels(lows)}

def structured_setups(symbol, candles, quote, chain):
    if len(candles) < 12: return []
    lv = levels_for(candles); last=candles[-1]; prev=candles[-2]
    setups=[]
    swept = prev.high > lv["opening_range_high"] and last.close > lv["opening_range_high"] and last.close > lv["vwap"]
    if swept:
        risk=max(last.close-lv["opening_range_high"], 0.1); target=last.close+risk*2.4
        contract=next((c for c in chain if c.right=="call" and c.delta and 0.25 >= c.delta >= 0.05), None)
        setups.append(SetupOut(symbol=symbol, setup_type="structured", name="Opening-range breakout retest", direction="call", grade="B+", score=78, entry_trigger=round(last.close+0.05,2), current_underlying_price=quote.price, invalidation=round(lv["opening_range_high"]-0.05,2), target1=round(last.close+risk*2,2), target2=round(target,2), reward_risk=round((target-last.close)/risk,2), contract=contract, confluences=["VWAP alignment", "Opening range reclaimed", "Range expansion"], avoid_reasons=[], generated_at=quote.timestamp, expires_at=quote.timestamp+timedelta(minutes=45), data_freshness="fresh_mock"))
    return [s for s in setups if s.reward_risk >= get_settings().structured_min_rr]

def lottery_candidates(symbol, candles, quote, chain):
    s=get_settings(); lv=levels_for(candles); last=candles[-1]
    bullish = last.close > lv["vwap"] and last.close >= lv["opening_range_high"]
    out=[]
    for c in chain:
        sp=spread_pct(c.bid,c.ask); abs_delta=abs(c.delta or 0); debit=c.ask*100
        trigger_ok = bullish and c.right=="call"
        if not trigger_ok or not (s.lottery_min_ask <= c.ask <= s.lottery_max_ask and debit <= s.lottery_max_debit and c.volume >= s.lottery_min_volume and c.open_interest >= s.lottery_min_open_interest and sp <= s.lottery_max_spread_pct and s.lottery_min_delta <= abs_delta <= s.lottery_max_delta and c.bid > 0):
            continue
        mid=round((c.bid+c.ask)/2,2); otm=max((c.strike-quote.price)/quote.price*100,0) if c.right=="call" else max((quote.price-c.strike)/quote.price*100,0)
        score=min(100, 40 + c.volume/50 + c.open_interest/200 + (c.gamma or 0)*300 - sp/2)
        out.append(LotteryOut(symbol=symbol,right=c.right,strike=c.strike,expiration=c.expiration,bid=c.bid,ask=c.ask,midpoint=mid,last=c.last,total_debit=debit,otm_percent=round(otm,2),delta=c.delta,gamma=c.gamma,theta=c.theta,iv=c.iv,volume=c.volume,open_interest=c.open_interest,spread_percent=sp,underlying_trigger=round(max(lv["session_high"], c.strike-0.8),2),underlying_invalidation=round(lv["vwap"]-0.2,2),break_even=round(c.strike+c.ask,2),estimated_2x_underlying=round(c.strike+c.ask*2,2),estimated_5x_underlying=round(c.strike+c.ask*5,2),estimated_10x_underlying=round(c.strike+c.ask*10,2),explanation="Modeled estimates use simple intrinsic-value thresholds and are not guarantees; 0DTE options can expire worthless.",catalyst="Confirmed momentum runner: above VWAP and opening-range high in mock data.",setup_score=round(score,1),max_allocation=20,time_remaining_minutes=355,worthless_reasons=["Underlying may fail to reach strike quickly", "Bid-ask spread and theta decay can erase premium", "Mock data is not tradable live data"]))
    return sorted(out, key=lambda x: x.setup_score, reverse=True)[:3]

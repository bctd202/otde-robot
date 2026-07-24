def vwap(candles):
    pv = sum(((c.high+c.low+c.close)/3)*c.volume for c in candles)
    vol = sum(c.volume for c in candles)
    return round(pv/vol, 4) if vol else 0

def opening_range(candles, minutes=5):
    rows = candles[:minutes]
    return {"high": max(c.high for c in rows), "low": min(c.low for c in rows)} if rows else {"high":0,"low":0}

def swings(candles, lookback=2):
    highs=[]; lows=[]
    for i in range(lookback, len(candles)-lookback):
        win = candles[i-lookback:i+lookback+1]
        if candles[i].high == max(c.high for c in win): highs.append((candles[i].timestamp, candles[i].high))
        if candles[i].low == min(c.low for c in win): lows.append((candles[i].timestamp, candles[i].low))
    return highs, lows

def equal_levels(levels, tolerance=0.05):
    found=[]
    for i, a in enumerate(levels):
        for b in levels[i+1:]:
            if abs(a[1]-b[1]) <= tolerance: found.append(round((a[1]+b[1])/2,2))
    return sorted(set(found))

def spread_pct(bid, ask):
    mid=(bid+ask)/2
    return round(((ask-bid)/mid)*100,2) if mid else 999

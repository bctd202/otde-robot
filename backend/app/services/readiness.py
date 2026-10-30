"""Read-only readiness, separate from API process liveness."""
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import ForwardPaperPosition, LottoTrialPosition, RetestRun, ScannerRuntime
from app.services import expanded_account, retest_trials
from app.services.evidence_health import collection_evidence, utc
from app.services.market_calendar import market_session, next_market_open, NY


def snapshot(db, provider, *, now=None):
    now=now or datetime.now(timezone.utc)
    settings=get_settings();session=market_session(now)
    runtime=db.get(ScannerRuntime,'parlay')
    evidence=collection_evidence(db,now,runtime)
    quality=provider.data_quality_status() if hasattr(provider,'data_quality_status') else {}
    problems=[]
    if not settings.paper_only:problems.append('Paper-only setting is disabled')
    if not settings.parlay_background_scanner_enabled:problems.append('Background scanner is disabled')
    if runtime and runtime.operator_hold:problems.append('Scanner held by operator')
    if evidence['status']=='STALE':problems.append('Scheduled evaluations are overdue')
    if evidence.get('input_observation_errors'):problems.append('Saved candle coverage diagnostics contain collection errors')
    if session=='regular' and evidence['status']!='WARMING_UP':
        if hasattr(provider,'status') and provider.status().status!='healthy':
            problems.append('Market data provider reports degraded or unavailable evidence')
        if quality.get('connected') is False:problems.append('Candle stream disconnected')
        if quality.get('stale_symbols'):problems.append('Required symbol candles are stale')
    unknown=db.scalar(select(func.count()).select_from(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key==expanded_account.KEY,ForwardPaperPosition.status=='UNPRICED')) or 0
    lotto_unknown=db.scalar(select(func.count()).select_from(LottoTrialPosition).where(
        LottoTrialPosition.account_key.like('lotto-v3%'),LottoTrialPosition.status=='UNPRICED')) or 0
    if unknown:problems.append(f'{unknown} main-account exits have unknown proceeds')
    if lotto_unknown:problems.append(f'{lotto_unknown} lotto exits have unknown proceeds')
    run=db.get(RetestRun,retest_trials.KEY)
    drift=bool(run and (run.policy['code_hash']!=retest_trials.code_hash()
                       or run.policy['configuration']!=retest_trials.configuration()))
    if drift:problems.append('Frozen retest study: source changed; new admissions blocked')
    day=now.astimezone(NY).date()
    latest=db.scalar(select(func.max(ScannerRuntime.last_scan_completed_at)))
    return {'as_of':now.isoformat(),'paper_only':settings.paper_only,
        'status':'ATTENTION' if problems else 'SLEEPING' if session!='regular' else 'COLLECTING',
        'market_session':session,'problems':problems,'main_unknown_exits':unknown,
        'lotto_unknown_exits':lotto_unknown,'retest_admissions_blocked':drift,
        'next_market_open_at':next_market_open(now).isoformat() if session!='regular' else None,
        'last_completed_scan_at':utc(latest).isoformat() if latest else None,
        'trading_date':day.isoformat(),'collection':evidence,'transport':quality,
        'basis':'Saved observations and current transport state; broker execution is not simulated by a health check.'}

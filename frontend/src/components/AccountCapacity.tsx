import type {ForwardAccount} from '../types';

export function AccountCapacity({account}:{account:ForwardAccount}){
  const open=account.positions.filter(p=>p.status==='OPEN').length;
  const unknown=account.positions.filter(p=>p.status==='UNPRICED').length;
  const held=open+unknown,limit=account.policy.max_positions;
  const free=Math.max(0,limit-held);
  const archived=account.status==='ARCHIVED';
  return <aside className="execution-warning" aria-label="Paper account capacity">
    <strong>{archived?'Archived account capacity':free===0?'New entries blocked: account full':'Paper account position slots'} · {held}/{limit} occupied</strong>
    <p>{open} open · {unknown} unresolved exits · {free} slots free.</p>
    {unknown>0&&<p>Unresolved exits still use cash and slots. We cannot release them or calculate their profit without valid exit evidence.</p>}
    <p>{archived?'This preserved account accepts no new entries.':'Free slots alone do not guarantee a fill: settled cash, fresh quotes and entry rules still apply.'} Pending entries do not reserve slots; sold positions awaiting settlement no longer use slots, but their proceeds are not yet available.</p>
    <p>Account capacity is not a cap on research records. <a href="#backtest-lab">Open Research</a> → Uncapped opportunities to review the separate breakout/retest observations, including skips and cancellations. Those observations are not funded-account returns.</p>
  </aside>;
}

import type { SignalAlert } from '../types';
import { formatEasternTime } from '../lib/dates';

export function SignalAlerts({alerts}:{alerts:SignalAlert[]}) {
  const notificationsAvailable=typeof Notification!=='undefined';
  const enable=async()=>{if(notificationsAvailable)await Notification.requestPermission()};
  return <section className="signal-alerts" aria-labelledby="signal-alerts-title">
    <header><div><p className="eyebrow">Server watched</p><h2 id="signal-alerts-title">Signal Alerts</h2></div>
      {notificationsAvailable&&Notification.permission!=='granted'&&<button type="button" onClick={()=>void enable()}>Enable browser alerts</button>}
      {notificationsAvailable&&Notification.permission==='granted'&&<span className="alerts-enabled">Browser alerts on</span>}
    </header>
    <p className="section-note">The server keeps scanning with this page closed. Browser pop-ups require this page to remain open; alert history does not.</p>
    {alerts.length===0?<p className="section-empty">No lifecycle changes recorded yet.</p>:<div className="alert-list">{[...alerts].reverse().slice(0,8).map(alert=><article key={alert.id} className={`alert-event alert-${alert.event_type.toLowerCase()}`}>
      <span>{alert.event_type.replaceAll('_',' ')}</span><strong>{alert.symbol}</strong><p>{alert.message}</p><time>{formatEasternTime(alert.created_at)}</time>
    </article>)}</div>}
  </section>;
}

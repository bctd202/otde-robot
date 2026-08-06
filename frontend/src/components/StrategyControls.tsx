import type { StrategyMode, StrategyView } from '../types';

const strategyLabels:Record<StrategyView,string>={ALL:'All plays',ONE_MIN_0DTE:'1-Min / 0DTE',STRUCTURED_INTRADAY:'Structured Intraday'};

export function StrategyControls({view,onViewChange,alerts,onAlertChange}:{view:StrategyView;onViewChange:(view:StrategyView)=>void;alerts:Record<StrategyMode,boolean>;onAlertChange:(mode:StrategyMode,enabled:boolean)=>void}) {
  return <section className="strategy-controls" aria-labelledby="strategy-controls-title">
    <div><p className="eyebrow">Today&apos;s research lanes</p><h2 id="strategy-controls-title">Play Selector</h2><p>Both engines keep scanning and recording. This only changes the board view and browser alerts.</p></div>
    <div className="strategy-control-groups">
      <fieldset><legend>Board view</legend><div className="segmented-control">{(['ALL','ONE_MIN_0DTE','STRUCTURED_INTRADAY'] as StrategyView[]).map(mode=><button type="button" className={view===mode?'active':''} aria-pressed={view===mode} key={mode} onClick={()=>onViewChange(mode)}>{strategyLabels[mode]}</button>)}</div></fieldset>
      <fieldset><legend>Browser alerts</legend><label><input type="checkbox" checked={alerts.ONE_MIN_0DTE} onChange={event=>onAlertChange('ONE_MIN_0DTE',event.target.checked)}/> 1-Min / 0DTE</label><label><input type="checkbox" checked={alerts.STRUCTURED_INTRADAY} onChange={event=>onAlertChange('STRUCTURED_INTRADAY',event.target.checked)}/> Structured Intraday</label></fieldset>
    </div>
  </section>;
}

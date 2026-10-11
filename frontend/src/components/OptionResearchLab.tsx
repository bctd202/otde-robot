import type {OptionPathResearch} from '../types';

const money=(value:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);

export function OptionResearchLab({data}:{data:OptionPathResearch}){
  const matched=data.scenarios.some(row=>row.matched_plays>0);
  const extent=Math.max(1,...data.scenarios.flatMap(row=>[Math.abs(row.baseline_net_dollars),Math.abs(row.alternative_net_dollars)]));
  return <section className="research-breakdown option-research-lab" aria-label="Forward option exit research">
    <header><div><span>FORWARD RESEARCH · FIXED EXPERIMENTS</span><h3>Would an earlier option exit help?</h3></div><strong>{data.observed_plays} plays observed</strong></header>
    <p>Each experiment keeps the strategy’s earlier exit or closes at the first fresh bid after 15, 30, or 60 minutes. These comparisons collect evidence while the existing strategy continues.</p>
    <div className="research-evidence-counts"><span>{data.quoted_observations} fresh quote observations</span><span>{data.gap_observations} missing / stale observations</span><span>{money(data.fixed_cost_per_contract)} assumed cost per contract</span></div>
    {matched?<svg viewBox="0 0 720 220" role="img" aria-label="Baseline versus maximum-hold option results">
      <line x1="390" x2="390" y1="10" y2="200" className="graph-zero"/>
      {data.scenarios.map((row,index)=><g key={row.maximum_hold_minutes}>
        <text x="10" y={35+index*64} className="graph-axis">{row.maximum_hold_minutes} min · {row.matched_plays} matched</text>
        {[row.baseline_net_dollars,row.alternative_net_dollars].map((value,series)=><rect key={series} x={value>=0?390:390+value/extent*190} y={20+index*64+series*22} width={Math.abs(value)/extent*190} height="15" rx="3" fill={series?'#2dd4bf':'#94a3b8'}><title>{`${series?'Maximum hold':'Baseline'}: ${money(value)}`}</title></rect>)}
      </g>)}
    </svg>:<div className="graph-empty"><span>Collecting a new forward sample</span><p>Historical option paths are not reconstructed. Comparisons appear when both exits have defensible quotes.</p></div>}
    <p className="research-legend">Gray: baseline · Teal: maximum hold · Dollar P/L on each rule’s matched sample</p>
    <div className="research-table-scroll"><table><thead><tr><th>Maximum hold</th><th>Matched</th><th>Incomplete</th><th>Baseline net</th><th>Alternative net</th><th>Difference</th></tr></thead><tbody>{data.scenarios.map(row=><tr key={row.maximum_hold_minutes}><td>{row.maximum_hold_minutes} minutes</td><td>{row.matched_plays}</td><td>{row.incomplete_plays}</td><td>{row.matched_plays?money(row.baseline_net_dollars):'—'}</td><td>{row.matched_plays?money(row.alternative_net_dollars):'—'}</td><td>{row.matched_plays?money(row.difference_dollars):'—'}</td></tr>)}</tbody></table></div>
    <p>{data.note}</p><small>Research cohort {data.definition.version} · {data.definition.code_fingerprint}. Quotes reuse the scanner cache; {data.additional_requests} additional provider requests.</small>
  </section>;
}

export function OneMinuteRules(){
  return <details className="research-breakdown strategy-explainer"><summary>How the one-minute plays are selected</summary>
    <ol><li><strong>Read completed one-minute candles.</strong> At least eight are required. Compare price with VWAP, a five-minute opening range, and the previous seven candles.</li>
      <li><strong>Choose a direction.</strong> Six checks cover VWAP position, crossing VWAP, the opening range, the recent high/low, acceleration, and increasing volume. The winning direction needs at least three checks and a lead of two.</li>
      <li><strong>Require a confirmed breakout and a score of 85.</strong> Score combines the checks with option volume, open interest, and spread. The entry also has premium and price-extension limits.</li>
      <li><strong>Select a verified same-day option.</strong> Entry ask must be $0.20–$1.00, liquidity and quote checks must pass, and the strike must be reachable by the underlying target. Eligible contracts are ranked by volume plus half their open interest, then spread.</li>
      <li><strong>Follow the underlying stop and target.</strong> The trigger is the opening/recent range boundary; invalidation uses VWAP and the opening range. The first target uses 1.5 times the larger of the stop distance or 0.2% of the stock price. Remaining plays exit on the completed 3:45 PM ET candle. If stop and target occur in one candle, the stop wins.</li></ol>
    <p>“One-minute” is the signal timeframe, not a one-minute holding period. Recorded R divides by the actual saved entry-to-stop distance, so the target’s minimum-distance rule can create winners larger than 1.5R. Displayed option targets do not currently control automated underlying exits. The performance view selects the first automated BUY per ticker/day, then applies quality exclusions.</p>
  </details>;
}

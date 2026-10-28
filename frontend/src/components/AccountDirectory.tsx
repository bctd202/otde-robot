import './account-directory.css';

const groups=[
  {title:'Trading accounts',parameter:'paper_account',page:'performance',items:[
    {key:'tasty-capacity-ten-v1',label:'Main · ten positions',note:'$2,000 start · independent new account'},
    {key:'tasty-session-v2-20261019',label:'Original · three positions',note:'Preserved balance and unresolved exits'},
  ]},
  {title:'Lotto · calls + puts',parameter:'lotto_account',page:'lottery',items:[
    {key:'lotto-v3-contract100-multi5-fixed5',label:'Lotto · 5× exit',note:'$500 start · up to five positions'},
    {key:'lotto-v3-contract100-multi5-trail40',label:'Lotto · trail after 2×',note:'$500 start · 40% trail · five positions'},
  ]},
  {title:'Frozen breakout / retest study',parameter:'research_account',page:'backtest-lab',items:[
    {key:'breakout-retest-v1:control:base',label:'Immediate breakout',note:'$2,000 start · original modeled costs'},
    {key:'breakout-retest-v1:treatment:base',label:'Wait for retest',note:'$2,000 start · original modeled costs'},
    {key:'breakout-retest-v1:control:stress',label:'Immediate · cost stress',note:'$2,000 start · 3¢/side slippage'},
    {key:'breakout-retest-v1:treatment:stress',label:'Retest · cost stress',note:'$2,000 start · 3¢/side slippage'},
  ]},
];

export function AccountDirectory(){
  return <details className="account-directory">
    <summary>Paper accounts · balances &amp; graphs <span>Open an account →</span></summary>
    <p>Separate simulations, not one combined balance. Starting amounts below are account policies—not current values or confirmation of activation. Open an account for its saved value, quote gaps and trades.</p>
    {groups.map(group=><section key={group.title} aria-label={group.title}><h3>{group.title}</h3><div className="account-directory-grid">
      {group.items.map(item=>{const url=new URL(window.location.href);
        for(const key of ['paper_account','lotto_account','research_account'])url.searchParams.delete(key);
        url.searchParams.set(group.parameter,item.key);url.hash=group.page;
        return <a key={item.key} href={`${url.pathname}${url.search}${url.hash}`}><strong>{item.label}</strong><small>{item.note}</small><span>View balance &amp; trades →</span></a>;
      })}
    </div></section>)}
  </details>;
}

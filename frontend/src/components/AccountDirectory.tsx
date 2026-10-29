import './account-directory.css';

type AccountGroup={title:string;parameter:string;page:string;items:{key:string;label:string;note:string}[]};

const main:AccountGroup={title:'Main account',parameter:'paper_account',page:'performance',items:[
  {key:'tasty-capacity-ten-v1',label:'Main · ten positions',note:'1-minute + Structured Intraday · $2,000 starting policy'},
]};

const history:AccountGroup={title:'Earlier main account',parameter:'paper_account',page:'performance',items:[
  {key:'tasty-session-v2-20261019',label:'Original · three positions',note:'Preserved balance and unresolved exits'},
]};

const experiments:AccountGroup[]=[
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

function AccountLinks({group}:{group:AccountGroup}){
  return <div className="account-directory-grid">
      {group.items.map(item=>{const url=new URL(window.location.href);
        for(const key of ['paper_account','lotto_account','research_account'])url.searchParams.delete(key);
        url.searchParams.set(group.parameter,item.key);url.hash=group.page;
        return <a key={item.key} href={`${url.pathname}${url.search}${url.hash}`}><strong>{item.label}</strong><small>{item.note}</small><span>View balance &amp; trades →</span></a>;
      })}
    </div>;
}

export function AccountDirectory(){
  return <section className="account-directory" aria-label="Paper accounts">
    <header><h2>Your paper accounts</h2><span>Simulated money · separate results</span></header>
    <section className="account-directory-main" aria-label={main.title}>
      <AccountLinks group={main}/>
    </section>
    <p className="account-directory-note">Open your main account for its balance, P/L graph and trades. Starting amounts are policies—not current balances or confirmation of activation. Never combine overlapping account results.</p>
    <details>
      <summary>Experiments <span>6 comparison accounts</span></summary>
      <p>Separate paper tests following shared opportunities. These are comparisons, not six independent sources of profit.</p>
      {experiments.map(group=><section key={group.title} aria-label={group.title}><h3>{group.title}</h3><AccountLinks group={group}/></section>)}
    </details>
    <details>
      <summary>History <span>Earlier accounts &amp; preserved exposure</span></summary>
      <p>Organized here for a cleaner board—not stopped, reset or settled. Existing processing rules remain unchanged; unresolved exits still count as unknown exposure.</p>
      <AccountLinks group={history}/>
      <p>For older archived main or lotto trials, open the corresponding account page and use its trial selector. Saved records remain available.</p>
    </details>
  </section>;
}

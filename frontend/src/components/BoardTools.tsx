import type {ReactNode} from 'react';
import './board-tools.css';

export function BoardTools({selector,watch,alerts,viewLabel,watchLabel,alertCount}:{
  selector:ReactNode;watch:ReactNode;alerts:ReactNode;viewLabel:string;watchLabel:string;alertCount:number;
}) {
  return <div className="board-tools" aria-label="Trade board tools">
    {[
      {id:'selector',label:'Play Selector',state:viewLabel,content:selector},
      {id:'watch',label:'Flex Scanner',state:watchLabel,content:watch},
      {id:'alerts',label:'Signal Alerts',state:`${alertCount} recorded`,content:alerts},
    ].map(tool=><details className="board-tool" key={tool.id}>
      <summary><span>{tool.label}</span><small>{tool.state}</small></summary>
      <div className="board-tool-content">{tool.content}</div>
    </details>)}
  </div>;
}

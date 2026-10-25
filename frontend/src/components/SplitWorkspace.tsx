import {useEffect,useRef,useState} from 'react';
import type {ReactNode} from 'react';

const compactQuery='(max-width: 999px), (orientation: portrait)';
export function SplitWorkspace({children,detail,title,onClose}:{children:ReactNode;detail:ReactNode|null;title:string;onClose:()=>void}){
  const [compact,setCompact]=useState(()=>window.matchMedia?.(compactQuery).matches??false);
  const panel=useRef<HTMLElement>(null);
  const list=useRef<HTMLDivElement>(null);
  const close=useRef(onClose);close.current=onClose;
  const open=detail!==null;
  useEffect(()=>{
    const query=window.matchMedia?.(compactQuery);if(!query)return;
    const update=()=>setCompact(query.matches);query.addEventListener('change',update);
    return()=>query.removeEventListener('change',update);
  },[]);
  useEffect(()=>{
    if(!open)return;
    const previous=document.activeElement as HTMLElement|null;
    const node=panel.current;
    const listNode=list.current;
    const overflow=document.body.style.overflow;
    if(compact){document.body.style.overflow='hidden';listNode?.setAttribute('inert','')}
    node?.querySelector<HTMLButtonElement>('.detail-back')?.focus();
    const keyboard=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();close.current();return}
      if(!compact||event.key!=='Tab'||!node)return;
      const elements=Array.from(node.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),summary,[tabindex="0"]')).filter(el=>el.getClientRects().length>0);
      const first=elements[0],last=elements.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
    };
    node?.addEventListener('keydown',keyboard);
    return()=>{
      node?.removeEventListener('keydown',keyboard);listNode?.removeAttribute('inert');
      if(compact)document.body.style.overflow=overflow;
      if(previous?.isConnected)previous.focus();
    };
  },[open,compact]);
  return <div className={`split-workspace ${open?'has-detail':''}`}>
    <div className="split-list" ref={list}>{children}</div>
    {open&&<aside ref={panel} className={`detail-panel ${compact?'compact-detail':''}`} role={compact?'dialog':'complementary'} aria-modal={compact?true:undefined} aria-label={title}>
      <header className="detail-panel-header"><button className="detail-back" type="button" onClick={onClose}>← Back to plays</button><span>{title}</span><small>Paper research</small></header>
      <div className="detail-panel-body">{detail}</div>
    </aside>}
  </div>;
}

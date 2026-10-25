import {useState} from 'react';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {SplitWorkspace} from './SplitWorkspace';

afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals()});
function Example(){const [open,setOpen]=useState(false);return <SplitWorkspace title="Test play" detail={open?<button>Evidence</button>:null} onClose={()=>setOpen(false)}><button onClick={()=>setOpen(true)}>Inspect</button></SplitWorkspace>}
test('landscape opens a complementary inspector, Escape returns focus to the play',()=>{
  render(<Example/>);const inspect=screen.getByText('Inspect');inspect.focus();fireEvent.click(inspect);
  expect(screen.getByRole('complementary',{name:'Test play'})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:/Back to plays/})).toHaveFocus();
  fireEvent.keyDown(document.activeElement!,{key:'Escape'});
  expect(screen.queryByRole('complementary')).not.toBeInTheDocument();expect(inspect).toHaveFocus();
});
test('portrait uses a modal, traps keyboard focus and restores scrolling on close',()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}));
  vi.spyOn(HTMLElement.prototype,'getClientRects').mockReturnValue([{width:10}] as unknown as DOMRectList);
  render(<Example/>);fireEvent.click(screen.getByText('Inspect'));
  expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal','true');
  expect(document.body.style.overflow).toBe('hidden');expect(screen.getByText('Inspect').parentElement).toHaveAttribute('inert');
  const back=screen.getByRole('button',{name:/Back to plays/});fireEvent.keyDown(back,{key:'Tab',shiftKey:true});expect(screen.getByText('Evidence')).toHaveFocus();
  fireEvent.keyDown(screen.getByText('Evidence'),{key:'Tab'});expect(back).toHaveFocus();
  fireEvent.click(back);expect(document.body.style.overflow).toBe('');expect(screen.getByText('Inspect').parentElement).not.toHaveAttribute('inert');
});

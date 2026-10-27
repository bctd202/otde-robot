import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {BoardTools} from './BoardTools';

afterEach(cleanup);

test('tools start collapsed without unmounting controls or hiding their summary state',()=>{
  const action=vi.fn();
  const {container,rerender}=render(<BoardTools selector={<button onClick={action}>Change view</button>}
    watch={<input aria-label="Ticker draft" defaultValue="SPY"/>} alerts={<p>Latest alert</p>}
    viewLabel="All plays" watchLabel="1/2 slots used" alertCount={4}/>);
  const panels=container.querySelectorAll('details');
  expect(panels).toHaveLength(3);
  panels.forEach(panel=>expect(panel.open).toBe(false));
  expect(screen.getByText('1/2 slots used')).toBeVisible();
  expect(screen.getByText('4 recorded')).toBeVisible();
  panels[0].open=true;fireEvent(panels[0],new Event('toggle'));
  fireEvent.click(screen.getByRole('button',{name:'Change view'}));
  expect(action).toHaveBeenCalledOnce();
  panels[1].open=true;fireEvent(panels[1],new Event('toggle'));
  fireEvent.change(screen.getByLabelText('Ticker draft'),{target:{value:'QQQ'}});
  panels[1].open=false;fireEvent(panels[1],new Event('toggle'));
  rerender(<BoardTools selector={<button>Change view</button>} watch={<input aria-label="Ticker draft" defaultValue="SPY"/>}
    alerts={<p>New alert</p>} viewLabel="Structured Intraday" watchLabel="1/2 slots used" alertCount={5}/>);
  panels[1].open=true;fireEvent(panels[1],new Event('toggle'));
  expect(screen.getByLabelText('Ticker draft')).toHaveValue('QQQ');
  expect(screen.getByText('Structured Intraday')).toBeVisible();
  expect(screen.getByText('5 recorded')).toBeVisible();
});

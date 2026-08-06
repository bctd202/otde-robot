import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {StrategyControls} from './StrategyControls';

afterEach(cleanup);

test('strategy selector is unlocked and alert lanes toggle independently',()=>{
  const onViewChange=vi.fn(),onAlertChange=vi.fn();
  render(<StrategyControls view="ALL" onViewChange={onViewChange}
    alerts={{ONE_MIN_0DTE:true,STRUCTURED_INTRADAY:true}} onAlertChange={onAlertChange}/>);
  fireEvent.click(screen.getByRole('button',{name:'Structured Intraday'}));
  expect(onViewChange).toHaveBeenCalledWith('STRUCTURED_INTRADAY');
  fireEvent.click(screen.getByRole('checkbox',{name:'1-Min / 0DTE'}));
  expect(onAlertChange).toHaveBeenCalledWith('ONE_MIN_0DTE',false);
  expect(screen.getByText(/Both engines keep scanning and recording/)).toBeInTheDocument();
});

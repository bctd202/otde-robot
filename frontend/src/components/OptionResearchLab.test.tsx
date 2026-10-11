import {cleanup,render,screen,within} from '@testing-library/react';
import {afterEach,expect,test} from 'vitest';
import {OneMinuteRules,OptionResearchLab} from './OptionResearchLab';
import type {OptionPathResearch} from '../types';

afterEach(cleanup);
const data:OptionPathResearch={definition:{version:'option-path-v1',code_fingerprint:'abcdef',maximum_hold_minutes:[15,30,60],collection:'CACHE_ONLY'},
  observations:12,quoted_observations:10,gap_observations:2,observed_plays:1,
  fixed_cost_per_contract:1,additional_requests:0,note:'Exploratory; no orders or exit rules are changed.',
  scenarios:[15,30,60].map(minutes=>({maximum_hold_minutes:minutes,matched_plays:0,incomplete_plays:1,
    baseline_net_dollars:0,alternative_net_dollars:0,difference_dollars:0}))};

test('does not present missing historical paths as zero-dollar results',()=>{
  render(<OptionResearchLab data={data}/>);
  expect(screen.getByText('Collecting a new forward sample')).toBeInTheDocument();
  expect(screen.getByText('2 missing / stale observations')).toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  const rows=screen.getAllByRole('row').slice(1);
  for(const row of rows) expect(within(row).getAllByText('—')).toHaveLength(3);
  expect(screen.getByText(/0 additional provider requests/)).toBeInTheDocument();
});

test('plots matched baseline and maximum-hold samples with costs and exclusions',()=>{
  render(<OptionResearchLab data={{...data,scenarios:[{maximum_hold_minutes:15,matched_plays:2,
    incomplete_plays:1,baseline_net_dollars:-36,alternative_net_dollars:14,difference_dollars:50}]}}/>);
  expect(screen.getByRole('img',{name:'Baseline versus maximum-hold option results'})).toBeInTheDocument();
  const table=screen.getByRole('table');
  expect(within(table).getByText('-$36.00')).toBeInTheDocument();
  expect(within(table).getByText('$14.00')).toBeInTheDocument();
  expect(within(table).getByText('$50.00')).toBeInTheDocument();
  expect(screen.getByText('$1.00 assumed cost per contract')).toBeInTheDocument();
});

test('explains one-minute timeframe and keeps displayed option targets separate',()=>{
  render(<OneMinuteRules/>);
  expect(screen.getByText(/not a one-minute holding period/)).toBeInTheDocument();
  expect(screen.getByText(/Displayed option targets do not currently control/)).toBeInTheDocument();
  expect(screen.getByText(/At least eight are required/)).toBeInTheDocument();
});

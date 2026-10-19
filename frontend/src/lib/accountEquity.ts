import type {AccountEquityPoint} from '../types';

// A missing valuation or missed intraday collection interval is a gap, not a
// zero, carried purchase price, or line interpolated through missing evidence.
export function equitySegments(points:AccountEquityPoint[],intraday:boolean):AccountEquityPoint[][]{
  const segments:AccountEquityPoint[][]=[];
  let current:AccountEquityPoint[]=[];
  for(const point of points){
    if(point.equity_cents===null||point.return_percent===null){
      if(current.length)segments.push(current);
      current=[];continue;
    }
    if(intraday&&current.length&&Date.parse(point.at)-Date.parse(current[current.length-1].at)>180000){
      segments.push(current);current=[];
    }
    current.push(point);
  }
  if(current.length)segments.push(current);
  return segments;
}

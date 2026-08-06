const DATE_ONLY=/^(\d{4})-(\d{2})-(\d{2})$/;
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

/** Format an API calendar date without interpreting it as a timestamp. */
export function formatDateOnly(value:string|null|undefined):string {
  if(!value)return '—';
  const match=DATE_ONLY.exec(value);
  if(!match)return value;
  const year=Number(match[1]);
  const month=Number(match[2]);
  const day=Number(match[3]);
  const check=new Date(Date.UTC(year,month-1,day));
  if(check.getUTCFullYear()!==year||check.getUTCMonth()!==month-1||check.getUTCDate()!==day)return value;
  return `${MONTHS[month-1]} ${day}, ${year}`;
}

const easternTime=new Intl.DateTimeFormat('en-US',{
  timeZone:'America/New_York',hour:'numeric',minute:'2-digit',timeZoneName:'short',
});
const easternDateTime=new Intl.DateTimeFormat('en-US',{
  timeZone:'America/New_York',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short',
});

const API_DATETIME_WITHOUT_ZONE=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

/** SQLite stores UTC datetimes without an offset; interpret those as UTC, never browser-local time. */
export function parseApiTimestamp(value:string|Date|null|undefined):Date|null {
  if(!value)return null;
  const normalized=typeof value==='string'&&API_DATETIME_WITHOUT_ZONE.test(value)?`${value}Z`:value;
  const date=normalized instanceof Date?normalized:new Date(normalized);
  return Number.isNaN(date.getTime())?null:date;
}

export function formatEasternTime(value:string|Date|null|undefined):string {
  if(!value)return '—';
  const date=parseApiTimestamp(value);
  return date?easternTime.format(date):String(value);
}

export function formatEasternDateTime(value:string|Date|null|undefined):string {
  if(!value)return '—';
  const date=parseApiTimestamp(value);
  return date?easternDateTime.format(date):String(value);
}

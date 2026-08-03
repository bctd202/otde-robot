import { afterEach, describe, expect, test, vi } from 'vitest';
import { formatDateOnly, formatEasternDateTime, formatEasternTime } from './dates';

afterEach(()=>vi.unstubAllEnvs());

describe.each(['America/New_York','America/Los_Angeles','Asia/Tokyo'])('browser timezone %s',timezone=>{
  test('keeps date-only expiration on its calendar day',()=>{
    vi.stubEnv('TZ',timezone);
    expect(formatDateOnly('2026-08-03')).toBe('Aug 3, 2026');
  });
});

test('formats actual timestamps in Eastern Time',()=>{
  expect(formatEasternTime('2026-08-03T14:30:00Z')).toBe('10:30 AM EDT');
  expect(formatEasternDateTime('2026-08-03T14:30:00Z')).toBe('Aug 3, 2026, 10:30 AM EDT');
});

test('leaves malformed or non-date-only values visible for diagnosis',()=>{
  expect(formatDateOnly('2026-02-30')).toBe('2026-02-30');
  expect(formatDateOnly('not-a-date')).toBe('not-a-date');
});

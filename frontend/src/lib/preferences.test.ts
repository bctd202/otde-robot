import {afterEach,expect,test,vi} from 'vitest';
import {readPreference,savePreference} from './preferences';
afterEach(()=>{vi.restoreAllMocks();localStorage.clear()});
test('presentation preferences survive reload without requiring storage permission',()=>{
  savePreference('page','lottery');expect(readPreference('page')).toBe('lottery');
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new Error('Storage blocked')});
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('Storage blocked')});
  expect(readPreference('page')).toBeNull();expect(()=>savePreference('page','parlay')).not.toThrow();
});

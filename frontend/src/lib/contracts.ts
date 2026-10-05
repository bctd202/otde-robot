import type { Contract } from '../types';

const approvedLiveProviders=new Set(['tradier','tastytrade']);

export function isVerifiedLiveContract(contract:Contract|null|undefined):boolean {
  return Boolean(contract?.actionable===true&&contract.verification_status==='verified'&&
    contract.provider&&approvedLiveProviders.has(contract.provider)&&contract.data_mode==='live'&&
    contract.normalized_symbol&&contract.bid_timestamp&&contract.ask_timestamp&&contract.timestamp);
}

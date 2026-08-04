export interface ProviderStatus { provider:string; mode:string; status:string; delay_seconds:number; latest_timestamp:string; message:string }
export interface Quote { symbol:string; price:number; timestamp:string }
export interface Contract { option_symbol:string; bid:number; ask:number; volume:number; open_interest:number; delta:number|null; gamma:number|null }
export interface Setup { symbol:string; name:string; direction:string; grade:string; score:number; entry_trigger:number; invalidation:number; target1:number; target2:number; reward_risk:number; contract:Contract|null; confluences:string[] }
export interface Lottery { symbol:string; right:string; strike:number; bid:number; ask:number; midpoint:number; total_debit:number; spread_percent:number; delta:number|null; gamma:number|null; underlying_trigger:number; underlying_invalidation:number; break_even:number; estimated_2x_underlying:number; estimated_5x_underlying:number; estimated_10x_underlying:number; setup_score:number; explanation:string; worthless_reasons:string[] }
export interface LiquidityLevels { previous_day_high:number; previous_day_low:number; opening_range_high:number; opening_range_low:number; session_high:number; session_low:number; vwap:number; equal_highs:number[]; equal_lows:number[] }
export interface Dashboard { provider_status:ProviderStatus; quotes:Quote[]; market_session:string; volatility_proxy:number|null; levels:Record<string,LiquidityLevels>; directional_bias:Record<string,string>; news_warning:string; normal_setups:Setup[]; lottery_setups:Lottery[]; no_trade:boolean; paper_account:Record<string,string|number|boolean> }
export interface JournalSignal { id:number; symbol:string; signal_type:string; status:string; generated_at:string; payload:Record<string,unknown> }
export interface Analytics { minimum_sample_size:number; sample_size:number; statistically_promising:boolean; win_rate:number; profit_factor:number|null; average_winner:number; average_loser:number; expectancy:number; message:string }
export type SignalStatus='BUY'|'WATCH'|'MISSED'|'PASS'|'UNAVAILABLE';
export type ParlayDirection='call'|'put'|'none';
export type ScoreLabel='PLAY'|'WATCH CLOSELY'|'DEVELOPING'|'PASS';
export interface ParlayContract extends Contract { symbol:string; expiration:string; strike:number; right:string; last:number; iv:number|null; theta:number|null; vega:number|null; timestamp:string; bid_timestamp?:string|null; ask_timestamp?:string|null; provider?:string; data_mode?:string; verification_status?:string; verification_reason?:string; actionable?:boolean; normalized_symbol?:string|null }
export interface ParlayCandidate {
  ranking_position:number; symbol:string; rank:string; direction:ParlayDirection; signal_status:SignalStatus;
  score:number; score_label:ScoreLabel; underlying_price:number|null; contract:ParlayContract|null;
  contract_cost:number|null; midpoint:number|null; spread_percent:number|null; entry_low:number|null;
  entry_high:number|null; no_chase_price:number|null; underlying_trigger:number|null;
  underlying_invalidation:number|null; first_underlying_target:number|null; stretch_underlying_target:number|null;
  first_option_target:number|null; stretch_option_target:number|null; reasons:string[]; rejection_reasons:string[];
  unavailable_reason:string|null; primary_action:string; generated_at:string; data_freshness:string;
  contract_verification_status?:string; contract_verification_reason?:string|null; actionable?:boolean; demo_mode?:boolean;
}
export interface ScannerHealth { candidate_count:number; unavailable_candidate_count:number; provider_status:string }
export interface ParlayResponse { provider_status:ProviderStatus; universe:string[]; candidates:ParlayCandidate[]; scanner_health:ScannerHealth; paper_only:boolean }
export type PaperDecision='HOLD'|'TAKE_PROFIT'|'EXIT'|'DATA_UNAVAILABLE'|'EXPIRED'|'CLOSED';
export interface PaperPosition {
  id:number; symbol:string; option_symbol:string; direction:'call'|'put'; expiration:string; strike:number;
  quantity:number; entry_option_price:number; entry_underlying_price:number; total_debit:number;
  underlying_trigger:number; underlying_invalidation:number; first_underlying_target:number;
  stretch_underlying_target:number; first_option_target:number; stretch_option_target:number;
  score:number; score_label:string; entry_reasons:string[]; provider_mode:string; opened_at:string;
  closed_at:string|null; exit_option_price:number|null; exit_underlying_price:number|null; exit_reason:string|null;
  lifecycle_status:'ACTIVE'|'EXPIRED'|'CLOSED'; expired_at:string|null; current_option_price:number|null; current_underlying_price:number|null;
  unrealized_pnl:number|null; realized_pnl:number|null; pnl_percent:number|null; decision_status:PaperDecision;
  data_freshness:string; next_action:string; last_marked_at:string|null; paper_only:boolean;
}
export interface PaperPositionsResponse { positions:PaperPosition[]; paper_only:boolean }
export interface PerformanceMetrics { total_triggered_signals:number;open_signals:number;targets_hit:number;stops_hit:number;timed_exits:number;invalidated_missed:number;win_rate:number;average_r:number;cumulative_r:number;profit_factor:number|null;maximum_drawdown_r:number;average_duration:number;average_mfe:number;average_mae:number }
export interface PerformanceSignal { signal_id:string;source:'LIVE'|'BACKTEST';ticker:string;direction:'CALL'|'PUT';setup_type:string;trading_date:string;triggered_at:string;entry_price:number;stop_price:number;target_price:number;exit_reason:string;result_r:number|null;duration_minutes:number|null;score:number;user_entered:boolean;option_snapshot:Record<string,unknown>|null;strategy_snapshot:Record<string,unknown>;condition_snapshot:Record<string,unknown>;conservative_same_candle:boolean }
export interface PerformanceResponse {metrics:PerformanceMetrics;signals:PerformanceSignal[];timezone:string;underlying_only:boolean;paper_only:boolean}
export interface BacktestRun {id:string;requested_start:string;requested_end:string;actual_start:string|null;actual_end:string|null;tickers:string[];status:string;warnings:string[];failures:Record<string,string>;started_at:string;completed_at:string|null}

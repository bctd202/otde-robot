from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "0DTE Liquidity Hunter"
    database_url: str = "sqlite:///./liquidity_hunter.db"
    market_data_provider: str = "mock"
    symbols: str = "SPY,QQQ,IWM"
    timezone: str = "America/New_York"
    structured_risk_percent: float = 0.25
    structured_min_rr: float = 2.0
    lottery_max_debit: float = 40.0
    lottery_max_ask: float = 0.40
    lottery_min_ask: float = 0.05
    lottery_min_volume: int = 250
    lottery_min_open_interest: int = 500
    lottery_max_spread_pct: float = 30.0
    lottery_min_delta: float = 0.05
    lottery_max_delta: float = 0.25
    paper_account_size: float = 25000.0
    paper_only: bool = True
    event_trading_enabled: bool = False
    close_to_close_squeeze_enabled: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    mock_scenario: str = "active"
    enable_demo_option_contracts: bool = False
    tradier_api_token: str | None = None
    tradier_base_url: str = "https://api.tradier.com/v1"
    tradier_data_mode: str = "unknown"
    parlay_symbols: str = "SPY,QQQ,IWM,TSLA,NVDA,AAPL,AMZN,META,MSFT,GOOGL,AVGO,IBIT,GLD,SLV,TLT,USO,UNG,AMD,COIN,PLTR"
    parlay_symbol_limit: int = 20
    parlay_flex_limit: int = 2

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def parlay_symbol_list(self) -> list[str]:
        """The bounded, de-duplicated universe used by the Parlay scanner."""
        return list(dict.fromkeys(
            s.strip().upper() for s in self.parlay_symbols.split(",") if s.strip()
        ))[:max(1, min(self.parlay_symbol_limit, 50))]


@lru_cache
def get_settings() -> Settings:
    return Settings()

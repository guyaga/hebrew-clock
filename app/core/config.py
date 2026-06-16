from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 8765
    display_lag: int = 8
    # Defaults to the project root (parent of app/); override with FONT_DIR env var.
    font_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)
    gtag_id: str | None = None  # set GTAG_ID env var to enable Google Analytics
    # Trusted proxy IP list for X-Forwarded-Proto. Set FORWARDED_ALLOW_IPS to a
    # comma-separated CIDR/IP list (e.g. "10.0.0.0/8,127.0.0.1") to restrict which
    # upstream proxies are trusted. Default "*" suits PaaS deployments (Render,
    # Heroku) where proxy IPs are not predictable; tighten in self-hosted setups.
    forwarded_allow_ips: str = "*"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

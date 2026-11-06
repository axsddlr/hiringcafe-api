"""Runtime configuration, env-overridable with sane production defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable settings snapshot.

    The two values that matter most for getting past Cloudflare are
    ``impersonate`` (TLS/HTTP2 fingerprint profile) and ``user_agent``
    (must agree with the impersonated Chrome major version).
    """

    base_url: str = "https://hiringcafe.com"
    page_path: str = "/classic"

    timeout: float = 30.0
    retries: int = 1
    impersonate: str = "chrome"
    user_agent: str = DEFAULT_USER_AGENT

    # buildId rotates on every Vercel deployment; cache it but re-discover on 404.
    build_id_ttl: float = 6 * 3600

    # Short response cache: identical searches within the window cost nothing upstream.
    cache_ttl: float = 300.0
    cache_max: int = 256

    # Upstream politeness limit for concurrent outbound requests.
    max_concurrency: int = 4

    # Guard against a caller posting a multi-megabyte searchState.
    max_search_state_bytes: int = 20_000

    default_radius: int = 50
    default_radius_unit: str = "miles"

    zipdb_path: Path = field(default_factory=lambda: ROOT / "data" / "us_zips.db")

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        base = cls()
        return replace(
            base,
            base_url=_env_str("HC_BASE_URL", base.base_url),
            page_path=_env_str("HC_PAGE_PATH", base.page_path),
            timeout=_env_float("HC_TIMEOUT", base.timeout),
            retries=_env_int("HC_RETRIES", base.retries),
            impersonate=_env_str("HC_IMPERSONATE", base.impersonate),
            user_agent=_env_str("HC_USER_AGENT", base.user_agent),
            build_id_ttl=_env_float("HC_BUILD_ID_TTL", base.build_id_ttl),
            cache_ttl=_env_float("HC_CACHE_TTL", base.cache_ttl),
            cache_max=_env_int("HC_CACHE_MAX", base.cache_max),
            max_concurrency=max(1, _env_int("HC_MAX_CONCURRENCY", base.max_concurrency)),
            max_search_state_bytes=max(
                256, _env_int("HC_MAX_SEARCH_STATE_BYTES", base.max_search_state_bytes)
            ),
            default_radius=_env_int("HC_DEFAULT_RADIUS", base.default_radius),
            default_radius_unit=_env_str("HC_DEFAULT_RADIUS_UNIT", base.default_radius_unit),
            zipdb_path=Path(_env_str("HC_ZIPDB_PATH", str(base.zipdb_path))),
            log_level=_env_str("HC_LOG_LEVEL", base.log_level),
        )

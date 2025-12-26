import os, time
from urllib.parse import urlparse, urlunparse

import redis


def _force_loopback_redis(url: str, default_db: int = 0) -> str:
    """Return a Redis URL that is safe on non-Docker hosts.

    If the env contains Docker-era URLs like redis://redis:6379/0, the hostname
    "redis" will not resolve on EC2. Force loopback for those hostnames.
    """
    if not url:
        return f"redis://127.0.0.1:6379/{default_db}"

    p = urlparse(url)
    if p.scheme not in {"redis", "rediss"}:
        return url

    host = p.hostname or ""
    port = p.port or 6379
    db_path = p.path if p.path else f"/{default_db}"

    if host in {"redis", "localhost", ""}:
        host = "127.0.0.1"

    auth = ""
    if p.username:
        auth += p.username
    if p.password:
        auth += f":{p.password}"
    if auth:
        auth += "@"

    netloc = f"{auth}{host}:{port}"
    return urlunparse((p.scheme, netloc, db_path, "", p.query, p.fragment))


_RURL = (
    os.getenv("RATELIMIT_REDIS_URL")
    or os.getenv("CELERY_BROKER_URL")
    or "redis://127.0.0.1:6379/0"
)

_RURL = _force_loopback_redis(_RURL, default_db=0)

_r = redis.Redis.from_url(_RURL)


class RateLimitExceeded(Exception): ...


def _bucket(key: str, window_sec: int, max_count: int):
    p = _r.pipeline()
    p.incr(key, 1)
    p.expire(key, window_sec)
    count, _ = p.execute()
    if int(count) > max_count:
        raise RateLimitExceeded(f"Rate limit exceeded for {key}")


def check_global_per_min():
    cap = int(os.getenv("WA_RATE_GLOBAL_PER_MIN", "90"))
    _bucket("rl:wa:global:1m", 60, cap)


def check_per_phone_daily(phone: str, template: str):
    cap = int(os.getenv("WA_RATE_PER_PHONE_PER_DAY", "2"))
    key = f"rl:wa:{template}:{phone}:1d"
    _bucket(key, 24 * 3600, cap)

# import os, time
# import redis

# _RURL = (
#     os.getenv("RATELIMIT_REDIS_URL")
#     or os.getenv("CELERY_BROKER_URL")
#     or "redis://127.0.0.1:6379/0"
# )

# _r = redis.Redis.from_url(_RURL)

# class RateLimitExceeded(Exception): ...

# def _bucket(key: str, window_sec: int, max_count: int):
#     now = int(time.time())
#     p = _r.pipeline()
#     p.incr(key, 1)
#     p.expire(key, window_sec)
#     count, _ = p.execute()
#     if int(count) > max_count:
#         raise RateLimitExceeded(f"Rate limit exceeded for {key}")

# def check_global_per_min():
#     cap = int(os.getenv("WA_RATE_GLOBAL_PER_MIN", "90"))
#     _bucket("rl:wa:global:1m", 60, cap)

# def check_per_phone_daily(phone: str, template: str):
#     cap = int(os.getenv("WA_RATE_PER_PHONE_PER_DAY", "2"))
#     key = f"rl:wa:{template}:{phone}:1d"
#     _bucket(key, 24*3600, cap)

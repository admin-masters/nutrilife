import os, time
import redis

_RURL = os.getenv("RATELIMIT_REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
_r = redis.Redis.from_url(_RURL)

class RateLimitExceeded(Exception): ...

def _bucket(key: str, window_sec: int, max_count: int):
    now = int(time.time())
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
    _bucket(key, 24*3600, cap)

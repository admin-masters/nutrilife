import os, time
import redis

_RURL = os.getenv("RATELIMIT_REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
#_r = redis.Redis.from_url(_RURL)
_r = None  # Will be initialized on first use

def _get_redis():
    """Lazy initialization of Redis connection."""
    global _r
    if _r is None:
        _r = redis.Redis.from_url(_RURL)
    return _r

class RateLimitExceeded(Exception): ...

# def _bucket(key: str, window_sec: int, max_count: int):
#     now = int(time.time())
#     #p = _r.pipeline()
#     p = _get_redis().pipeline()
#     p.incr(key, 1)
#     p.expire(key, window_sec)
#     count, _ = p.execute()
#     if int(count) > max_count:
#         raise RateLimitExceeded(f"Rate limit exceeded for {key}")
def _bucket(key: str, window_sec: int, max_count: int):
    try:
        now = int(time.time())
        p = _get_redis().pipeline()
        p.incr(key, 1)
        p.expire(key, window_sec)
        count, _ = p.execute()
        if int(count) > max_count:
            raise RateLimitExceeded(f"Rate limit exceeded for {key}")
    except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
        # If Redis is unavailable, log but don't block the operation
        # You might want to import logging and log this
        import logging
        logging.warning(f"Redis unavailable for rate limiting: {e}. Allowing operation to proceed.")
        # Optionally, you could raise RateLimitExceeded here if you want to be strict
        pass  # Allow the operation to proceed
    
def check_global_per_min():
    cap = int(os.getenv("WA_RATE_GLOBAL_PER_MIN", "90"))
    _bucket("rl:wa:global:1m", 60, cap)

def check_per_phone_daily(phone: str, template: str):
    cap = int(os.getenv("WA_RATE_PER_PHONE_PER_DAY", "2"))
    key = f"rl:wa:{template}:{phone}:1d"
    _bucket(key, 24*3600, cap)

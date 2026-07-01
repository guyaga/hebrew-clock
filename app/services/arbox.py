"""ARBOX next-session lookup.

Finds the signed-in member's next booked class and returns it for the clock
image. Uses curl_cffi with Chrome impersonation because ARBOX sits behind
Cloudflare, which 403s plain requests/httpx on their TLS fingerprint.

Runs synchronously (curl_cffi is sync) — call it from a thread-pool worker.
Heavily cached (default 30 min) with a failure back-off so we never hammer
ARBOX and trip its IP-level rate limit.

Configure via env:
  ARBOX_EMAIL, ARBOX_PASSWORD   – required to enable the feature
  ARBOX_BOX_ID       (20152)    – HOZ30
  ARBOX_LOCATION_ID  (17351)
  ARBOX_WHITELABEL   (Arbox)
  ARBOX_LOOKAHEAD_DAYS (21)
  ARBOX_CACHE_TTL    (1800)
"""
import datetime
import json
import os

from loguru import logger

try:
    from curl_cffi import requests as _cffi
except Exception:  # pragma: no cover - import guard
    _cffi = None

BASE = "https://apiappv2.arboxapp.com"

EMAIL = os.environ.get("ARBOX_EMAIL", "").strip()
PASSWORD = os.environ.get("ARBOX_PASSWORD", "").strip()
BOX_ID = int(os.environ.get("ARBOX_BOX_ID", "20152"))
LOCATION_ID = int(os.environ.get("ARBOX_LOCATION_ID", "17351"))
WHITELABEL = os.environ.get("ARBOX_WHITELABEL", "Arbox")
LOOKAHEAD_DAYS = int(os.environ.get("ARBOX_LOOKAHEAD_DAYS", "21"))
CACHE_TTL_SECONDS = int(os.environ.get("ARBOX_CACHE_TTL", "1800"))
FAIL_BACKOFF_SECONDS = int(os.environ.get("ARBOX_FAIL_BACKOFF", "1800"))

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "whitelabel": WHITELABEL,
    "version": "11",
    "referername": "app",
    "lang": "en",
    "Origin": "https://app.arboxapp.com",
    "Referer": "https://app.arboxapp.com/",
}

# {"data": dict|None, "time": datetime|None, "last_fail": datetime|None, "token": str|None}
_cache: dict = {"data": None, "time": None, "last_fail": None, "token": None}


def is_configured() -> bool:
    return bool(_cffi and EMAIL and PASSWORD)


def _israel_now() -> datetime.datetime:
    utc = datetime.datetime.utcnow()
    return utc + datetime.timedelta(hours=3 if 3 <= utc.month <= 10 else 2)


def _login(session) -> str:
    resp = session.post(
        f"{BASE}/api/v2/user/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login {resp.status_code}: {resp.text[:200]}")
    return str(resp.json()["data"]["token"])


def _schedule(session, token: str) -> list:
    today = _israel_now()
    start = today.strftime("%Y-%m-%d")
    end = (today + datetime.timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")
    payload = {
        "from": f"{start}T00:00:00.000Z",
        "to": f"{end}T23:59:59.000Z",
        "locations_box_id": LOCATION_ID,
        "boxes_id": BOX_ID,
    }
    session.headers.update({"accesstoken": token})
    resp = session.post(
        f"{BASE}/api/v2/schedule/betweenDates", data=json.dumps(payload)
    )
    if resp.status_code == 401:
        raise PermissionError("token expired")
    if resp.status_code != 200:
        raise RuntimeError(f"schedule {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("data", [])


def _pick_next(items: list) -> dict | None:
    now = _israel_now()
    best = None
    best_dt = None
    for c in items:
        if not c.get("user_booked"):
            continue
        date_s = c.get("date")
        time_s = str(c.get("time") or "")[:5]
        if not date_s or not time_s:
            continue
        try:
            dt = datetime.datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if dt < now:
            continue
        if best_dt is None or dt < best_dt:
            best_dt = dt
            cat = c.get("box_categories") or {}
            best = {
                "category": str(cat.get("name") or "").strip(),
                "date": date_s,
                "time": time_s,
                "weekday": dt.weekday(),  # Mon=0 .. Sun=6
            }
    return best


def get_next_session() -> dict | None:
    """Return {category, date, time, weekday} for the next booked class, or None."""
    if not is_configured():
        return None

    now = datetime.datetime.utcnow()
    cached_at = _cache.get("time")
    if cached_at and (now - cached_at).total_seconds() < CACHE_TTL_SECONDS:
        return _cache.get("data")

    failed_at = _cache.get("last_fail")
    if failed_at and (now - failed_at).total_seconds() < FAIL_BACKOFF_SECONDS:
        return _cache.get("data")

    try:
        session = _cffi.Session(impersonate="chrome")
        session.headers.update(_HEADERS)
        token = _cache.get("token") or _login(session)
        _cache["token"] = token
        try:
            items = _schedule(session, token)
        except PermissionError:
            token = _login(session)
            _cache["token"] = token
            items = _schedule(session, token)

        result = _pick_next(items)
        _cache.update({"data": result, "time": now, "last_fail": None})
        if result:
            logger.info("arbox next: {} {} {}", result["date"], result["time"], result["category"])
        else:
            logger.info("arbox: no upcoming booked class")
        return result
    except Exception as exc:
        logger.warning("arbox error: {}", exc)
        _cache["last_fail"] = now
        _cache["token"] = None  # force fresh login next time
        return _cache.get("data")

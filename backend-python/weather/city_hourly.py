# -*- coding: utf-8 -*-
"""逐市小时级气象（open-meteo hourly）：全国模型推理的输入。

为什么不用 `city_weather.py`
----------------------------
那个只取 `current`（温度/风速/能见度三项），够画屏，不够喂模型 ——
模型要露点、气压、云量、以及 3/6 小时的历史极值与趋势。这里一次取 48 小时
（过去 24 + 未来 24），把当前值与历史一起算好，供 `ml.national_model` 推理。

口径：open-meteo 是**模式输出**，不是观测；能见度尤其如此。所以全国模型输出的是
"模式能见度的低能见度概率"，界面上必须与 METAR 实测分开表述。

缓存与限流（V1.1.2 补，2026-11-15 因线上 429 重写）
----------------------------------------------------
线上事故：2026-11-15 云端出口 IP 的 open-meteo 每日额度被打满，接口返回
`Daily API request limit exceeded`。原来的实现有三处会把这件事放大：

1. **成功结果只在内存里** —— 进程重启（部署、systemd 重启、冷启动重建）就丢，
   于是每次重启都重新拉 4 批；这一天部署了若干次，等于把额度反复烧一遍。
2. **失败只缓存 300 秒** —— 每 5 分钟再撞 4 批，一天最多上千次必然失败的请求，
   额度恢复的瞬间也会被下一轮撞掉一部分。
3. **没有区分 429 与网络错误** —— 429 是"今天没了"，超时是"这一秒不通"，
   两者用同一个重试节奏，等于拿有限的额度去赌一个不可能成功的结果。

现在的规则：
- 成功 → 落盘 `data/cache/city-hourly.json`，TTL 3600 秒（模式逐时才更新，
  半小时一拉是浪费）。重启后**盘上快照还在 TTL 内就直接用**，不重新请求。
- 429 → 进入退避窗口（900 秒起，连续 429 翻倍，上限 3600 秒），窗口内
  **一次请求都不发**，直接返回 `rateLimited=true` 与 `retryAt`。
- 只有网络错误（非 429）才用 300 秒的短重试。

**过期的盘上快照不用来喂模型**：`city_weather` 交旧数据是为了"屏幕上有数"，
模型不一样 —— 特征取的是"最后一个已发生的小时"，快照老两小时，算出来的
就是两小时前那一刻的概率，时间已经错位。所以这里宁可返回空，也不拿旧快照充数。
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

API = 'https://api.open-meteo.com/v1/forecast'
HOURLY = ('temperature_2m,dew_point_2m,relative_humidity_2m,wind_speed_10m,'
          'wind_gusts_10m,wind_direction_10m,surface_pressure,cloud_cover,visibility')
BATCH = 80
PAST_DAYS = 1
FORECAST_DAYS = 1
TTL_SECONDS = 3600.0          # 成功一轮缓存 1 小时（模式逐时更新）
STALE_RETRY = 300.0           # 普通失败（超时/解析）5 分钟后再试
RATE_LIMIT_TTL = 900.0        # 429 后 15 分钟内不再硬撞，连续 429 翻倍
RATE_LIMIT_MAX = 3600.0       # 退避上限 1 小时
TIMEOUT = 60.0
USER_AGENT = 'ALC-tianchuang/1.1.2 (national model hourly; contact: project maintainer)'
CACHE_KEY = 'cities'

CACHE_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'cache' / 'city-hourly.json'

_lock = threading.Lock()
_cache: Dict[str, Any] = {'value': None, 'expires': 0.0, 'key': None,
                          'rateLimitedUntil': 0.0, 'strikes': 0}


def _cloud_base(temp: Optional[float], dew: Optional[float]) -> Optional[float]:
    if temp is None or dew is None:
        return None
    return max(0.0, 125.0 * (temp - dew))


def _features(city: Dict[str, Any], hourly: Dict[str, Any], elevation: Optional[float]) -> Optional[Dict[str, Any]]:
    times = hourly.get('time') or []
    if len(times) < 8:
        return None
    series = {key: hourly.get(key) or [] for key in
              ('temperature_2m', 'dew_point_2m', 'wind_speed_10m', 'wind_gusts_10m',
               'wind_direction_10m', 'surface_pressure', 'cloud_cover', 'visibility')}

    # 取"最后一个已发生的小时"：过去段里最后一格
    now_hour = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:00')
    index = max(6, len([t for t in times if t <= now_hour]) - 1)
    index = min(index, len(times) - 2)

    def at(key: str, offset: int = 0):
        values = series[key]
        position = index + offset
        return values[position] if 0 <= position < len(values) else None

    vis = at('visibility')
    if vis is None:
        return None
    temp, dew = at('temperature_2m'), at('dew_point_2m')
    wdir, gust = at('wind_direction_10m'), at('wind_gusts_10m')
    past_vis = [at('visibility', -k) for k in range(1, 7)]
    past_vis = [v for v in past_vis if v is not None]
    past_gust = [at('wind_gusts_10m', -k) for k in range(1, 4)]
    past_gust = [v for v in past_gust if v is not None]
    vis3, temp3, dew3 = at('visibility', -3), at('temperature_2m', -3), at('dew_point_2m', -3)
    qnh, qnh3 = at('surface_pressure'), at('surface_pressure', -3)
    hour = int(times[index][11:13])
    rad = hour * 2 * math.pi / 24.0
    base = _cloud_base(temp, dew)
    return {
        'visM': vis, 'gustMs': gust, 'windMs': at('wind_speed_10m'),
        'wdirSin': None if wdir is None else math.sin(math.radians(wdir)),
        'wdirCos': None if wdir is None else math.cos(math.radians(wdir)),
        'tempC': temp, 'dewC': dew,
        'dewSpread': None if (temp is None or dew is None) else temp - dew,
        'cloudBaseM': base, 'qnhHpa': qnh,
        'visMin3h': min(past_vis[:3]) if past_vis[:3] else None,
        'visMin6h': min(past_vis) if past_vis else None,
        'gustMax3h': max(past_gust) if past_gust else None,
        'windChange3h': None if (gust is None or not past_gust) else gust - past_gust[0],
        'qnhTendency3h': None if (qnh is None or qnh3 is None) else qnh - qnh3,
        'visChange3h': None if (vis is None or vis3 is None) else vis - vis3,
        'tempTendency3h': None if (temp is None or temp3 is None) else temp - temp3,
        'spreadTendency3h': None if (temp is None or dew is None or temp3 is None or dew3 is None)
                            else (temp - dew) - (temp3 - dew3),
        'hourSin': math.sin(rad), 'hourCos': math.cos(rad),
        'month': int(times[index][5:7]),
        'lat': city['lat'], 'lon': city['lon'], 'elevM': elevation,
        'miss_vis': 0.0,
        'miss_gust': 1.0 if gust is None else 0.0,
        'miss_cloud': 0.0 if base is not None else 1.0,
        'miss_temp': 1.0 if temp is None else 0.0,
        'observedAt': times[index],
    }


def _retry_at(seconds: float) -> str:
    stamp = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, seconds))
    return stamp.strftime('%Y-%m-%dT%H:%M:%SZ')


def _load_disk() -> Optional[Dict[str, Any]]:
    """盘上快照。只在 TTL 内复用 —— 过期快照拿来喂模型等于算错时刻。"""
    try:
        if not CACHE_FILE.is_file():
            return None
        payload = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not payload.get('cities'):
            return None
        payload['diskCache'] = True
        return payload
    except Exception:  # noqa: BLE001 - 快照坏了就当没有，不影响请求
        return None


def _save_disk(value: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        slim = dict(value)
        slim.pop('elapsedMs', None)
        CACHE_FILE.write_text(json.dumps(slim, ensure_ascii=False), encoding='utf-8')
    except Exception:  # noqa: BLE001 - 写盘失败不影响本次结果
        pass


def _disk_age_seconds(payload: Dict[str, Any]) -> Optional[float]:
    try:
        text = str(payload.get('fetchedAt') or '').replace('Z', '+00:00')
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
    except Exception:  # noqa: BLE001
        return None


def _unavailable(reason: str, errors: List[str], **extra: Any) -> Dict[str, Any]:
    value = {'available': False, 'source': 'open-meteo hourly（公开、免密钥；模式输出，非观测）',
             'fetchedAt': None, 'cities': {}, 'errors': errors, 'reason': reason,
             'elapsedMs': 0}
    value.update(extra)
    with _lock:
        _cache.update({'value': value, 'expires': time.monotonic() + STALE_RETRY, 'key': CACHE_KEY})
    return value


def fetch(rows: List[Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
    """批量取逐市小时数据并归约成特征。失败的城市留空，不补零。

    三条出口：内存命中 / 盘上快照（TTL 内）/ 真实请求。
    429 进入退避窗口，窗口内**不发请求**，直接把原因与恢复时刻交出去。
    """
    now = time.monotonic()

    with _lock:
        if not force and _cache['value'] and now < _cache['expires']:
            return _cache['value']
        blocked_for = _cache['rateLimitedUntil'] - now

    # 进程刚起来（部署、重启、冷启动重建）：盘上快照还在 TTL 内就直接用，连一次请求都不发。
    # 这一条是本次额度事故的直接教训 —— 那天重启了若干次，每次都要重拉 4 批。
    if not force:
        disk = _load_disk()
        age = _disk_age_seconds(disk) if disk else None
        if disk and age is not None and age <= TTL_SECONDS:
            if blocked_for > 0:
                disk = {**disk, 'rateLimited': True, 'retryAt': _retry_at(blocked_for)}
            with _lock:
                _cache.update({'value': disk, 'expires': now + max(60.0, TTL_SECONDS - age),
                               'key': CACHE_KEY})
            return disk

    # 退避窗口内：一次请求都不发。这段时间里"再试"只会白白烧掉恢复后的额度。
    if not force and blocked_for > 0:
        return _unavailable(
            '上游配额用尽（429），本帧模型概率不可用',
            ['429 限流：退避窗口内跳过请求（剩余 %d 秒）' % int(blocked_for)],
            rateLimited=True, retryAt=_retry_at(blocked_for), httpStatus=429)

    started = time.time()
    out: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    rate_limited = False
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        params = {
            'latitude': ','.join(f"{row['lat']:.3f}" for row in chunk),
            'longitude': ','.join(f"{row['lon']:.3f}" for row in chunk),
            'hourly': HOURLY, 'past_days': PAST_DAYS, 'forecast_days': FORECAST_DAYS,
            'timezone': 'UTC',
        }
        try:
            response = httpx.get(API, params=params, timeout=TIMEOUT,
                                 headers={'User-Agent': USER_AGENT}, trust_env=False)
            response.raise_for_status()
            payload = response.json()
            bodies = payload if isinstance(payload, list) else [payload]
        except Exception as exc:  # noqa: BLE001 - 单批失败不该让整屏没数据
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            errors.append(f'batch {start // BATCH}: {str(exc)[:80]}')
            if status == 429:
                # 限流期间剩下的批次也一定失败，别把一次点击拖成 4 次超时
                rate_limited = True
                errors.append('429 限流：剩余批次跳过，本次模型概率不可用（规则派生兜底）')
                break
            continue
        for city, body in zip(chunk, bodies):
            features = _features(city, body.get('hourly') or {}, body.get('elevation'))
            if features:
                out[city['name']] = features

    if out:
        value = {
            'available': True,
            'source': 'open-meteo hourly（公开、免密钥；模式输出，非观测）',
            'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'cities': out, 'errors': errors,
            'elapsedMs': int((time.time() - started) * 1000),
        }
        with _lock:
            _cache.update({'value': value, 'expires': now + TTL_SECONDS, 'key': CACHE_KEY,
                           'rateLimitedUntil': 0.0, 'strikes': 0})
        _save_disk(value)
        return value

    # 到这里说明一批都没成。429 与网络错误分开计时。
    if rate_limited:
        with _lock:
            strikes = int(_cache.get('strikes') or 0) + 1
            wait = min(RATE_LIMIT_TTL * (2 ** (strikes - 1)), RATE_LIMIT_MAX)
            _cache.update({'strikes': strikes, 'rateLimitedUntil': now + wait})
        errors.append('429 限流：%d 秒内不再请求上游（第 %d 次连续限流）' % (int(wait), strikes))
        disk = _load_disk()
        age = _disk_age_seconds(disk) if disk else None
        if disk and age is not None and age <= TTL_SECONDS:
            # 盘上快照还在 TTL 内：这是"重启后第一次取数就撞上 429"的情况，
            # 用它可以继续出概率，时间也还是对的。
            return {**disk, 'rateLimited': True, 'retryAt': _retry_at(wait), 'errors': errors}
        return _unavailable('上游配额用尽（429），本帧模型概率不可用', errors,
                            rateLimited=True, retryAt=_retry_at(wait), httpStatus=429)

    disk = _load_disk()
    age = _disk_age_seconds(disk) if disk else None
    if disk and age is not None and age <= TTL_SECONDS:
        return {**disk, 'errors': errors}
    return _unavailable('逐市小时数据取不到（非限流错误）', errors,
                        rateLimited=False, retryAt=_retry_at(STALE_RETRY))


def status() -> Dict[str, Any]:
    """给 modelCard 用的状态：为什么没取到、什么时候能再试。"""
    now = time.monotonic()
    with _lock:
        blocked = max(0.0, _cache['rateLimitedUntil'] - now)
        value = _cache['value'] or {}
    return {
        'available': bool(value.get('available')),
        'rateLimited': blocked > 0 or bool(value.get('rateLimited')),
        'retryAt': _retry_at(blocked) if blocked > 0 else (value.get('retryAt') or ''),
        'reason': value.get('reason') or '',
        'errors': list(value.get('errors') or [])[:4],
        'cities': len(value.get('cities') or {}),
        'fetchedAt': value.get('fetchedAt'),
    }

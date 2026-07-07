"""
Emby 保号服务 —— 模拟播放会话，保持 Emby 账号活跃。

原理（参考 Bemby 项目）：
1. 用 Emby 账号密码登录 → 获取 AccessToken + UserId
2. 从媒体库随机选一部影片/剧集
3. POST /Sessions/Playing 开始播放（带 User-Agent）
4. 每 30 秒 POST /Sessions/Playing/Progress 上报进度
5. 到达配置时长后 POST /Sessions/Playing/Stopped 停止
6. 可选：标记已看
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone as tzinfo
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("tg_assistant.emby")

# ── User-Agent 列表（按设备类型区分） ──
_IOS_USER_AGENTS = [
    "SenPlayer/6.1.2 CFNetwork/1490.0.4 Darwin/23.2.0",
    "Lenna/1.0.15 CFNetwork/1494.0.7 Darwin/23.4.0",
    "VidHub/2.2.4",
    "Fileball/1.3.26 CFNetwork/1490.0.4 Darwin/23.2.0",
]
_ANDROID_USER_AGENTS = [
    "Yamby/2.0.3.4(Android)",
    "Hills/0.2.1",
    "SenPlayer/6.1.2(Android)",
]

# ── 设备配置 ──
_DEVICE_CONFIG: dict[str, dict[str, str]] = {
    "iPhone": {"client": "SenPlayer", "version": "6.1.0", "prefix": "iPhone"},
    "Android": {"client": "Yamby", "version": "2.0.3.4", "prefix": "Android"},
}


@dataclass
class EmbyAccount:
    """Emby 账号凭据"""
    server_url: str          # https://emby.example.com
    username: str
    password: str
    user_agent: str = ""     # 空则根据 device_type 随机选取
    device_type: str = "iPhone"  # iPhone | Android


@dataclass
class EmbyWatchConfig:
    """单个 Emby 保号任务配置"""
    id: str
    name: str
    accounts: List[EmbyAccount] = field(default_factory=list)
    watch_minutes: int = 30       # 观看时长（分钟）
    mark_watched: bool = False    # 播放后标记已看
    time_range: str = "08:00-22:00"  # 执行时间窗口
    enabled: bool = True


@dataclass
class EmbyWatchResult:
    """单次播放结果"""
    account: str
    server: str
    item_name: str = ""
    duration_seconds: float = 0
    success: bool = False
    error: str = ""
    logs: list[str] = field(default_factory=list)


class EmbyClient:
    """Emby REST API 客户端"""

    def __init__(self, server_url: str, username: str, password: str,
                 user_agent: str = "", device_type: str = "iPhone"):
        self.server = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.device_type = device_type if device_type in _DEVICE_CONFIG else "iPhone"
        self._dc = _DEVICE_CONFIG[self.device_type]
        self.ua = user_agent or random.choice(
            _IOS_USER_AGENTS if self.device_type == "iPhone" else _ANDROID_USER_AGENTS
        )
        self._token: str = ""
        self._user_id: str = ""
        self._device_id: str = self._dc["prefix"]
        self._play_session_id: str = ""  # 跨 Playing/Progress/Stopped 保持一致
        self._http = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._http.aclose()

    # ── 认证 ──

    async def login(self) -> bool:
        """通过用户名密码登录"""
        try:
            # Emby 认证：POST /Users/AuthenticateByName
            resp = await self._http.post(
                f"{self.server}/Users/AuthenticateByName",
                headers={
                    "X-Emby-Authorization": self._auth_header(""),
                    "Content-Type": "application/json",
                },
                json={"Username": self.username, "Pw": self.password},
            )
            if resp.status_code != 200:
                logger.warning("Emby login failed for %s@%s: %s",
                               self.username, self.server, resp.text[:200])
                return False
            data = resp.json()
            self._token = data.get("AccessToken", "")
            self._user_id = data.get("User", {}).get("Id", "")
            return bool(self._token and self._user_id)
        except Exception as exc:
            logger.warning("Emby login error for %s@%s: %s",
                           self.username, self.server, exc)
            return False

    def _auth_header(self, token: str = "") -> str:
        t = token or self._token
        parts = [
            f'MediaBrowser Client="{self._dc["client"]}"',
            f'Device="{self._device_id}"',
            f'DeviceId="{self._device_id}"',
            f'Version="{self._dc["version"]}"',
        ]
        if t:
            parts.append(f'Token="{t}"')
        return ", ".join(parts)

    def _headers(self) -> dict:
        return {
            "X-Emby-Authorization": self._auth_header(),
            "User-Agent": self.ua,
        }

    # ── 媒体库 ──

    async def get_random_item(self) -> Optional[dict]:
        """随机选取一部影片或剧集"""
        try:
            params = {
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                "Limit": 200,
                "Fields": "MediaSources,ProviderIds",
                "IsMissing": "false",
                "IsVirtualItem": "false",
            }
            resp = await self._http.get(
                f"{self.server}/Users/{self._user_id}/Items",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code != 200:
                return None
            items = resp.json().get("Items", [])
            if not items:
                return None
            return random.choice(items)
        except Exception as exc:
            logger.warning("Emby media fetch error: %s", exc)
            return None

    # ── 播放模拟 ──

    async def start_playing(self, item_id: str, media_source_id: str = "",
                            position_ticks: int = 0) -> bool:
        """报告播放开始"""
        try:
            self._play_session_id = f"tgsp-{random.randint(100000, 999999)}"
            payload: dict = {
                "ItemId": item_id,
                "MediaSourceId": media_source_id or item_id,
                "PlaySessionId": self._play_session_id,
                "PlayMethod": "Transcode",
                "PositionTicks": position_ticks,
                "IsPaused": False,
                "IsMuted": False,
                "CanSeek": True,
                "RepeatMode": "RepeatNone",
            }

            resp = await self._http.post(
                f"{self.server}/Sessions/Playing",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Emby start playing error: %s", exc)
            return False

    async def report_progress(self, item_id: str, media_source_id: str = "",
                              position_ticks: int = 0, is_paused: bool = False) -> bool:
        """上报播放进度"""
        try:
            payload: dict = {
                "ItemId": item_id,
                "MediaSourceId": media_source_id or item_id,
                "PlaySessionId": self._play_session_id,
                "PositionTicks": position_ticks,
                "IsPaused": is_paused,
                "IsMuted": False,
                "CanSeek": True,
                "RepeatMode": "RepeatNone",
                "EventName": "timeupdate",
            }

            resp = await self._http.post(
                f"{self.server}/Sessions/Playing/Progress",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Emby progress report error: %s", exc)
            return False

    async def stop_playing(self, item_id: str, media_source_id: str = "",
                           position_ticks: int = 0) -> bool:
        """报告播放停止"""
        try:
            payload: dict = {
                "ItemId": item_id,
                "MediaSourceId": media_source_id or item_id,
                "PlaySessionId": self._play_session_id,
                "PositionTicks": position_ticks,
            }

            resp = await self._http.post(
                f"{self.server}/Sessions/Playing/Stopped",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Emby stop playing error: %s", exc)
            return False

    async def mark_played(self, item_id: str) -> bool:
        """标记为已观看"""
        try:
            resp = await self._http.post(
                f"{self.server}/Users/{self._user_id}/PlayedItems/{item_id}",
                headers=self._headers(),
            )
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Emby mark played error: %s", exc)
            return False

    # ── 完整模拟 ──

    async def simulate_watch(self, minutes: int = 30,
                             mark_watched: bool = False) -> EmbyWatchResult:
        """执行一次完整模拟播放"""
        result = EmbyWatchResult(
            account=self.username, server=self.server,
        )
        log_msgs: list[str] = []

        # 登录
        if not await self.login():
            result.error = "登录失败"
            log_msgs.append("❌ Emby 登录失败")
            result.logs = log_msgs
            return result
        log_msgs.append(f"✅ 登录成功 ({self.username}@{self.server})")
        logger.info("Emby 登录成功: %s@%s", self.username, self.server)

        # 随机选影片
        item = await self.get_random_item()
        if not item:
            result.error = "未找到可播放的媒体"
            log_msgs.append("❌ 媒体库为空")
            result.logs = log_msgs
            return result

        item_name = item.get("Name") or item.get("OriginalTitle") or item.get("Id", "?")
        item_id = item["Id"]
        media_sources = item.get("MediaSources", [])
        media_source_id = media_sources[0]["Id"] if media_sources else ""
        run_time_ticks = item.get("RunTimeTicks", 0)  # 总时长（100ns 单位）

        log_msgs.append(f"📺 选中: {item_name}")
        logger.info("Emby 选中影片: %s (id=%s)", item_name, item_id)

        # 计算播放时长
        target_seconds = minutes * 60
        # 从 5%-10% 处开始
        start_pct = random.uniform(0.05, 0.10)
        start_ticks = int(run_time_ticks * start_pct) if run_time_ticks else 0
        # 严格使用配置的播放时长，不受影片实际长度限制
        end_seconds = start_ticks / 10_000_000 + target_seconds
        end_ticks = int(end_seconds * 10_000_000)
        # 随机延长 0-15%
        extra = random.uniform(0, 0.15) * target_seconds
        end_seconds += extra
        end_ticks = int(end_seconds * 10_000_000)
        progress_interval = 30  # 每 30 秒报告进度

        result.item_name = item_name

        # 开始播放
        if not await self.start_playing(item_id, media_source_id, start_ticks):
            result.error = "开始播放失败"
            log_msgs.append("❌ 开始播放失败")
            result.logs = log_msgs
            return result
        log_msgs.append("▶ 播放开始")
        logger.info("Emby 播放开始: %s, total %ds", item_name, int(end_seconds))

        current_ticks = start_ticks
        elapsed = 0.0
        while current_ticks < end_ticks:
            await asyncio.sleep(progress_interval)
            elapsed += progress_interval
            step = progress_interval * 10_000_000
            current_ticks = min(current_ticks + step, end_ticks)
            if not await self.report_progress(item_id, media_source_id, current_ticks):
                # 单次进度失败不中断
                pass

        log_msgs.append(f"⏹ 播放停止 (实际 {elapsed:.0f}s)")
        logger.info("Emby 播放完成: %s, %ds", item_name, elapsed)

        # 停止
        await self.stop_playing(item_id, media_source_id, end_ticks)

        # 标记已看
        if mark_watched:
            await self.mark_played(item_id)
            log_msgs.append("📌 已标记为已看")
            logger.info("Emby 标记已看: %s", item_name)

        result.success = True
        result.duration_seconds = elapsed
        result.logs = log_msgs
        return result

"""
实时日志事件总线 (Real-time Log Event Bus)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 游标订阅：每个消费者有自己的 last_cursor，从上次断开处续读，不丢数据
- 环形缓冲：最多保留最近 N 条事件，防止内存泄漏
- 多频道支持：monitor_logs / keyword_heartbeat / client_status 等
- 线程安全：asyncio.Lock 保护写操作
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

MAX_EVENTS_PER_CHANNEL = 5000
CLEANUP_INTERVAL = 300  # 每 5 分钟清理一次超时消费者


@dataclass
class LogEvent:
    """单条日志事件"""
    cursor: int          # 全局递增游标
    channel: str         # 频道名: monitor_logs, heartbeat, client_status
    timestamp: float     # Unix 时间戳
    data: Dict[str, Any] # 事件内容


class LogEventBus:
    """实时日志事件总线（单例）"""

    _instance: Optional["LogEventBus"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._channels: Dict[str, List[LogEvent]] = {}      # channel → events
        self._global_cursor: int = 0                         # 全局递增游标
        self._write_lock = asyncio.Lock()
        self._subscriber_count: int = 0
        self._cleanup_task: Optional[asyncio.Task] = None

    @classmethod
    async def get_instance(cls) -> "LogEventBus":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    bus = cls()
                    bus._cleanup_task = asyncio.create_task(bus._periodic_cleanup())
                    cls._instance = bus
        return cls._instance

    async def publish(
        self,
        channel: str,
        data: Dict[str, Any],
        *,
        timestamp: Optional[float] = None,
    ) -> int:
        """
        发布一条事件到指定频道。
        返回该事件的 cursor 值。
        """
        async with self._write_lock:
            self._global_cursor += 1
            cursor = self._global_cursor
            ts = timestamp or time.time()

            event = LogEvent(
                cursor=cursor,
                channel=channel,
                timestamp=ts,
                data=data,
            )

            if channel not in self._channels:
                self._channels[channel] = []
            buf = self._channels[channel]
            buf.append(event)

            # 环形缓冲：超过上限丢弃最旧的
            if len(buf) > MAX_EVENTS_PER_CHANNEL:
                del buf[: len(buf) - MAX_EVENTS_PER_CHANNEL]

            return cursor

    async def subscribe(
        self,
        channels: List[str],
        last_cursor: int = 0,
        poll_interval: float = 0.5,
        heartbeat_interval: float = 10.0,
    ) -> AsyncGenerator[str, None]:
        """
        订阅一个或多个频道的事件流。
        从 last_cursor 之后开始推送，如果没有新事件则定期发送心跳。

        用法 (FastAPI SSE):
            async def event_generator():
                async for sse_msg in bus.subscribe(["monitor_logs", "heartbeat"]):
                    yield sse_msg
            return StreamingResponse(event_generator(), media_type="text/event-stream")
        """
        self._subscriber_count += 1
        last_heartbeat = time.time()
        try:
            # 发送 retry 字段：告诉浏览器断开后 3 秒自动重连
            # 同时解决 HTTP/2 proxy 关闭 SSE 流导致的 ERR_HTTP2_PROTOCOL_ERROR
            yield "retry: 3000\n\n"

            # 先推送自 last_cursor 之后的所有未读事件
            catchup_events = await self._get_events_since(channels, last_cursor)
            for event in catchup_events:
                yield self._format_sse(event)
                last_heartbeat = time.time()

            # 然后轮询新事件
            while True:
                new_events = await self._get_events_since(channels, last_cursor)
                for event in new_events:
                    yield self._format_sse(event)
                    last_cursor = max(last_cursor, event.cursor)
                    last_heartbeat = time.time()

                # 心跳：防止连接被代理/负载均衡器关闭
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield f": heartbeat {now}\n\n"
                    last_heartbeat = now

                await asyncio.sleep(poll_interval)
        finally:
            self._subscriber_count -= 1

    async def _get_events_since(
        self, channels: List[str], since_cursor: int
    ) -> List[LogEvent]:
        """获取指定频道中 cursor > since_cursor 的所有事件"""
        results: List[LogEvent] = []
        async with self._write_lock:
            for channel in channels:
                buf = self._channels.get(channel, [])
                for event in buf:
                    if event.cursor > since_cursor:
                        results.append(event)
        results.sort(key=lambda e: e.cursor)
        return results

    @staticmethod
    def _format_sse(event: LogEvent) -> str:
        """格式化为 SSE (Server-Sent Events) 消息"""
        payload = json.dumps(
            {
                "cursor": event.cursor,
                "channel": event.channel,
                "timestamp": event.timestamp,
                "data": event.data,
            },
            ensure_ascii=False,
        )
        return f"id: {event.cursor}\ndata: {payload}\n\n"

    async def get_channel_since(
        self, channel: str, since_cursor: int, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """同步获取频道中 cursor > since_cursor 的事件（用于轮询兼容）"""
        results: List[Dict[str, Any]] = []
        async with self._write_lock:
            buf = self._channels.get(channel, [])
            for event in buf:
                if event.cursor > since_cursor:
                    results.append({
                        "cursor": event.cursor,
                        "channel": event.channel,
                        "timestamp": event.timestamp,
                        **event.data,
                    })
        results.sort(key=lambda e: e["cursor"])
        return results[-limit:]

    async def get_latest_cursor(self, channel: str) -> int:
        """获取指定频道的最新 cursor"""
        async with self._write_lock:
            buf = self._channels.get(channel, [])
            if buf:
                return buf[-1].cursor
            return 0

    async def _periodic_cleanup(self):
        """定期清理旧事件（保留最近 MAX_EVENTS_PER_CHANNEL 条）"""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            async with self._write_lock:
                for channel, buf in list(self._channels.items()):
                    if len(buf) > MAX_EVENTS_PER_CHANNEL:
                        self._channels[channel] = buf[-MAX_EVENTS_PER_CHANNEL:]
                    # 如果频道为空且无订阅者，删除频道
                    if not buf and self._subscriber_count == 0:
                        del self._channels[channel]

    async def shutdown(self):
        """关闭事件总线"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task


import contextlib  # noqa: E402


async def get_log_event_bus() -> LogEventBus:
    """获取事件总线单例"""
    return await LogEventBus.get_instance()

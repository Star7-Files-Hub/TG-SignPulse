"""独立监听器 API - 秒转消息 / 抢红包"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

from backend.core.auth import get_current_user
from backend.core.config import get_settings
from backend.models.user import User

router = APIRouter(tags=["monitors"])
settings = get_settings()


def _monitors_file() -> Path:
    return settings.resolve_workdir() / "monitors.json"


def _load_monitors() -> list[dict]:
    f = _monitors_file()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_monitors(data: list[dict]) -> None:
    _monitors_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- Schemas ----

class MonitorIn(BaseModel):
    name: str = Field(..., description="监听器名称")
    account_names: List[str] = Field(..., description="关联账号（必选）")
    action: str = Field("forward", description="forward / red_packet_button / red_packet_keyword")
    # 转发模式
    keywords: List[str] = Field(default_factory=list, description="关键词（正则）列表")
    match_mode: str = Field("regex", description="contains / exact / regex")
    forward_chat_id: Optional[int] = Field(None, description="转发目标 Chat ID")
    forward_thread_id: Optional[int] = Field(None, description="转发目标话题 ID")
    dedup_seconds: int = Field(60, description="消息ID去重窗口秒数")
    fuzzy_threshold: float = Field(0.85, description="模糊匹配阈值（0-1，0=关闭模糊去重）")
    fuzzy_cooldown_minutes: int = Field(5, description="模糊匹配冷却时间（分钟）")
    smart_dedup: bool = Field(False, description="智能去重：提取数值比对，数值不变不转发")
    forward_with_button: bool = Field(False, description="转发时附带原消息按钮")
    smart_dedup_pattern: Optional[str] = Field(None, description="智能去重提取正则（默认提取所有数字）")
    # 红包模式 - 监听群组
    chat_ids: List[int] = Field(default_factory=list, description="红包监听群组 Chat ID")
    button_names: List[str] = Field(default_factory=list, description="按钮名列表（空=任意按钮）")
    extract_pattern: Optional[str] = Field(None, description="提取数字正则")
    grab_text_template: str = Field("/grab {number}")
    red_packet_delay: float = Field(0, description="抢红包延迟秒数")
    auto_reply_list: List[str] = Field(default_factory=list)
    auto_reply_delay: float = Field(0, description="回复延迟秒数")
    enabled: bool = Field(True)

    @validator("account_names")
    @classmethod
    def account_names_not_empty(cls, v):
        if not v:
            raise ValueError("至少选择一个关联账号")
        return v


class MonitorOut(MonitorIn):
    id: str


class MonitorUpdate(BaseModel):
    name: Optional[str] = None
    account_names: Optional[List[str]] = None
    action: Optional[str] = None
    keywords: Optional[List[str]] = None
    match_mode: Optional[str] = None
    forward_chat_id: Optional[int] = None
    forward_thread_id: Optional[int] = None
    dedup_seconds: Optional[int] = None
    fuzzy_threshold: Optional[float] = None
    fuzzy_cooldown_minutes: Optional[int] = None
    smart_dedup: Optional[bool] = None
    forward_with_button: Optional[bool] = None
    smart_dedup_pattern: Optional[str] = None
    chat_ids: Optional[List[int]] = None
    button_names: Optional[List[str]] = None
    extract_pattern: Optional[str] = None
    grab_text_template: Optional[str] = None
    red_packet_delay: Optional[float] = None
    auto_reply_list: Optional[List[str]] = None
    auto_reply_delay: Optional[float] = None
    enabled: Optional[bool] = None


# ---- Routes ----

@router.get("", response_model=List[MonitorOut])
def list_monitors(current_user: User = Depends(get_current_user)):
    return _load_monitors()


@router.post("", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    payload: MonitorIn,
    current_user: User = Depends(get_current_user),
):
    monitors = _load_monitors()
    new_id = uuid.uuid4().hex[:8]
    entry = payload.dict()
    entry["id"] = new_id
    monitors.append(entry)
    _save_monitors(monitors)

    import asyncio
    from backend.services.keyword_monitor import get_keyword_monitor_service
    asyncio.ensure_future(get_keyword_monitor_service().restart_from_tasks())

    return entry


@router.put("/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    monitor_id: str,
    payload: MonitorUpdate,
    current_user: User = Depends(get_current_user),
):
    monitors = _load_monitors()
    for m in monitors:
        if m.get("id") == monitor_id:
            update_data = payload.dict(exclude_none=True)
            m.update(update_data)
            _save_monitors(monitors)

            import asyncio
            from backend.services.keyword_monitor import get_keyword_monitor_service
            asyncio.ensure_future(get_keyword_monitor_service().restart_from_tasks())
            return m
    raise HTTPException(status_code=404, detail="监听器不存在")


@router.delete("/{monitor_id}", status_code=status.HTTP_200_OK)
async def delete_monitor(
    monitor_id: str,
    current_user: User = Depends(get_current_user),
):
    monitors = _load_monitors()
    new_list = [m for m in monitors if m.get("id") != monitor_id]
    if len(new_list) == len(monitors):
        raise HTTPException(status_code=404, detail="监听器不存在")
    _save_monitors(new_list)

    import asyncio
    from backend.services.keyword_monitor import get_keyword_monitor_service
    asyncio.ensure_future(get_keyword_monitor_service().restart_from_tasks())
    return {"ok": True}


class MonitorLogEntry(BaseModel):
    time: str = ""
    monitor_id: str = ""
    monitor_name: str = ""
    event_type: str = "info"  # info / match / forward / red_packet / error
    message: str = ""
    chat_title: str = ""
    msg_preview: str = ""


@router.get("/logs", response_model=List[MonitorLogEntry])
def get_monitor_logs(
    limit: int = 200,
    offset: int = 0,
    since: str = "",
    current_user: User = Depends(get_current_user),
):
    """获取监听器日志（支持分页 + since 实时轮询）"""
    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        svc = get_keyword_monitor_service()
        monitors = {m["id"]: m.get("name", m["id"]) for m in _load_monitors()}
        logs: list[dict] = []

        # 优先使用结构化日志
        for monitor_id, entries in svc._monitor_logs.items():
            mname = monitors.get(monitor_id, monitor_id)
            for entry in entries:
                if since and entry.get("time", "") <= since:
                    continue
                msg = entry.get("message", "")
                etype = "info"
                if "✅" in msg or "命中" in msg:
                    etype = "match"
                if "转发" in msg:
                    etype = "forward"
                if "红包" in msg:
                    etype = "red_packet"
                if "失败" in msg or "拦截" in msg:
                    etype = "error"
                logs.append({
                    "time": entry.get("time", ""),
                    "monitor_id": monitor_id,
                    "monitor_name": mname,
                    "event_type": etype,
                    "message": msg[:200],
                    "chat_title": entry.get("chat_title", ""),
                    "msg_preview": entry.get("msg_preview", ""),
                })

        # 回退到旧格式字符串日志
        if not logs and not since:
            for (account_name, task_name), entries in svc._task_logs.items():
                if not isinstance(task_name, str) or not task_name.startswith("monitor:"):
                    continue
                monitor_id = task_name.replace("monitor:", "", 1)
                mname = monitors.get(monitor_id, monitor_id)
                for line in entries:
                    line_str = str(line)
                    time_str = line_str[:19] if len(line_str) >= 19 else ""
                    msg = line_str[22:] if len(line_str) > 22 else line_str
                    etype = "info"
                    if "命中" in msg or "✅" in msg:
                        etype = "match"
                    if "转发" in msg:
                        etype = "forward"
                    if "红包" in msg:
                        etype = "red_packet"
                    if "失败" in msg or "拦截" in msg:
                        etype = "error"
                    logs.append({
                        "time": time_str,
                        "monitor_id": monitor_id,
                        "monitor_name": mname,
                        "event_type": etype,
                        "message": msg[:200],
                        "chat_title": "",
                        "msg_preview": "",
                    })

        logs.sort(key=lambda x: x.get("time", ""), reverse=True)
        return logs[offset:offset + limit]
    except Exception:
        return []


@router.get("/status")
def get_monitor_status(current_user: User = Depends(get_current_user)):
    """返回关键词监控服务的内部诊断状态"""
    from backend.services.keyword_monitor import get_keyword_monitor_service

    svc = get_keyword_monitor_service()
    return {
        "rules_count": len(svc._rules),
        "handler_count": len(svc._handler_refs),
        "active_key": svc._active_key[:80] if svc._active_key else "",
        "has_heartbeat": svc._heartbeat_task is not None,
        "msg_received": dict(svc._msg_received),
        "last_msg_time": {k: v for k, v in svc._last_msg_time.items()},
        "accounts": list(set(
            account_name for account_name, _, _ in svc._handler_refs
        )),
        "rule_accounts": list(set(
            rule.account_name for rule in svc._rules
        )),
        "rule_chat_ids": list(set(
            rule.chat_id for rule in svc._rules
        )),
        "rule_push_channels": list(set(
            str(rule.action.get("push_channel", "telegram"))
            for rule in svc._rules
        )),
    }


# ────────────────────────────────────────────────────
# SSE 实时日志流 (Server-Sent Events)
# ────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
from fastapi import Query
from starlette.responses import Response  # noqa: E402


async def _auth_sse_user(
    token: str = Query("", description="JWT token for SSE (EventSource doesn't support headers)"),
) -> User:
    """SSE 专用认证：EventSource 不支持自定义 Header，故通过 query 传 token"""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token query parameter")

    try:
        from jose import jwt as jose_jwt
        from backend.core.config import get_settings
        settings = get_settings()
        payload = jose_jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    from backend.core.database import get_session_local
    session_local = get_session_local()
    db = session_local()
    try:
        # FastAPI admin bootstrap uses string user_id "admin", which maps to username field
        from backend.models.user import User
        from sqlalchemy.orm import Session
        user = None
        # Try as integer id first, then as username
        try:
            uid = int(user_id)
            user = db.query(User).filter(User.id == uid).first()
        except (ValueError, TypeError):
            user = db.query(User).filter(User.username == str(user_id)).first()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    finally:
        db.close()


@router.get("/stream")
async def monitor_event_stream(
    last_cursor: int = 0,
    channels: str = "monitor_logs,heartbeat,service_status,diagnostic",
    current_user: User = Depends(_auth_sse_user),
):
    """
    实时日志流 SSE 端点。
    - last_cursor: 从该游标之后开始推送（0 = 推送所有历史 + 实时）
    - channels: 逗号分隔的频道列表
    - token: JWT Token（EventSource 通过 query string 传认证信息）
    前端通过 EventSource 连接到此端点获得实时日志推送。
    """
    from backend.services.log_event_bus import get_log_event_bus

    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    bus = await get_log_event_bus()

    async def event_generator():
        try:
            async for sse_msg in bus.subscribe(channel_list, last_cursor=last_cursor):
                yield sse_msg
        except asyncio.CancelledError:
            pass  # 客户端正常断开
        except GeneratorExit:
            pass  # StreamingResponse 关闭生成器（HTTP/2 proxy 关闭流时触发）
        except Exception:
            pass  # 其他错误静默退出，前端会自动重连

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",       # 禁用 nginx 缓冲
            "X-Content-Type-Options": "nosniff",
        },
    )


import asyncio  # noqa: E402

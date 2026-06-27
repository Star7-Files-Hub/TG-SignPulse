"""
Emby 保号任务 CRUD API
存储格式：{workdir}/emby_tasks.json
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.core.config import get_settings
from backend.models.user import User
from backend.services.emby_watch import EmbyClient

router = APIRouter(tags=["emby"])
settings = get_settings()


def _tasks_file() -> Path:
    return settings.resolve_workdir() / "emby_tasks.json"


def _load() -> list[dict]:
    f = _tasks_file()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(data: list[dict]) -> None:
    _tasks_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Schemas ──

class EmbyAccountIn(BaseModel):
    server_url: str = Field(..., description="Emby 服务器地址，如 https://emby.example.com")
    username: str = Field(...)
    password: str = Field(...)
    user_agent: str = Field("", description="空则随机选取")


class EmbyTaskIn(BaseModel):
    name: str = Field(..., description="任务名称")
    accounts: List[EmbyAccountIn] = Field(...)
    watch_minutes: int = Field(30, description="观看时长（分钟）")
    mark_watched: bool = Field(False, description="播放后标记已看")
    time_range: str = Field("08:00-22:00", description="执行时间窗口")
    enabled: bool = Field(True)


class EmbyTaskOut(BaseModel):
    id: str
    name: str
    accounts: List[EmbyAccountIn]
    watch_minutes: int = 30
    mark_watched: bool = False
    time_range: str = "08:00-22:00"
    enabled: bool = True
    last_run: Optional[str] = None
    last_result: Optional[str] = None


class EmbyTaskUpdate(BaseModel):
    name: Optional[str] = None
    accounts: Optional[List[EmbyAccountIn]] = None
    watch_minutes: Optional[int] = None
    mark_watched: Optional[bool] = None
    time_range: Optional[str] = None
    enabled: Optional[bool] = None


class EmbyWatchLogEntry(BaseModel):
    time: str = ""
    task_id: str = ""
    task_name: str = ""
    account: str = ""
    server: str = ""
    item: str = ""
    duration: float = 0
    success: bool = False
    error: str = ""


# ── 日志缓存 ──
_watch_logs: list[dict] = []


def _add_watch_log(task_id: str, task_name: str, account: str, server: str,
                   item: str, duration: float, success: bool, error: str) -> None:
    from datetime import datetime, timezone as tzinfo
    _watch_logs.append({
        "time": datetime.now(tzinfo.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": task_id,
        "task_name": task_name,
        "account": account,
        "server": server,
        "item": item,
        "duration": duration,
        "success": success,
        "error": error,
    })
    if len(_watch_logs) > 500:
        del _watch_logs[:-500]


# ── CRUD ──

@router.get("", response_model=List[EmbyTaskOut])
def list_emby_tasks(current_user: User = Depends(get_current_user)):
    return _load()


@router.post("", response_model=EmbyTaskOut, status_code=201)
async def create_emby_task(payload: EmbyTaskIn, current_user: User = Depends(get_current_user)):
    tasks = _load()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "name": payload.name,
        "accounts": [a.dict() for a in payload.accounts],
        "watch_minutes": payload.watch_minutes,
        "mark_watched": payload.mark_watched,
        "time_range": payload.time_range,
        "enabled": payload.enabled,
        "last_run": None,
        "last_result": None,
    }
    tasks.append(entry)
    _save(tasks)
    await _reschedule()
    return entry


@router.put("/{task_id}", response_model=EmbyTaskOut)
async def update_emby_task(task_id: str, payload: EmbyTaskUpdate,
                     current_user: User = Depends(get_current_user)):
    tasks = _load()
    for t in tasks:
        if t["id"] == task_id:
            if payload.name is not None:
                t["name"] = payload.name
            if payload.accounts is not None:
                t["accounts"] = [a.dict() for a in payload.accounts]
            if payload.watch_minutes is not None:
                t["watch_minutes"] = payload.watch_minutes
            if payload.mark_watched is not None:
                t["mark_watched"] = payload.mark_watched
            if payload.time_range is not None:
                t["time_range"] = payload.time_range
            if payload.enabled is not None:
                t["enabled"] = payload.enabled
            _save(tasks)
            await _reschedule()
            return t
    raise HTTPException(status_code=404, detail="任务不存在")


@router.delete("/{task_id}")
async def delete_emby_task(task_id: str, current_user: User = Depends(get_current_user)):
    tasks = _load()
    new_list = [t for t in tasks if t["id"] != task_id]
    if len(new_list) == len(tasks):
        raise HTTPException(status_code=404, detail="任务不存在")
    _save(new_list)
    await _reschedule()
    return {"ok": True}


@router.post("/{task_id}/run")
async def run_emby_task_now(task_id: str, current_user: User = Depends(get_current_user)):
    """立即执行一次（后台执行，不阻塞，避免 Cloudflare 超时）"""
    tasks = _load()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 标记为执行中
    for t in tasks:
        if t["id"] == task["id"]:
            from datetime import datetime, timezone as tzinfo
            t["last_run"] = datetime.now(tzinfo.utc).strftime("%Y-%m-%d %H:%M:%S")
            t["last_result"] = "⏳ 执行中..."
    _save(tasks)
    import asyncio
    asyncio.create_task(_execute_task(copy.deepcopy(task)))
    return {"ok": True, "message": "已加入执行队列，完成后自动更新状态"}


@router.get("/logs", response_model=List[EmbyWatchLogEntry])
def get_emby_logs(limit: int = 100, current_user: User = Depends(get_current_user)):
    logs = sorted(_watch_logs, key=lambda x: x.get("time", ""), reverse=True)
    return logs[:limit]


# ── 执行引擎 ──

async def _execute_task(task: dict) -> None:
    """执行单个 Emby 保号任务"""
    import logging
    log = logging.getLogger("tg_signpulse.emby")

    def _update_status(result_text: str) -> None:
        try:
            tasks = _load()
            for t in tasks:
                if t["id"] == task["id"]:
                    from datetime import datetime, timezone as tzinfo
                    t["last_run"] = datetime.now(tzinfo.utc).strftime("%Y-%m-%d %H:%M:%S")
                    t["last_result"] = result_text
            _save(tasks)
        except Exception:
            pass

    try:
        from backend.services.emby_watch import EmbyClient
    except Exception as exc:
        log.error("Emby execute_task import failed: %s", exc)
        _update_status(f"❌ {exc}")
        return

    task_name = task.get("name", task["id"])
    accounts = task.get("accounts", [])
    minutes = task.get("watch_minutes", 30)
    mark = task.get("mark_watched", False)
    results: list[str] = []

    for acc in accounts:
        server = acc["server_url"]
        username = acc["username"]
        password = acc["password"]
        ua = acc.get("user_agent", "")

        client = EmbyClient(server, username, password, ua)
        try:
            result = await client.simulate_watch(minutes=minutes, mark_watched=mark)
            _add_watch_log(
                task_id=task["id"], task_name=task_name,
                account=username, server=server,
                item=result.item_name, duration=result.duration_seconds,
                success=result.success, error=result.error,
            )
            results.append("✅" if result.success else f"❌ {result.error}")
        except Exception as exc:
            _add_watch_log(
                task_id=task["id"], task_name=task_name,
                account=username, server=server,
                item="", duration=0,
                success=False, error=str(exc),
            )
            results.append(f"❌ {exc}")
        finally:
            await client.close()

    success_count = sum(1 for r in results if r.startswith("✅"))
    _update_status(f"✅ {success_count}/{len(results)}" if success_count == len(results) else f"❌ {success_count}/{len(results)}")


async def _reschedule() -> None:
    """重新调度所有 Emby 保号任务"""
    try:
        from backend.scheduler import schedule_emby_jobs
        await schedule_emby_jobs()
    except Exception:
        pass

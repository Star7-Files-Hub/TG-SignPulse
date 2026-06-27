"""
会话自动恢复工具
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
被 telegram.py 的 check_account_status 调用，
当检测到 AUTH_KEY_UNREGISTERED 时：
1. 关闭所有缓存客户端
2. 从 .session 文件重新导出 session_string（读取最新 key）
3. 用最新的 session_string 创建独立客户端做验证
4. 都失败则删除旧 session + 输出手动登录提示
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("backend.session_recovery")

# 全局计数器，防止同一账号短时间内反复触发恢复
_RECOVERY_ATTEMPTS: Dict[str, int] = {}
_MAX_RECOVERY_PER_HOUR = 3


async def recover_session(
    account_name: str,
    session_dir: Path,
    proxy_dict: Optional[dict] = None,
    timeout_seconds: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """
    尝试恢复账号会话。

    Returns:
        恢复成功则返回 {"ok": True, "user_id": ...}
        恢复失败则返回 {"ok": False, "message": "...", "needs_relogin": True}
        None 表示不需要处理
    """
    now = __import__("time").time()
    key = account_name

    # ── 频率限制：同一账号每小时最多恢复 3 次 ──
    if key in _RECOVERY_ATTEMPTS:
        attempts = _RECOVERY_ATTEMPTS[key]
        # 清理超过 1 小时的旧记录
        if isinstance(attempts, tuple):
            count, first_ts = attempts
            if now - first_ts > 3600:
                _RECOVERY_ATTEMPTS[key] = (1, now)
            elif count >= _MAX_RECOVERY_PER_HOUR:
                logger.error(
                    "Session recovery rate-limited for %s (%s attempts/hour), "
                    "skipping auto-recovery to avoid infinite loop",
                    account_name, count,
                )
                return {
                    "ok": False,
                    "message": (
                        f"会话恢复触发过于频繁（{_MAX_RECOVERY_PER_HOUR} 次/小时），"
                        f"已跳过自动恢复。请手动重新登录账号 {account_name}。"
                    ),
                    "needs_relogin": True,
                    "rate_limited": True,
                }
            else:
                _RECOVERY_ATTEMPTS[key] = (count + 1, first_ts)
        else:
            _RECOVERY_ATTEMPTS[key] = (1, now)
    else:
        _RECOVERY_ATTEMPTS[key] = (1, now)

    # ── 获取 API credentials ──
    try:
        from backend.services.config import get_config_service
        tg_cfg = get_config_service().get_telegram_config()
        api_id = int(os.getenv("TG_API_ID") or tg_cfg.get("api_id") or 0)
        api_hash = os.getenv("TG_API_HASH") or tg_cfg.get("api_hash") or ""
        if not api_id or not api_hash:
            return {
                "ok": False,
                "message": "未配置 Telegram API ID / API Hash，无法恢复会话",
                "needs_relogin": True,
            }
    except Exception as exc:
        logger.error("Failed to load API config for recovery: %s", exc)
        return None

    # ── Step 1: 关闭所有缓存客户端 ──
    try:
        from tg_signer.core import close_client_by_name
        await close_client_by_name(account_name, workdir=session_dir)
        logger.info("Step 1: closed cached clients for %s", account_name)
    except Exception as exc:
        logger.warning("Step 1 failed (non-fatal): %s", exc)

    # ── Step 2: 从 .session 文件重新导出 session_string ──
    fresh_session_string: Optional[str] = None
    session_file = session_dir / f"{account_name}.session"

    if session_file.exists():
        try:
            from pyrogram import Client as _PyroClient
            tmp = _PyroClient(
                name=str(session_dir / account_name),
                api_id=api_id,
                api_hash=api_hash,
                proxy=proxy_dict,
                in_memory=False,
                no_updates=True,
            )
            async with tmp:
                fresh_session_string = await tmp.export_session_string()
            if fresh_session_string:
                logger.info(
                    "Step 2: exported fresh session_string (%s chars) from .session for %s",
                    len(fresh_session_string), account_name,
                )
                # 保存为 .session_string 文件 + 内存
                from backend.utils.tg_session import (
                    save_session_string_file,
                    set_account_session_string,
                )
                set_account_session_string(account_name, fresh_session_string)
                save_session_string_file(session_dir, account_name, fresh_session_string)
        except Exception as exc:
            logger.warning(
                "Step 2: failed to export session_string from .session for %s: %s",
                account_name, exc,
            )

    # ── Step 3: 用 session_string 创建独立客户端验证 ──
    if not fresh_session_string:
        # fallback: 尝试加载已有的 .session_string 文件
        try:
            from backend.utils.tg_session import load_session_string_file
            fresh_session_string = load_session_string_file(session_dir, account_name)
        except Exception:
            pass

    if fresh_session_string:
        try:
            from pyrogram import Client as _PyroClient
            from backend.utils.account_locks import get_account_lock

            verify_client = _PyroClient(
                name=f"{account_name}_recovery",
                api_id=api_id,
                api_hash=api_hash,
                proxy=proxy_dict,
                in_memory=True,
                session_string=fresh_session_string,
                no_updates=True,
            )
            lock = get_account_lock(account_name)
            async with lock:
                async with verify_client:
                    me = await asyncio.wait_for(
                        verify_client.get_me(), timeout=timeout_seconds
                    )
            from backend.utils.tg_session import set_account_status
            set_account_status(
                account_name,
                status="connected",
                message="会话恢复成功",
                code="OK",
                needs_relogin=False,
            )
            logger.info(
                "Step 3: session recovery succeeded for %s (user_id=%s)",
                account_name, getattr(me, "id", "?"),
            )
            # 重置计数器（恢复成功）
            _RECOVERY_ATTEMPTS[key] = (0, now)
            return {
                "ok": True,
                "status": "connected",
                "message": "会话已自动恢复",
                "code": "OK",
                "needs_relogin": False,
                "user_id": getattr(me, "id", None),
            }
        except Exception as exc:
            logger.warning(
                "Step 3: session verification failed for %s (fresh session_string): %s",
                account_name, exc,
            )

    # ── Step 4: 彻底失败，清理旧文件 + 日志提示 ──
    logger.error(
        "FATAL: session recovery exhausted for %s. "
        "Deleting .session and .session_string files. "
        "Manual re-login required.",
        account_name,
    )
    _cleanup_session_files(session_dir, account_name)

    from backend.utils.tg_session import set_account_status, delete_account_session_string
    try:
        delete_account_session_string(account_name)
    except Exception:
        pass
    set_account_status(
        account_name,
        status="invalid",
        message="会话恢复失败，请重新登录",
        code="ACCOUNT_SESSION_INVALID",
        needs_relogin=True,
    )

    return {
        "ok": False,
        "status": "invalid",
        "message": (
            f"账号 {account_name} 会话已失效且无法自动恢复。"
            f"请前往「账号管理」页面重新登录。"
        ),
        "code": "ACCOUNT_SESSION_INVALID",
        "needs_relogin": True,
    }


def _cleanup_session_files(session_dir: Path, account_name: str) -> None:
    """删除所有 .session 相关的文件"""
    for suffix in ("", "-journal", "-wal", "-shm", "_string"):
        f = session_dir / f"{account_name}.session{suffix}"
        if f.exists():
            try:
                f.unlink()
                logger.info("Deleted %s", f)
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", f, exc)

from __future__ import annotations

import asyncio
import difflib
import hashlib
import logging
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

from backend.core.config import get_settings
from backend.services.push_notifications import send_keyword_push
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_account_proxy,
    get_account_session_string,
    get_session_mode,
    load_session_string_file,
)

logger = logging.getLogger("backend.keyword_monitor")
settings = get_settings()
_PYROGRAM_IMPORT_ERROR: Exception | None = None

try:
    from pyrogram import errors, filters
    from pyrogram.handlers import MessageHandler
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
except Exception as exc:  # pragma: no cover - fallback for unsupported runtimes
    _PYROGRAM_IMPORT_ERROR = exc

    class _RPCError(Exception):
        pass

    class _FloodWait(_RPCError):
        def __init__(self, *args, value: int = 0, **kwargs):
            super().__init__(*args)
            self.value = value

    errors = SimpleNamespace(FloodWait=_FloodWait)

    class _FilterExpr:
        def __and__(self, other):
            return self

        def __or__(self, other):
            return self

    filters = SimpleNamespace(
        text=_FilterExpr(),
        caption=_FilterExpr(),
        chat=lambda *args, **kwargs: _FilterExpr(),
    )

    class MessageHandler:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Telegram runtime dependencies are unavailable. "
                "Use Python 3.10-3.13 with a compatible pyrogram/kurigram install."
            ) from _PYROGRAM_IMPORT_ERROR

    class InlineKeyboardButton:  # type: ignore[no-redef]
        text = ""
        url = None
        callback_data = None

    class InlineKeyboardMarkup:  # type: ignore[no-redef]
        inline_keyboard = ()

    class ReplyKeyboardMarkup:  # type: ignore[no-redef]
        keyboard = ()

    class Message:  # type: ignore[no-redef]
        pass

DEFAULT_CONTINUE_TIMEOUT = 25
DEFAULT_HISTORY_LIMIT = 10


def _is_callback_data_invalid(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "data_invalid" in text or "encrypted data is invalid" in text


@dataclass(frozen=True)
class KeywordMonitorRule:
    account_name: str
    task_name: str
    chat_id: int
    chat_name: str
    message_thread_id: Optional[int]
    action: Dict[str, Any]


def _parse_keywords(value: Any, *, split_commas: bool = True) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    elif split_commas:
        raw_items = re.split(r"[\n,]+", str(value or ""))
    else:
        raw_items = str(value or "").splitlines()
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _keyword_split_commas(action: Dict[str, Any]) -> bool:
    return (action.get("match_mode") or "contains").strip() != "regex"


def _regex_keyword_value(match: re.Match[str]) -> str:
    for group in match.groups():
        if group is not None:
            value = str(group).strip()
            if value:
                return value
    return match.group(0).strip()


def _is_immediate_continue_action(action: Optional[Dict[str, Any]]) -> bool:
    if not action:
        return False
    try:
        return int(action.get("action")) in {1, 2}
    except (TypeError, ValueError):
        return False


def _message_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _message_url(message: Message) -> str:
    link = getattr(message, "link", None)
    if isinstance(link, str) and link:
        return link

    username = getattr(message.chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message.id}"

    chat_id = getattr(message.chat, "id", None)
    if isinstance(chat_id, int):
        chat_id_text = str(chat_id)
        if chat_id_text.startswith("-100"):
            return f"https://t.me/c/{chat_id_text[4:]}/{message.id}"
    return ""


def _as_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_forward_chat_id(value: Any) -> Optional[Union[int, str]]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@"):
        return text
    try:
        return int(text)
    except ValueError:
        return text


_TEMPLATE_PATTERN = re.compile(r"(?:\$\{|\{)([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


def _read_positive_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def _resolve_action_delay(action: Dict[str, Any], fallback_delay: float = 0.0) -> float:
    raw_delay = action.get("delay")
    if raw_delay is None:
        return max(float(fallback_delay or 0.0), 0.0)

    delay_text = str(raw_delay).strip()
    if not delay_text:
        return max(float(fallback_delay or 0.0), 0.0)

    try:
        if "-" in delay_text:
            start_text, end_text = delay_text.split("-", 1)
            start = float(start_text)
            end = float(end_text)
            if end < start:
                start, end = end, start
            return max(random.uniform(start, end), 0.0)
        return max(float(delay_text), 0.0)
    except (TypeError, ValueError):
        return max(float(fallback_delay or 0.0), 0.0)


def _render_template(value: Any, variables: Dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1), "")

    return _TEMPLATE_PATTERN.sub(replace, value)


def _render_action_templates(action: Dict[str, Any], variables: Dict[str, str]) -> Dict[str, Any]:
    rendered: Dict[str, Any] = {}
    for key, value in action.items():
        if isinstance(value, str):
            rendered[key] = _render_template(value, variables)
        elif isinstance(value, list):
            rendered[key] = [
                _render_template(item, variables) if isinstance(item, str) else item
                for item in value
            ]
        else:
            rendered[key] = value
    return rendered


def _clean_text_for_match(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return "".join(
        ch
        for ch in normalized.lower()
        if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
    )


def _button_text_matches(target_text: str, button_text: str) -> bool:
    if not target_text or not button_text:
        return False
    if target_text == button_text or target_text in button_text:
        return True
    return len(button_text) >= 2 and button_text in target_text


def _message_matches_thread(message: Message, message_thread_id: Optional[int]) -> bool:
    if message_thread_id is None:
        return True
    return message_thread_id in _message_thread_candidates(message)


def _message_thread_candidates(message: Message) -> list[int]:
    candidates: list[int] = []
    for raw_value in (
        getattr(message, "message_thread_id", None),
        getattr(message, "direct_messages_chat_topic_id", None),
        getattr(message, "reply_to_top_message_id", None),
        getattr(message, "reply_to_message_id", None),
        getattr(getattr(message, "topic", None), "id", None),
    ):
        value = _as_int_or_none(raw_value)
        if value is None or value in candidates:
            continue
        candidates.append(value)
    return candidates


def _reply_markup_marker(reply_markup: Any) -> Any:
    if isinstance(reply_markup, InlineKeyboardMarkup):
        return (
            "inline",
            tuple(
                tuple(getattr(button, "text", "") for button in row)
                for row in reply_markup.inline_keyboard
            ),
        )
    if isinstance(reply_markup, ReplyKeyboardMarkup):
        return (
            "reply",
            tuple(
                tuple(
                    button if isinstance(button, str) else getattr(button, "text", "")
                    for button in row
                )
                for row in reply_markup.keyboard
            ),
        )
    return None


def _describe_reply_markup(reply_markup: Any) -> str:
    """生成 reply_markup 的人类可读描述（用于日志）"""
    if reply_markup is None:
        return ""
    if isinstance(reply_markup, InlineKeyboardMarkup):
        btn_count = sum(len(row) for row in reply_markup.inline_keyboard)
        return f"{btn_count} 个内联按钮"
    if isinstance(reply_markup, ReplyKeyboardMarkup):
        btn_count = sum(len(row) for row in reply_markup.keyboard)
        return f"{btn_count} 个回复按钮"
    return "按钮"


def _message_state_marker(message: Message) -> tuple[Any, ...]:
    return (
        getattr(message, "id", None),
        getattr(message, "text", None),
        getattr(message, "caption", None),
        getattr(message, "edit_date", None),
        _reply_markup_marker(getattr(message, "reply_markup", None)),
    )


def _messages_state(messages: list[Message]) -> dict[int, tuple[Any, ...]]:
    return {
        message.id: _message_state_marker(message)
        for message in messages
        if message is not None
    }


def _message_has_button_text(message: Message, text: str) -> bool:
    target_text = _clean_text_for_match(text)
    if not target_text:
        return False

    reply_markup = getattr(message, "reply_markup", None)
    if isinstance(reply_markup, InlineKeyboardMarkup):
        rows = reply_markup.inline_keyboard
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        rows = reply_markup.keyboard
    else:
        return False

    for row in rows:
        for button in row:
            button_text = button if isinstance(button, str) else getattr(button, "text", "")
            if not button_text:
                continue
            if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                return True
    return False


def _collect_clickable_buttons(message: Message) -> list[tuple[str, Any, str]]:
    reply_markup = getattr(message, "reply_markup", None)
    clickable_buttons: list[tuple[str, Any, str]] = []
    if isinstance(reply_markup, InlineKeyboardMarkup):
        for row in reply_markup.inline_keyboard:
            for button in row:
                button_text = getattr(button, "text", "")
                if button_text:
                    clickable_buttons.append(("inline", button, button_text))
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        for row in reply_markup.keyboard:
            for button in row:
                button_text = button if isinstance(button, str) else getattr(button, "text", "")
                if button_text:
                    clickable_buttons.append(("reply", button, button_text))
    return clickable_buttons


def _message_supports_continue_action(message: Message, action: Dict[str, Any]) -> bool:
    try:
        action_id = int(action.get("action"))
    except (TypeError, ValueError):
        return False

    reply_markup = getattr(message, "reply_markup", None)
    if action_id == 3:
        return _message_has_button_text(message, str(action.get("text") or ""))
    if action_id == 4:
        return bool(message.photo and _collect_clickable_buttons(message))
    if action_id == 5:
        return bool(message.text or message.caption)
    if action_id == 6:
        return bool(message.photo)
    if action_id == 7:
        return bool((message.text or message.caption) and reply_markup)
    return False


def _message_has_terminal_success_text(message: Message) -> bool:
    text = "\n".join(
        item
        for item in [
            getattr(message, "text", None),
            getattr(message, "caption", None),
        ]
        if item
    ).lower()
    if not text.strip():
        return False
    failure_markers = (
        "失败",
        "错误",
        "异常",
        "未成功",
        "无法",
        "failed",
        "failure",
        "error",
        "invalid",
    )
    if any(marker in text for marker in failure_markers):
        return False
    success_markers = (
        "签到成功",
        "已签到",
        "成功",
        "完成",
        "success",
        "successful",
        "done",
        "completed",
    )
    return any(marker in text for marker in success_markers)


class KeywordMonitorService:
    def __init__(self) -> None:
        self._handler_refs: list[tuple[str, Any, Any]] = []
        self._rules: list[KeywordMonitorRule] = []
        self._active_key = ""
        self._lock = asyncio.Lock()
        self._task_logs: dict[tuple[str, str], list[str]] = {}
        self._task_status: dict[tuple[str, str], dict[str, Any]] = {}
        self._skip_log_times: dict[tuple[str, str, str], float] = {}
        self._ai_tools: Optional[Any] = None
        self._forwarded_cache: dict[str, float] = {}  # 消息ID去重: dedup_key -> timestamp
        self._last_forwarded_text: dict[str, str] = {}  # 完全匹配去重: monitor_id -> last_text
        self._fuzzy_dedup_cache: dict[str, list[tuple[str, float]]] = {}  # 模糊去重: monitor_id -> [(hash, time)]
        self._smart_dedup_last: dict[str, str] = {}  # 智能去重: monitor_id -> last_numbers_signature
        self._monitor_logs: dict[str, list[dict]] = {}  # 结构化日志: monitor_id -> [{time, message, chat_title, msg_preview}]
        self._ai_cfg_signature: Optional[tuple[str, str, str]] = None
        # ── 实时日志事件总线集成 ──
        self._msg_received: dict[str, int] = {}       # account_name → 消息接收计数
        self._last_msg_time: dict[str, float] = {}    # account_name → 最后收到消息的时间
        self._last_heartbeat_time: float = 0.0
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def _ensure_client_ready(self, client: Any) -> None:
        if getattr(client, "is_connected", False):
            if not getattr(client, "is_initialized", False):
                try:
                    await client.initialize()
                except ConnectionError as exc:
                    if "already initialized" not in str(exc).lower():
                        raise
            return

        is_authorized = await client.connect()
        if not is_authorized:
            raise ConnectionError("Session invalid: unauthorized")

        try:
            await client.get_me()
        except Exception as exc:
            raise ConnectionError(f"Session invalid: {exc}") from exc

        if not getattr(client, "is_initialized", False):
            try:
                await client.initialize()
            except ConnectionError as exc:
                if "already initialized" not in str(exc).lower():
                    raise

    async def _call_client_with_retry(
        self,
        client: Any,
        callback,
        *,
        operation: str,
        max_retries: int = 4,
    ):
        for attempt in range(1, max_retries + 1):
            try:
                return await callback()
            except errors.FloodWait as exc:
                wait_seconds = max(int(getattr(exc, "value", 1) or 1), 1)
                logger.warning(
                    "%s hit FloodWait, retrying in %ss (%s/%s)",
                    operation,
                    wait_seconds,
                    attempt,
                    max_retries,
                )
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
                backoff = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "%s transient failure, retrying in %ss (%s/%s): %s: %s",
                    operation,
                    backoff,
                    attempt,
                    max_retries,
                    type(exc).__name__,
                    exc,
                )
                if attempt >= max_retries:
                    raise
                try:
                    await self._ensure_client_ready(client)
                except Exception as reconnect_exc:
                    logger.warning(
                        "%s reconnect failed: %s: %s",
                        operation,
                        type(reconnect_exc).__name__,
                        reconnect_exc,
                    )
                await asyncio.sleep(backoff)

    def _task_key(self, account_name: str, task_name: str) -> tuple[str, str]:
        return account_name, task_name

    def _should_log_rule_event(
        self,
        rule: KeywordMonitorRule,
        event_key: str,
        *,
        interval_seconds: float = 30.0,
    ) -> bool:
        now = time.monotonic()
        cache_key = (rule.account_name, rule.task_name, event_key)
        last_logged_at = self._skip_log_times.get(cache_key, 0.0)
        if now - last_logged_at < interval_seconds:
            return False
        self._skip_log_times[cache_key] = now
        return True

    def _append_task_log(
        self,
        account_name: str,
        task_name: str,
        line: str,
        *,
        active: Optional[bool] = None,
    ) -> None:
        key = self._task_key(account_name, task_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs = self._task_logs.setdefault(key, [])
        logs.append(f"{timestamp} - {line}")
        if len(logs) > 1000:
            del logs[:-1000]

        status = self._task_status.setdefault(key, {})
        status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        status["message"] = line
        if active is not None:
            status["active"] = active

    async def _publish_bus_event(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """发布事件到实时日志事件总线"""
        try:
            from backend.services.log_event_bus import get_log_event_bus
            bus = await get_log_event_bus()
            await bus.publish("monitor_logs", {
                "event_type": event_type,
                **data,
            })
        except Exception:
            pass  # 事件总线发布失败不影响主流程

    def _append_rule_log(
        self,
        rule: KeywordMonitorRule,
        line: str,
        *,
        active: Optional[bool] = None,
        detail: Optional[dict] = None,
    ) -> None:
        self._append_task_log(
            rule.account_name,
            rule.task_name,
            line,
            active=active,
        )
        # 结构化日志（用于监控面板实时展示）
        monitor_id = rule.task_name.replace("monitor:", "") if rule.task_name.startswith("monitor:") else rule.task_name
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "monitor_id": monitor_id,
            "message": line,
            "chat_title": detail.get("chat_title", "") if detail else "",
            "msg_preview": detail.get("msg_preview", "") if detail else "",
        }
        self._monitor_logs.setdefault(monitor_id, []).append(entry)
        if len(self._monitor_logs.get(monitor_id, [])) > 500:
            self._monitor_logs[monitor_id] = self._monitor_logs[monitor_id][-500:]

    def get_task_logs(self, task_name: str, account_name: Optional[str] = None) -> list[str]:
        if account_name:
            return list(self._task_logs.get(self._task_key(account_name, task_name), []))

        for (_item_account, item_task), logs in self._task_logs.items():
            if item_task == task_name:
                return list(logs)
        return []

    def get_task_history_entry(
        self,
        task_name: str,
        account_name: str,
    ) -> Optional[dict[str, Any]]:
        key = self._task_key(account_name, task_name)
        logs = self._task_logs.get(key) or []
        status = self._task_status.get(key)
        if not logs and not status:
            return None

        flow_logs = list(logs[-500:])
        return {
            "time": (status or {}).get("updated_at", ""),
            "success": bool((status or {}).get("active", False)),
            "message": (status or {}).get("message", "关键词后台监听状态"),
            "flow_logs": flow_logs,
            "flow_truncated": len(logs) > len(flow_logs),
            "flow_line_count": len(logs),
        }

    def _describe_rule(self, rule: KeywordMonitorRule) -> str:
        keywords = _parse_keywords(
            rule.action.get("keywords"),
            split_commas=_keyword_split_commas(rule.action),
        )
        preview = ", ".join(keywords[:3])
        if len(keywords) > 3:
            preview += f" ... 共 {len(keywords)} 条"
        push_channel = str(rule.action.get("push_channel") or "telegram").strip()
        continue_actions = self._continue_actions(rule.action)
        parts = [
            f"Chat={rule.chat_name}({rule.chat_id})",
            f"匹配方式={rule.action.get('match_mode') or 'contains'}",
            f"关键词={preview or '-'}",
            f"命中处理={push_channel}",
        ]
        if rule.message_thread_id is not None:
            parts.append(f"话题ID={rule.message_thread_id}")
        if push_channel == "continue":
            parts.append(f"后续动作={len(continue_actions)} 步")
        return "，".join(parts)

    def _describe_continue_action(self, action: Dict[str, Any]) -> str:
        try:
            action_id = int(action.get("action"))
        except (TypeError, ValueError):
            return f"未知动作: {action}"
        if action_id == 1:
            text = str(action.get("text") or "")
            return f"发送文本: {text[:120]}"
        if action_id == 2:
            return f"发送骰子: {action.get('dice') or '🎲'}"
        if action_id == 3:
            return f"点击按钮: {action.get('text') or ''}"
        if action_id == 4:
            return "AI 识图选择按钮"
        if action_id == 5:
            return "AI 计算并发送答案"
        if action_id == 6:
            return "AI 识图并发送文本"
        if action_id == 7:
            return "AI 计算并点击按钮"
        return f"动作 {action_id}"

    def _rules_key(self, rules: list[KeywordMonitorRule]) -> str:
        return repr(
            [
                {
                    "account_name": rule.account_name,
                    "task_name": rule.task_name,
                    "chat_id": rule.chat_id,
                    "message_thread_id": rule.message_thread_id,
                    "action": rule.action,
                }
                for rule in rules
            ]
        )

    def _handlers_are_active_for(self, rules: list[KeywordMonitorRule]) -> bool:
        expected_accounts = {rule.account_name for rule in rules}
        if not expected_accounts:
            return not self._handler_refs

        active_accounts = {
            account_name
            for account_name, client, _handler_ref in self._handler_refs
            if getattr(client, "is_connected", False)
            and getattr(client, "_tg_signpulse_no_updates", None) is False
        }
        return expected_accounts.issubset(active_accounts)

    def _load_rules(self) -> list[KeywordMonitorRule]:
        from backend.services.sign_tasks import get_sign_task_service

        rules: list[KeywordMonitorRule] = []

        # ---- 独立监听器（不依赖任务系统） ----
        try:
            import json
            monitors_file = settings.resolve_workdir() / "monitors.json"
            if monitors_file.exists():
                monitors = json.loads(monitors_file.read_text(encoding="utf-8"))
                for m in monitors:
                    if not m.get("enabled", True):
                        continue
                    action_type = m.get("action", "forward")
                    action_dict = {
                        "action": 8,
                        "keywords": m.get("keywords", []),
                        "match_mode": m.get("match_mode", "regex"),
                    }
                    action_dict["dedup_seconds"] = m.get("dedup_seconds", 60)
                    action_dict["fuzzy_threshold"] = m.get("fuzzy_threshold", 0.85)
                    action_dict["fuzzy_cooldown_minutes"] = m.get("fuzzy_cooldown_minutes", 5)
                    action_dict["smart_dedup"] = m.get("smart_dedup", False)
                    action_dict["forward_with_button"] = m.get("forward_with_button", False)
                    action_dict["smart_dedup_pattern"] = m.get("smart_dedup_pattern")
                    # 转发模式：chat_id=0 表示监听全部群聊/频道
                    if action_type == "forward":
                        action_dict["push_channel"] = "forward"
                        if m.get("forward_thread_id"):
                            action_dict["forward_message_thread_id"] = m["forward_thread_id"]
                        src_chat = m.get("source_chat_id") or 0
                        chat_label = str(src_chat) if src_chat else "*"
                        # 多目标转发（共享关键词，不同账号→不同频道）
                        targets = m.get("forward_targets")
                        if targets and isinstance(targets, list):
                            for tgt in targets:
                                acc = tgt.get("account", "")
                                fid = tgt.get("forward_chat_id")
                                if acc and fid:
                                    act_copy = dict(action_dict)
                                    act_copy["forward_chat_id"] = str(fid)
                                    rules.append(KeywordMonitorRule(
                                        account_name=acc,
                                        task_name=f"monitor:{m.get('id', 'unknown')}",
                                        chat_id=src_chat,
                                        chat_name=chat_label,
                                        message_thread_id=None,
                                        action=act_copy,
                                    ))
                            continue
                        # 单目标兼容
                        if m.get("forward_chat_id"):
                            action_dict["forward_chat_id"] = str(m["forward_chat_id"])
                        for acc_name in m.get("account_names", []):
                            rules.append(KeywordMonitorRule(
                                account_name=acc_name,
                                task_name=f"monitor:{m.get('id', 'unknown')}",
                                chat_id=src_chat,
                                chat_name=chat_label,
                                message_thread_id=None,
                                action=action_dict,
                            ))
                        continue
                    # 红包模式：需要指定群组
                    elif action_type in ("red_packet_button", "red_packet_keyword"):
                        action_dict["push_channel"] = "continue"
                        action_dict["red_packet_mode"] = "button" if action_type == "red_packet_button" else "keyword"
                        if m.get("extract_pattern"):
                            action_dict["extract_pattern"] = m["extract_pattern"]
                        if m.get("grab_text_template"):
                            action_dict["grab_text_template"] = m["grab_text_template"]
                        if m.get("red_packet_delay"):
                            action_dict["red_packet_delay"] = m["red_packet_delay"]
                        if m.get("button_names"):
                            action_dict["button_names"] = list(m["button_names"])
                        if m.get("auto_reply_list"):
                            action_dict["auto_reply_list"] = list(m["auto_reply_list"])
                        if m.get("auto_reply_delay"):
                            action_dict["auto_reply_delay"] = m["auto_reply_delay"]
                        if action_type == "red_packet_keyword":
                            tmpl = m.get("grab_text_template", "/grab {number}")
                            action_dict["continue_actions"] = [{"action": 1, "text": tmpl}]
                        for acc_name in m.get("account_names", []):
                            for chat_id in m.get("chat_ids", []):
                                rules.append(KeywordMonitorRule(
                                    account_name=acc_name,
                                    task_name=f"monitor:{m.get('id', 'unknown')}",
                                    chat_id=chat_id,
                                    chat_name=str(m.get('name', chat_id)),
                                    message_thread_id=None,
                                    action=action_dict,
                                ))
        except Exception as exc:
            logger.warning("Failed to load independent monitors: %s", exc)

        # ---- 任务系统中的监听模式任务 ----
        tasks = get_sign_task_service().list_tasks(force_refresh=True)
        for task in tasks:
            account_name = str(task.get("account_name") or "").strip()
            task_name = str(task.get("name") or "").strip()
            if not account_name or not task_name or not task.get("enabled", True):
                continue
            for chat in task.get("chats") or []:
                chat_id = chat.get("chat_id")
                try:
                    chat_id_int = int(chat_id)
                except (TypeError, ValueError):
                    continue
                for action in chat.get("actions") or []:
                    try:
                        action_id = int(action.get("action"))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if action_id != 8 or not _parse_keywords(
                        action.get("keywords"),
                        split_commas=_keyword_split_commas(action),
                    ):
                        continue
                    rules.append(
                        KeywordMonitorRule(
                            account_name=account_name,
                            task_name=task_name,
                            chat_id=chat_id_int,
                            chat_name=str(chat.get("name") or chat_id_int),
                            message_thread_id=_as_int_or_none(
                                chat.get("message_thread_id")
                            ),
                            action=dict(action),
                        )
                    )
        return rules

    def _match_keyword(self, action: Dict[str, Any], text: str) -> Optional[str]:
        keywords = _parse_keywords(
            action.get("keywords"),
            split_commas=_keyword_split_commas(action),
        )
        if not text:
            return None
        # 红包模式且未配置关键词
        if not keywords and action.get("red_packet_mode"):
            rp_mode = action["red_packet_mode"]
            # button 模式：扫描所有消息找红包按钮
            if rp_mode == "button":
                return "*"
            # keyword 模式：用 extract_pattern 过滤
            if rp_mode == "keyword":
                pattern = action.get("extract_pattern", r"/grab\s+(\d+)")
                try:
                    if re.search(pattern, text):
                        return text[:40]
                except re.error:
                    pass
            return None
        if not keywords:
            return None

        mode = (action.get("match_mode") or "contains").strip()
        ignore_case = bool(action.get("ignore_case", True))
        haystack = text.lower() if ignore_case else text

        for keyword in keywords:
            needle = keyword.lower() if ignore_case else keyword
            if mode == "exact" and haystack == needle:
                return keyword
            if mode == "regex":
                flags = re.IGNORECASE | re.MULTILINE if ignore_case else re.MULTILINE
                try:
                    match = re.search(keyword, text, flags=flags)
                    if match:
                        return _regex_keyword_value(match)
                except re.error as exc:
                    logger.warning("Invalid keyword monitor regex %r: %s", keyword, exc)
                continue
            if mode not in {"exact", "regex"} and needle in haystack:
                return keyword
        return None

    def _message_thread_id(self, message: Message) -> Optional[int]:
        candidates = _message_thread_candidates(message)
        return candidates[0] if candidates else None

    def _build_variables(
        self,
        *,
        account_name: str,
        rule: KeywordMonitorRule,
        message: Message,
        text: str,
        matched: str,
        chat_title: str,
        sender: str,
        url: str,
    ) -> Dict[str, str]:
        # 提取动态数字（红包等场景）
        number = ""
        number2 = ""
        number3 = ""
        extract_pattern = rule.action.get("extract_pattern") if isinstance(rule.action, dict) else None
        if extract_pattern:
            try:
                m = re.search(str(extract_pattern), text)
                if m and m.lastindex:
                    number = m.group(1) or ""
                    if m.lastindex >= 2:
                        number2 = m.group(2) or ""
                    if m.lastindex >= 3:
                        number3 = m.group(3) or ""
            except re.error:
                pass

        # 随机回复（从预设列表中选取）
        auto_reply_list = rule.action.get("auto_reply_list") if isinstance(rule.action, dict) else None
        random_reply = ""
        if isinstance(auto_reply_list, list) and auto_reply_list:
            import random
            random_reply = random.choice(auto_reply_list)

        return {
            "keyword": matched,
            "message": text,
            "text": text,
            "sender": sender,
            "chat_id": str(getattr(message.chat, "id", "")),
            "chat_title": chat_title,
            "message_id": str(getattr(message, "id", "")),
            "url": url,
            "task_name": rule.task_name,
            "account_name": account_name,
            "number": number,
            "number2": number2,
            "number3": number3,
            "random_reply": random_reply,
        }

    def _continue_actions(self, action: Dict[str, Any]) -> list[Dict[str, Any]]:
        actions = action.get("continue_actions")
        if not isinstance(actions, list):
            return []

        supported = {1, 2, 3, 4, 5, 6, 7}
        result: list[Dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            try:
                action_id = int(item.get("action"))
            except (TypeError, ValueError):
                continue
            if action_id in supported:
                result.append(dict(item))
        return result

    def _continue_target(
        self, action: Dict[str, Any], source_message: Message
    ) -> tuple[Union[int, str], Optional[int]]:
        target_chat_id = _parse_forward_chat_id(action.get("continue_chat_id"))
        if target_chat_id is None:
            target_chat_id = source_message.chat.id

        configured_thread_id = _as_int_or_none(action.get("continue_message_thread_id"))
        if configured_thread_id is not None:
            return target_chat_id, configured_thread_id

        if target_chat_id == source_message.chat.id:
            return target_chat_id, self._message_thread_id(source_message)
        return target_chat_id, None

    def _continue_interval(self, action: Dict[str, Any]) -> float:
        try:
            return max(float(action.get("continue_action_interval", 1)), 0.0)
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _build_ai_cfg_signature(cfg: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(cfg.get("api_key") or ""),
            str(cfg.get("base_url") or ""),
            str(cfg.get("model") or ""),
        )

    def _get_ai_tools(self):
        from tg_signer.ai_tools import AITools, OpenAIConfigManager

        for workdir in (settings.resolve_session_dir(), settings.resolve_workdir()):
            cfg = OpenAIConfigManager(workdir).load_config()
            if cfg:
                signature = self._build_ai_cfg_signature(cfg)
                if self._ai_tools is None or self._ai_cfg_signature != signature:
                    self._ai_tools = AITools(cfg)
                    self._ai_cfg_signature = signature
                return self._ai_tools
        raise RuntimeError("OpenAI config is required for keyword monitor AI actions")

    async def _warm_chat(self, client: Any, chat_id: Union[int, str]) -> None:
        try:
            await client.get_chat(chat_id)
        except Exception as exc:
            logger.debug("Keyword monitor warm chat failed for %r: %s", chat_id, exc)

    async def _request_callback_answer(
        self,
        client: Any,
        chat_id: Union[int, str],
        message_id: int,
        callback_data: Union[str, bytes],
    ) -> bool:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await client.request_callback_answer(
                    chat_id, message_id, callback_data=callback_data
                )
                return True
            except errors.FloodWait as exc:
                wait_seconds = max(int(getattr(exc, "value", 1) or 1), 1)
                if attempt >= max_retries:
                    logger.warning("Keyword monitor callback FloodWait failed: %s", exc)
                    return False
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
                if attempt >= max_retries:
                    logger.warning(
                        "Keyword monitor button callback did not respond after retries: %s",
                        exc,
                    )
                    return False
                try:
                    await self._ensure_client_ready(client)
                except Exception as reconnect_exc:
                    logger.warning(
                        "Keyword monitor callback reconnect failed: %s: %s",
                        type(reconnect_exc).__name__,
                        reconnect_exc,
                    )
                await asyncio.sleep(min(2**attempt, 6))
            except Exception as exc:
                if _is_callback_data_invalid(exc):
                    logger.warning(
                        "Keyword monitor callback returned DATA_INVALID; waiting for follow-up messages"
                    )
                    return False
                logger.warning("Keyword monitor callback could not be confirmed: %s", exc)
                return False
        return False

    async def _click_inline_button(self, client: Any, message: Message, button: Any) -> bool:
        callback_data = getattr(button, "callback_data", None)
        if callback_data is not None:
            if await self._request_callback_answer(
                client, message.chat.id, message.id, callback_data
            ):
                return True

        click = getattr(message, "click", None)
        if callable(click):
            for args, kwargs in (
                ((getattr(button, "text", None),), {}),
                ((), {"text": getattr(button, "text", None)}),
            ):
                try:
                    await click(*args, **kwargs)
                    return True
                except TypeError:
                    continue
                except Exception as exc:
                    if _is_callback_data_invalid(exc):
                        logger.warning(
                            "Keyword monitor Message.click could not confirm callback; waiting for follow-up messages"
                        )
                    else:
                        logger.warning(
                            "Keyword monitor Message.click could not confirm callback: %s",
                            exc,
                        )
                    return False
        return False

    async def _click_keyboard_by_text_result(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> tuple[bool, bool]:
        target_text = _clean_text_for_match(str(action.get("text") or ""))
        if not target_text:
            return False, False

        reply_markup = getattr(message, "reply_markup", None)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            flat_buttons = (button for row in reply_markup.inline_keyboard for button in row)
            for button in flat_buttons:
                button_text = getattr(button, "text", None)
                if not button_text:
                    continue
                if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                    return await self._click_inline_button(client, message, button), True
            return False, False

        if isinstance(reply_markup, ReplyKeyboardMarkup):
            for row in reply_markup.keyboard:
                for button in row:
                    button_text = (
                        button if isinstance(button, str) else getattr(button, "text", "")
                    )
                    if not button_text:
                        continue
                    if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                        kwargs: Dict[str, Any] = {}
                        if target_thread_id is not None:
                            kwargs["message_thread_id"] = target_thread_id
                        await self._call_client_with_retry(
                            client,
                            lambda _button_text=button_text, _kwargs=dict(kwargs): client.send_message(
                                target_chat_id, _button_text, **_kwargs
                            ),
                            operation=f"keyword monitor send reply keyboard {target_chat_id}",
                        )
                        return True, True
        return False, False

    async def _click_keyboard_by_text(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> bool:
        clicked, _matched = await self._click_keyboard_by_text_result(
            client,
            target_chat_id,
            target_thread_id,
            action,
            message,
        )
        return clicked

    async def _recent_messages(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        limit: int,
    ) -> list[Message]:
        async def _load_messages() -> list[Message]:
            messages: list[Message] = []
            async for message in client.get_chat_history(chat_id, limit=limit):
                if _message_matches_thread(message, thread_id):
                    messages.append(message)
            return messages

        return await self._call_client_with_retry(
            client,
            _load_messages,
            operation=f"keyword monitor get_chat_history {chat_id}",
        )

    def _message_supports_action(self, message: Message, action_id: int) -> bool:
        reply_markup = getattr(message, "reply_markup", None)
        if action_id == 3:
            return bool(reply_markup)
        if action_id == 4:
            return bool(message.photo and _collect_clickable_buttons(message))
        if action_id == 5:
            return bool(message.text or message.caption)
        if action_id == 6:
            return bool(message.photo)
        if action_id == 7:
            return bool((message.text or message.caption) and reply_markup)
        return False

    async def _find_recent_message(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        action_id: int,
    ) -> Optional[Message]:
        limit = _read_positive_int_env(
            "KEYWORD_MONITOR_CONTINUE_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT, 1
        )
        messages = await self._recent_messages(client, chat_id, thread_id, limit)
        for message in messages:
            if self._message_supports_action(message, action_id):
                return message
        return None

    async def _wait_for_chat_advance(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            for message_id, marker in current_state.items():
                if before_state.get(message_id) != marker:
                    return True
        return False

    async def _wait_for_continue_action_candidate(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        action: Dict[str, Any],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }
            for message in messages:
                if (
                    message.id in changed_ids
                    and _message_supports_continue_action(message, action)
                ):
                    return True
        return False

    async def _wait_for_terminal_success(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }
            for message in messages:
                if message.id in changed_ids and _message_has_terminal_success_text(
                    message
                ):
                    return True
        return False

    async def _download_photo_bytes(self, client: Any, message: Message) -> bytes:
        image_buffer = await client.download_media(message.photo.file_id, in_memory=True)
        image_buffer.seek(0)
        return image_buffer.read()

    async def _execute_ai_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> bool:
        action_id = int(action.get("action"))
        ai_tools = self._get_ai_tools()
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id

        if action_id == 5:
            query = (message.text or message.caption or "").strip()
            answer = (
                await ai_tools.calculate_problem(
                    query,
                    system_prompt=action.get("ai_prompt"),
                )
                or ""
            ).strip()
            if not answer:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, answer, **kwargs),
                operation=f"keyword monitor AI text reply {target_chat_id}",
            )
            return True

        if action_id == 6:
            image_bytes = await self._download_photo_bytes(client, message)
            answer = (
                await ai_tools.extract_text_by_image(
                    image_bytes,
                    system_prompt=action.get("ai_prompt"),
                )
                or ""
            ).strip()
            if not answer:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, answer, **kwargs),
                operation=f"keyword monitor AI OCR reply {target_chat_id}",
            )
            return True

        if action_id == 7:
            query = (message.text or message.caption or "").strip()
            answer = (
                await ai_tools.calculate_problem(
                    query,
                    system_prompt=action.get("ai_prompt"),
                )
                or ""
            ).strip()
            if not answer:
                return False
            proxy_action = {"action": 3, "text": answer}
            return await self._click_keyboard_by_text(
                client, target_chat_id, target_thread_id, proxy_action, message
            )

        if action_id == 4:
            if not message.photo:
                return False
            clickable_buttons = _collect_clickable_buttons(message)
            if not clickable_buttons:
                return False
            image_bytes = await self._download_photo_bytes(client, message)
            question_text = (message.caption or message.text or "").strip() or "Choose the correct option"
            options = [button_text for _, _, button_text in clickable_buttons]
            result_indexes = await ai_tools.choose_options_by_image(
                image_bytes,
                question_text,
                list(enumerate(options, start=1)),
                system_prompt=action.get("ai_prompt"),
            )
            clicked = 0
            for result_index in result_indexes:
                if result_index == 0:
                    selected_index = 0
                elif 1 <= result_index <= len(options):
                    selected_index = result_index - 1
                elif 0 <= result_index < len(options):
                    selected_index = result_index
                else:
                    return False
                button_kind, button, button_text = clickable_buttons[selected_index]
                if button_kind == "inline":
                    if await self._click_inline_button(client, message, button):
                        clicked += 1
                else:
                    await self._call_client_with_retry(
                        client,
                        lambda _button_text=button_text, _kwargs=dict(kwargs): client.send_message(
                            target_chat_id, _button_text, **_kwargs
                        ),
                        operation=f"keyword monitor reply keyboard click {target_chat_id}",
                    )
                    clicked += 1
                await asyncio.sleep(0.3)
            return clicked > 0

        return False

    async def _execute_continue_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        timeout: Optional[float] = None,
        next_action: Optional[Dict[str, Any]] = None,
    ) -> bool:
        action_id = int(action.get("action"))
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id

        if action_id == 1:
            text = str(action.get("text") or "").strip()
            if not text:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, text, **kwargs),
                operation=f"keyword monitor continue send_message {target_chat_id}",
            )
            return True

        if action_id == 2:
            dice = str(action.get("dice") or "🎲").strip() or "🎲"
            await self._call_client_with_retry(
                client,
                lambda: client.send_dice(target_chat_id, dice, **kwargs),
                operation=f"keyword monitor continue send_dice {target_chat_id}",
            )
            return True

        action_timeout = timeout or _read_positive_float_env(
            "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
        )
        deadline = time.perf_counter() + action_timeout
        limit = _read_positive_int_env(
            "KEYWORD_MONITOR_CONTINUE_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT, 1
        )

        while time.perf_counter() < deadline:
            recent_messages = await self._recent_messages(
                client,
                target_chat_id,
                target_thread_id,
                limit,
            )
            usable_messages = [
                message
                for message in recent_messages
                if self._message_supports_action(message, action_id)
            ]

            for recent_message in usable_messages:
                if action_id == 3:
                    before_state = _messages_state(recent_messages)
                    clicked, matched = await self._click_keyboard_by_text_result(
                        client,
                        target_chat_id,
                        target_thread_id,
                        action,
                        recent_message,
                    )
                    if clicked:
                        return True
                    if matched:
                        follow_timeout = min(6.0, action_timeout)
                        if next_action is not None:
                            if _is_immediate_continue_action(next_action):
                                if await self._wait_for_chat_advance(
                                    client,
                                    target_chat_id,
                                    target_thread_id,
                                    before_state,
                                    limit=limit,
                                    timeout=follow_timeout,
                                ):
                                    logger.info(
                                        "Keyword monitor button click returned false, "
                                        "but chat advanced before immediate next action; continuing"
                                    )
                                    return True
                                logger.warning(
                                    "Keyword monitor button click returned false, "
                                    "and chat did not advance before immediate next action"
                                )
                                return False
                            if await self._wait_for_continue_action_candidate(
                                client,
                                target_chat_id,
                                target_thread_id,
                                next_action,
                                before_state,
                                limit=limit,
                                timeout=follow_timeout,
                            ):
                                logger.info(
                                    "Keyword monitor button click returned false, "
                                    "but next action is ready; continuing"
                                )
                                return True
                            logger.warning(
                                "Keyword monitor button click returned false, "
                                "and next action is not ready"
                            )
                            return False
                        if await self._wait_for_terminal_success(
                            client,
                            target_chat_id,
                            target_thread_id,
                            before_state,
                            limit=limit,
                            timeout=follow_timeout,
                        ):
                            logger.info(
                                "Keyword monitor button click returned false, "
                                "but terminal success text was detected"
                            )
                            return True
                        logger.warning(
                            "Keyword monitor button click returned false, "
                            "and no terminal success text was detected"
                        )
                        return False
                    continue

                if await self._execute_ai_action(
                    client,
                    target_chat_id,
                    target_thread_id,
                    action,
                    recent_message,
                ):
                    return True

            await asyncio.sleep(0.5)

        logger.warning(
            "Keyword monitor continue action %s timed out waiting for usable message in %r",
            action_id,
            target_chat_id,
        )
        return False

    async def _execute_continue_actions(
        self,
        *,
        account_name: str,
        client: Any,
        rule: KeywordMonitorRule,
        message: Message,
        variables: Dict[str, str],
    ) -> None:
        continue_actions = self._continue_actions(rule.action)
        if not continue_actions:
            return

        target_chat_id, target_thread_id = self._continue_target(rule.action, message)
        interval = self._continue_interval(rule.action)
        timeout = _read_positive_float_env(
            "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
        )

        await self._warm_chat(client, target_chat_id)
        lock = get_account_lock(account_name)
        async with lock:
            rendered_actions = [
                _render_action_templates(raw_action, variables)
                for raw_action in continue_actions
            ]
            self._append_rule_log(
                rule,
                f"开始执行关键词命中后续动作：{len(rendered_actions)} 步，目标 Chat={target_chat_id}"
                + (
                    f"，话题ID={target_thread_id}"
                    if target_thread_id is not None
                    else ""
                ),
            )
            for index, action in enumerate(rendered_actions, start=1):
                next_action = (
                    rendered_actions[index]
                    if index < len(rendered_actions)
                    else None
                )
                action_desc = self._describe_continue_action(action)
                action_delay = _resolve_action_delay(
                    action,
                    interval if index > 1 else 0.0,
                )
                if action_delay > 0:
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} 等待 {action_delay:g} 秒后执行：{action_desc}",
                    )
                    await asyncio.sleep(action_delay)
                self._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 开始：{action_desc}",
                )
                try:
                    result = await asyncio.wait_for(
                        self._execute_continue_action(
                            client,
                            target_chat_id,
                            target_thread_id,
                            action,
                            timeout=timeout,
                            next_action=next_action,
                        ),
                        timeout=timeout + 1,
                    )
                except Exception as exc:
                    logger.warning(
                        "Keyword monitor continue action %s/%s failed for task %s: %s",
                        index,
                        len(continue_actions),
                        rule.task_name,
                        exc,
                        exc_info=True,
                    )
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} 执行异常：{exc}",
                    )
                    return
                if not result:
                    logger.warning(
                        "Keyword monitor continue action %s/%s returned false for task %s",
                        index,
                        len(continue_actions),
                        rule.task_name,
                    )
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} 执行失败：{action_desc}",
                    )
                    return
                self._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 执行成功：{action_desc}",
                )
                self._append_rule_log(rule, "关键词命中后续动作全部执行完成")
            await self._notify_red_packet_grab(rule=rule, message=message, chat_title="")

    async def _notify_red_packet_grab(
        self, *, rule: KeywordMonitorRule, message: Message, chat_title: str = ""
    ) -> None:
        """抢到红包后发送 Telegram Bot 通知"""
        try:
            from backend.services.config import get_config_service
            gs = get_config_service().get_global_settings()
            if not gs.get("telegram_bot_red_packet_notify_enabled"):
                return
            bot_token = gs.get("telegram_bot_token")
            bot_chat_id = gs.get("telegram_bot_chat_id")
            if not bot_token or not bot_chat_id:
                return
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = chat_title or str(getattr(message.chat, 'title', message.chat.id))
            text = (
                f"🧧 抢到红包！\n"
                f"群组: {title}\n"
                f"时间: {now_str}\n"
                f"关键词: {', '.join(rule.action.get('keywords', [])[:3]) or '全部'}"
            )
            from backend.services.push_notifications import send_telegram_bot_message
            await send_telegram_bot_message(
                bot_token=bot_token,
                chat_id=str(bot_chat_id),
                text=text,
                message_thread_id=gs.get("telegram_bot_message_thread_id"),
            )
        except Exception:
            pass

    async def _notify_forward_success(
        self,
        *,
        rule: KeywordMonitorRule,
        message: Message,
        chat_title: str = "",
        forward_chat_id: str = "",
        text_preview: str = "",
        keyword: str = "",
    ) -> None:
        """转发成功后通过 Telegram Bot 发送通知提醒"""
        try:
            from backend.services.config import get_config_service
            gs = get_config_service().get_global_settings()
            if not gs.get("telegram_bot_forward_notify_enabled", True):
                return
            bot_token = gs.get("telegram_bot_token")
            bot_chat_id = gs.get("telegram_bot_chat_id")
            if not bot_token or not bot_chat_id:
                return
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = chat_title or str(getattr(message.chat, 'title', message.chat.id))
            preview = text_preview[:200].replace('\n', ' ')
            text = (
                f"📨 秒转通知\n"
                f"群组: {title}\n"
                f"时间: {now_str}\n"
                f"关键词: {keyword}\n"
                f"转发至: {forward_chat_id}\n\n"
                f"{preview}"
            )
            from backend.services.push_notifications import send_telegram_bot_message
            await send_telegram_bot_message(
                bot_token=bot_token,
                chat_id=str(bot_chat_id),
                text=text,
                message_thread_id=gs.get("telegram_bot_message_thread_id"),
            )
            self._append_rule_log(rule, "Telegram Bot 通知已发送")
        except Exception:
            pass

    async def _click_red_packet_button(
        self, *, client: Any, rule: KeywordMonitorRule, message: Message
    ) -> bool:
        """自动点击消息中的红包按钮（支持指定按钮名/任意按钮）"""
        reply_markup = getattr(message, "reply_markup", None)
        if not reply_markup:
            return False

        button_names = rule.action.get("button_names") if isinstance(rule.action, dict) else None
        # 空列表 = 点击任意按钮（抢所有红包）
        click_any = not button_names or (isinstance(button_names, list) and len(button_names) == 0)
        if not isinstance(button_names, list):
            button_names = []

        try:
            from pyrogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

            if isinstance(reply_markup, InlineKeyboardMarkup):
                for row in reply_markup.inline_keyboard:
                    for btn in row:
                        btn_text = getattr(btn, "text", "") or ""
                        if not btn_text:
                            continue
                        if click_any or any(name.strip().lower() in btn_text.lower() for name in button_names if name.strip()):
                            self._append_rule_log(rule, f"红包模式：点击按钮 [{btn_text}]")
                            await self._click_inline_button(client, message, btn)
                            return True
            elif isinstance(reply_markup, ReplyKeyboardMarkup):
                for row in reply_markup.keyboard:
                    for btn in row:
                        btn_text = btn if isinstance(btn, str) else getattr(btn, "text", "")
                        if not btn_text:
                            continue
                        if click_any or any(name.strip().lower() in btn_text.lower() for name in button_names if name.strip()):
                            self._append_rule_log(rule, f"红包模式：点击回复按钮 [{btn_text}]")
                            await client.send_message(
                                chat_id=message.chat.id,
                                text=btn_text,
                                message_thread_id=getattr(message, "message_thread_id", None),
                            )
                            return True
        except Exception as exc:
            self._append_rule_log(rule, f"红包按钮点击失败: {exc}")
        return False

    async def _send_red_packet_reply(
        self, *, client: Any, rule: KeywordMonitorRule, message: Message,
        reply_text: str, reply_delay: float = 0
    ) -> None:
        """发送红包抢后的自动回复"""
        if not reply_text:
            return
        try:
            if reply_delay > 0:
                self._append_rule_log(rule, f"等待 {reply_delay:g} 秒后发送自动回复")
                await asyncio.sleep(reply_delay)
            else:
                await asyncio.sleep(random.uniform(0.3, 0.8))
            await client.send_message(
                chat_id=message.chat.id,
                text=reply_text,
                message_thread_id=getattr(message, "message_thread_id", None),
            )
            self._append_rule_log(rule, f"红包自动回复已发送: {reply_text[:60]}")
        except Exception as exc:
            self._append_rule_log(rule, f"红包自动回复失败: {exc}")

    async def _on_message(self, account_name: str, client: Any, message: Message) -> None:
        try:
            from backend.services.config import get_config_service

            # ── 消息接收心跳：记录每次收到消息的时间 ──
            now = time.time()
            self._msg_received[account_name] = self._msg_received.get(account_name, 0) + 1
            self._last_msg_time[account_name] = now

            text = _message_text(message)
            if not text:
                return
            message_thread_id = self._message_thread_id(message)
            same_chat_rules = [
                rule
                for rule in self._rules
                if rule.account_name == account_name
                and (rule.chat_id == 0 or rule.chat_id == message.chat.id)
            ]
            if not same_chat_rules:
                return
            matched_rules = [
                rule
                for rule in same_chat_rules
                if _message_matches_thread(message, rule.message_thread_id)
            ]
            if not matched_rules:
                thread_candidates = _message_thread_candidates(message)
                for rule in same_chat_rules:
                    if rule.message_thread_id is None:
                        continue
                    if not self._should_log_rule_event(
                        rule,
                        "thread_mismatch",
                        interval_seconds=45.0,
                    ):
                        continue
                    self._append_rule_log(
                        rule,
                        "监听收到消息但话题ID不匹配："
                        f"配置={rule.message_thread_id}，"
                        f"消息={message_thread_id if message_thread_id is not None else '-'}，"
                        f"候选={thread_candidates or ['-']}",
                        active=True,
                    )
                return

            global_settings = get_config_service().get_global_settings()
            url = _message_url(message)
            chat_title = (
                getattr(message.chat, "title", None)
                or getattr(message.chat, "username", None)
                or str(getattr(message.chat, "id", ""))
            )
            sender = ""
            if message.from_user:
                sender = (
                    message.from_user.username
                    or " ".join(
                        item
                        for item in [
                            message.from_user.first_name,
                            message.from_user.last_name,
                        ]
                        if item
                    )
                    or str(message.from_user.id)
                )

            for rule in matched_rules:
                matched = self._match_keyword(rule.action, text)
                if not matched:
                    if self._should_log_rule_event(
                        rule,
                        "keyword_miss",
                        interval_seconds=60.0,
                    ):
                        text_preview = text.replace("\n", " ").strip()
                        if len(text_preview) > 120:
                            text_preview = text_preview[:117] + "..."
                        self._append_rule_log(
                            rule,
                            f"未命中：{text_preview}",
                            active=True,
                            detail={"chat_title": chat_title, "msg_preview": text_preview[:80]},
                        )
                    continue
                text_preview = text.replace("\n", " ").strip()
                if len(text_preview) > 160:
                    text_preview = text_preview[:157] + "..."
                self._append_rule_log(
                    rule,
                    f"✅ 命中 [{matched}] Chat={chat_title}({getattr(message.chat, 'id', '')})：{text_preview}",
                    active=True,
                    detail={"chat_title": chat_title, "msg_preview": text_preview[:80]},
                )
                # 发布到实时事件总线
                await self._publish_bus_event("keyword_match", {
                    "monitor_id": rule.task_name.replace("monitor:", "") if rule.task_name.startswith("monitor:") else rule.task_name,
                    "account_name": account_name,
                    "chat_title": chat_title,
                    "keyword": matched,
                    "msg_preview": text_preview[:80],
                    "sender": sender,
                })
                body_lines = [
                    f"Task: {rule.task_name}",
                    f"Chat: {chat_title}",
                    f"Keyword: {matched}",
                ]
                if sender:
                    body_lines.append(f"Sender: {sender}")
                body_lines.append("")
                body_lines.append(text)
                forward_text = "\n".join(body_lines)
                variables = self._build_variables(
                    account_name=account_name,
                    rule=rule,
                    message=message,
                    text=text,
                    matched=matched,
                    chat_title=chat_title,
                    sender=sender,
                    url=url,
                )

                push_channel = str(rule.action.get("push_channel") or "telegram").strip()
                continue_enabled = push_channel == "continue"
                forward_chat_id = (
                    _parse_forward_chat_id(rule.action.get("forward_chat_id"))
                    if push_channel == "forward"
                    else None
                )
                if forward_chat_id is not None:
                    try:
                        # === 两级去重：完全匹配 + 模糊匹配 ===
                        monitor_id = rule.task_name.replace("monitor:", "")
                        dedup_seconds = int(rule.action.get("dedup_seconds", 60) or 0)
                        now = time.time()
                        forwarded = False

                        if dedup_seconds > 0:
                            normalized_text = text.strip()

                            # Level 1: 消息ID去重（同一消息不重复转发）
                            dedup_key = f"{rule.task_name}:{message.chat.id}:{message.id}"
                            if dedup_key in self._forwarded_cache:
                                if now - self._forwarded_cache[dedup_key] < dedup_seconds:
                                    continue
                            self._forwarded_cache[dedup_key] = now

                            # Level 2: 完全匹配 — 与上一条转发内容完全一致则拦掉
                            last_text = self._last_forwarded_text.get(monitor_id, "")
                            if normalized_text and normalized_text == last_text:
                                self._append_rule_log(rule, "去重（完全匹配）：该消息与上一条完全一致，已拦截")
                                continue

                            # Level 3: 模糊匹配 — 冷却时间内相似度 ≥ 阈值则拦掉
                            fuzzy_threshold = float(rule.action.get("fuzzy_threshold", 0.85) or 0)
                            fuzzy_cooldown = int(rule.action.get("fuzzy_cooldown_minutes", 5) or 0) * 60
                            if fuzzy_threshold > 0 and fuzzy_cooldown > 0 and normalized_text:
                                text_hash = hashlib.md5(normalized_text.encode()).hexdigest()
                                cache = self._fuzzy_dedup_cache.setdefault(monitor_id, [])
                                # 清理过期
                                cache[:] = [(h, t) for h, t in cache if now - t < fuzzy_cooldown]
                                for cached_hash, cached_time in cache:
                                    cached_text = self._last_forwarded_text.get(f"{monitor_id}:hash:{cached_hash}", "")
                                    if cached_text:
                                        ratio = difflib.SequenceMatcher(None, normalized_text, cached_text).ratio()
                                        if ratio >= fuzzy_threshold:
                                            remain = int(fuzzy_cooldown - (now - cached_time))
                                            self._append_rule_log(rule, f"去重（模糊匹配）：相似度 {ratio:.2f} ≥ {fuzzy_threshold}，冷却剩余 {remain}s，已拦截")
                                            forwarded = True
                                            break
                                if forwarded:
                                    continue
                                # 记录本次
                                cache.append((text_hash, now))
                                if len(cache) > 20:
                                    cache.pop(0)
                                self._last_forwarded_text[f"{monitor_id}:hash:{text_hash}"] = normalized_text

                            # Level 4: 智能去重 — 提取数值比对，数值不变不转发
                            smart_dedup = rule.action.get("smart_dedup", False)
                            if smart_dedup and normalized_text:
                                pattern = rule.action.get("smart_dedup_pattern") or r'\d+'
                                nums = re.findall(pattern, normalized_text)
                                sig = '|'.join(nums) if nums else ''
                                last_sig = self._smart_dedup_last.get(monitor_id, '')
                                if sig and sig == last_sig:
                                    self._append_rule_log(rule, f"去重（智能数值）：数值签名 [{sig}] 未变化，已拦截")
                                    continue
                                if sig:
                                    self._smart_dedup_last[monitor_id] = sig
                                    self._append_rule_log(rule, f"智能去重：数值签名 [{sig}]" + (f" (前次: [{last_sig}])" if last_sig else " (首次)"))

                            # 记录最后转发的文本
                            self._last_forwarded_text[monitor_id] = normalized_text

                            # 定期清理
                            self._forwarded_cache = {
                                k: v for k, v in self._forwarded_cache.items()
                                if now - v < max(dedup_seconds * 2, 120)
                            }

                        forward_kwargs: dict[str, Any] = {}
                        forward_thread_id = _as_int_or_none(
                            rule.action.get("forward_message_thread_id")
                        )
                        if forward_thread_id is not None:
                            forward_kwargs["message_thread_id"] = forward_thread_id

                        # ── forward_messages 原生转发（带「已转发」标识）──
                        fwd_result = await self._call_client_with_retry(
                            client,
                            lambda _fid=forward_chat_id, _kw=dict(forward_kwargs):
                                client.forward_messages(_fid, message.chat.id, message.id, **_kw),
                            operation=f"keyword monitor forward {forward_chat_id}",
                        )

                        # 链接优先级：原始来源 > 当前消息
                        # 如果大号的消息本身就是转发的（forward_from_chat），则链回真正的原始消息
                        raw_chat_id = str(getattr(message.chat, 'id', ''))
                        # 链接优先级：forward_from_chat > forward_origin > 当前消息
                        # 处理多级转发链条（大号从群组转至频道，小号再从频道转出）
                        fwd_from_chat = getattr(message, 'forward_from_chat', None)
                        fwd_from_msg_id = getattr(message, 'forward_from_message_id', None)
                        if not fwd_from_chat:
                            fwd_origin = getattr(message, 'forward_origin', None)
                            if fwd_origin:
                                fwd_from_chat = getattr(fwd_origin, 'chat', None)
                                fwd_from_msg_id = getattr(fwd_origin, 'message_id', 0) or getattr(message, 'forward_from_message_id', None)
                        if fwd_from_chat and fwd_from_msg_id:
                            src_chat_id = str(getattr(fwd_from_chat, 'id', ''))
                            clean_src = src_chat_id[4:] if src_chat_id.startswith("-100") else src_chat_id.lstrip("-")
                            msg_link = f"https://t.me/c/{clean_src}/{fwd_from_msg_id}"
                        else:
                            fwd_msg_id_val = getattr(message, 'forward_from_message_id', None) or 0
                            if fwd_msg_id_val:
                                clean_chat = raw_chat_id[4:] if raw_chat_id.startswith("-100") else raw_chat_id.lstrip("-")
                                msg_link = f"https://t.me/c/{clean_chat}/{fwd_msg_id_val}"
                            else:
                                clean_chat = raw_chat_id[4:] if raw_chat_id.startswith("-100") else raw_chat_id.lstrip("-")
                                msg_link = f"https://t.me/c/{clean_chat}/{message.id}"
                        await self._call_client_with_retry(
                            client,
                            lambda _fid=forward_chat_id, _link=msg_link, _kw=dict(forward_kwargs):
                                client.send_message(_fid, f"🔗 {_link}", **_kw),
                            operation=f"keyword monitor link {forward_chat_id}",
                        )
                        self._append_rule_log(
                            rule,
                            f"✅ 转发成功 → {chat_title}({raw_chat_id}) → {forward_chat_id}"
                            + (f"，话题ID={forward_thread_id}" if forward_thread_id is not None else ""),
                        )

                        # ── Bot 通知 ──
                        await self._notify_forward_success(
                            rule=rule,
                            message=message,
                            chat_title=chat_title,
                            forward_chat_id=str(forward_chat_id),
                            text_preview=text,
                            keyword=matched,
                        )

                        # 发布转发成功事件
                        await self._publish_bus_event("forward_success", {
                            "monitor_id": rule.task_name.replace("monitor:", "") if rule.task_name.startswith("monitor:") else rule.task_name,
                            "account_name": account_name,
                            "forward_chat_id": str(forward_chat_id),
                            "forward_thread_id": forward_thread_id,
                        })
                    except Exception as exc:
                        logger.warning(
                            "Failed to forward keyword match to %r: %s",
                            forward_chat_id,
                            exc,
                        )
                        self._append_rule_log(
                            rule,
                            f"关键词命中消息转发失败：目标 Chat={forward_chat_id}，错误={exc}",
                        )
                        # 发布转发失败事件
                        await self._publish_bus_event("forward_failure", {
                            "monitor_id": rule.task_name.replace("monitor:", "") if rule.task_name.startswith("monitor:") else rule.task_name,
                            "account_name": account_name,
                            "forward_chat_id": str(forward_chat_id),
                            "error": str(exc),
                        })

                elif push_channel == "forward":
                    # push_channel=forward 但 forward_chat_id 未配置或无效
                    self._append_rule_log(
                        rule,
                        f"⚠️ 转发目标未配置（forward_chat_id 为空/无效），关键词已命中但消息未被转发。"
                        f"请在监控器设置中填写「转发目标 Chat ID」。"
                        f"命中内容：{text[:100]}",
                    )
                    logger.warning(
                        "Keyword monitor forward skipped for task %s: forward_chat_id is %r",
                        rule.task_name,
                        rule.action.get("forward_chat_id"),
                    )

                if push_channel not in {"forward", "continue"}:
                    push_settings = dict(global_settings)
                    push_settings["keyword_monitor_push_channel"] = push_channel
                    push_settings["keyword_monitor_bark_url"] = rule.action.get("bark_url")
                    push_settings["keyword_monitor_custom_url"] = rule.action.get(
                        "custom_url"
                    )
                    await send_keyword_push(
                        push_settings,
                        {
                            "title": "TG-SignPulse keyword matched",
                            "body": forward_text,
                            "text": text,
                            "keyword": matched,
                            "account_name": account_name,
                            "task_name": rule.task_name,
                            "chat_id": getattr(message.chat, "id", None),
                            "chat_title": chat_title,
                            "sender": sender,
                            "message_id": message.id,
                            "url": url,
                        },
                    )
                    self._append_rule_log(
                        rule,
                        f"关键词命中通知已处理：推送方式={push_channel}",
                    )
                if continue_enabled:
                    # 红包模式：延迟执行
                    red_packet_delay = float(rule.action.get("red_packet_delay") or 0)
                    red_packet_mode = rule.action.get("red_packet_mode")
                    if red_packet_delay > 0:
                        self._append_rule_log(
                            rule,
                            f"红包模式：等待 {red_packet_delay:g} 秒后执行",
                        )
                        await asyncio.sleep(red_packet_delay)

                    # 红包按钮点击模式
                    if red_packet_mode == "button":
                        clicked = await self._click_red_packet_button(
                            client=client,
                            rule=rule,
                            message=message,
                        )
                        if clicked:
                            await self._notify_red_packet_grab(rule=rule, message=message, chat_title=chat_title)
                            # 发送随机回复
                            if variables.get("random_reply"):
                                reply_delay = float(rule.action.get("auto_reply_delay") or 0)
                                await self._send_red_packet_reply(
                                    client=client,
                                    rule=rule,
                                    message=message,
                                    reply_text=variables["random_reply"],
                                    reply_delay=reply_delay,
                                )
                        else:
                            self._append_rule_log(rule, "红包模式：消息无匹配按钮，跳过")

                    await self._execute_continue_actions(
                        account_name=account_name,
                        client=client,
                        rule=rule,
                        message=message,
                        variables=variables,
                    )
        except Exception as exc:
            logger.warning("Keyword monitor handling failed: %s", exc, exc_info=True)

    async def restart_from_tasks(self) -> None:
        async with self._lock:
            from backend.services.config import get_config_service
            from tg_signer.core import (
                _CLIENT_INSTANCES,
                close_client_by_name,
                get_client,
            )

            rules = self._load_rules()
            key = self._rules_key(rules)
            if key == self._active_key and self._handlers_are_active_for(rules):
                for rule in rules:
                    if not self._task_logs.get(
                        self._task_key(rule.account_name, rule.task_name)
                    ):
                        self._append_rule_log(
                            rule,
                            f"关键词后台监听运行中：{self._describe_rule(rule)}",
                            active=True,
                        )
                return

            await self.stop()
            self._rules = rules
            if not rules:
                self._active_key = key
                return

            session_dir = settings.resolve_session_dir()
            global_settings = get_config_service().get_global_settings()
            tg_config = get_config_service().get_telegram_config()
            api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
            api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")
            try:
                api_id = int(api_id) if api_id is not None else None
            except (TypeError, ValueError):
                api_id = None

            accounts = sorted({rule.account_name for rule in rules})
            started_accounts: set[str] = set()
            for account_name in accounts:
                account_rules = [rule for rule in rules if rule.account_name == account_name]
                chat_ids = sorted({rule.chat_id for rule in account_rules})
                # chat_id=0 表示监听全部群聊/频道（转发模式）
                has_wildcard = 0 in chat_ids
                if has_wildcard:
                    chat_ids = [cid for cid in chat_ids if cid != 0]
                proxy_value = get_account_proxy(account_name)
                if not proxy_value:
                    proxy_value = (global_settings.get("global_proxy") or "").strip() or None
                proxy = build_proxy_dict(proxy_value) if proxy_value else None

                session_mode = get_session_mode()
                session_string = None
                in_memory = False
                if session_mode == "string":
                    session_string = get_account_session_string(
                        account_name
                    ) or load_session_string_file(session_dir, account_name)
                    in_memory = bool(session_string)
                    if not session_string:
                        logger.warning(
                            "Keyword monitor account %s has no session_string",
                            account_name,
                        )
                        for rule in account_rules:
                            self._append_rule_log(
                                rule,
                                "关键词后台监听启动失败：账号没有可用 session_string",
                                active=False,
                            )
                        continue

                lock = get_account_lock(account_name)
                async with lock:
                    base_key = str(session_dir.joinpath(account_name).resolve())
                    # Also check the ::memory suffixed key (used when in_memory=True)
                    memory_key = f"{base_key}::memory"
                    existing = _CLIENT_INSTANCES.get(base_key) or _CLIENT_INSTANCES.get(memory_key)
                    if (
                        existing is not None
                        and getattr(existing, "_tg_signpulse_no_updates", None) is True
                    ):
                        logger.info(
                            "Recreating keyword monitor client for %s (was no_updates=True) with updates enabled",
                            account_name,
                        )
                        # close_client_by_name now handles both base_key and ::memory variants
                        await close_client_by_name(account_name, workdir=session_dir)

                    client = get_client(
                        account_name,
                        proxy=proxy,
                        workdir=session_dir,
                        session_string=session_string,
                        in_memory=in_memory,
                        api_id=api_id,
                        api_hash=api_hash,
                        no_updates=False,
                    )

                    async def handler(
                        client, message: Message, name: str = account_name
                    ) -> None:
                        await self._on_message(name, client, message)

                    # 构建消息过滤器
                    # 注意：filters.chat() 内部会调用 resolve_peer()，对无效群组直接抛 CHANNEL_INVALID
                    # 因此先把 client 启动，再预热每个 chat，排除无效的
                    try:
                        await client.__aenter__()
                    except Exception:
                        logger.warning(
                            "Keyword monitor failed to start client for %s",
                            account_name, exc_info=True,
                        )
                        for rule in account_rules:
                            self._append_rule_log(
                                rule,
                                "关键词后台监听启动失败：Telegram client 启动失败，请检查账号登录状态、代理或 API 配置",
                                active=False,
                            )
                        continue

                    # 预热 + 过滤无效 chat
                    valid_chat_ids: list[int] = []
                    for cid in chat_ids:
                        try:
                            await client.get_chat(cid)
                            valid_chat_ids.append(cid)
                        except Exception:
                            logger.warning(
                                "Keyword monitor skipping invalid/unjoined chat_id=%s for %s",
                                cid, account_name,
                            )
                            for rule in account_rules:
                                if rule.chat_id == cid:
                                    self._append_rule_log(
                                        rule,
                                        f"⚠️ 聊天 {cid} 无效或未加入，已跳过，对该群的监听将不生效",
                                        active=True,
                                    )

                    if has_wildcard:
                        base_filter = filters.group | filters.channel
                        if valid_chat_ids:
                            base_filter = base_filter | filters.chat(valid_chat_ids)
                    elif valid_chat_ids:
                        base_filter = filters.chat(valid_chat_ids)
                    else:
                        continue
                    msg_filter = base_filter & (filters.text | filters.caption)
                    handler_ref = client.add_handler(
                        MessageHandler(handler, msg_filter)
                    )

                    self._handler_refs.append((account_name, client, handler_ref))
                    started_accounts.add(account_name)
                    logger.info(
                        "Keyword monitor started for %s in %s", account_name, chat_ids
                    )
                    for rule in account_rules:
                        self._append_rule_log(
                            rule,
                            f"关键词后台监听已启动：{self._describe_rule(rule)}",
                            active=True,
                        )

            self._active_key = key if started_accounts == set(accounts) else ""

            # 启动心跳任务
            if started_accounts and self._heartbeat_task is None:
                self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

            # 发布启动事件
            await self._publish_bus_event("service_status", {
                "status": "started" if started_accounts else "partial",
                "accounts": list(started_accounts),
                "expected_accounts": list(accounts),
            })

    async def _heartbeat_loop(self) -> None:
        """每 30 秒发布一次心跳，包含消息接收状态诊断"""
        while True:
            await asyncio.sleep(30)
            now = time.time()
            # 防止重复心跳
            if now - self._last_heartbeat_time < 25:
                continue
            self._last_heartbeat_time = now

            try:
                active_accounts: List[str] = []
                for account_name, client, _ in self._handler_refs:
                    is_connected = getattr(client, "is_connected", False)
                    msg_count = self._msg_received.get(account_name, 0)
                    last_msg = self._last_msg_time.get(account_name, 0)
                    idle_seconds = int(now - last_msg) if last_msg else -1
                    is_healthy = is_connected and (
                        idle_seconds < 0 or idle_seconds < 300
                    )

                    active_accounts.append(account_name)
                    await self._publish_bus_event("heartbeat", {
                        "account_name": account_name,
                        "is_connected": is_connected,
                        "messages_received": msg_count,
                        "last_message_seconds_ago": idle_seconds if idle_seconds >= 0 else -1,
                        "is_healthy": is_healthy,
                        "handler_count": len(self._handler_refs),
                        "rule_count": len(self._rules),
                    })

                    # 诊断：超过 5 分钟未收到消息，输出警告
                    if idle_seconds > 300 and msg_count == 0:
                        logger.warning(
                            "Keyword monitor for %s: no messages received in %ss. "
                            "Possible issues: wrong chat filter, session expired, "
                            "or client with no_updates=True was reused.",
                            account_name, idle_seconds,
                        )
                        await self._publish_bus_event("diagnostic", {
                            "account_name": account_name,
                            "level": "warning",
                            "message": (
                                f"已 {idle_seconds}s 未收到任何消息。"
                                f"可能原因：聊天过滤不对、会话失效、或 no_updates 客户端复用。"
                            ),
                        })
            except Exception as exc:
                logger.warning("Heartbeat publish failed: %s", exc)

    async def stop(self) -> None:
        # 停止心跳
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        for rule in self._rules:
            self._append_rule_log(
                rule,
                "关键词后台监听已停止",
                active=False,
            )
        for account_name, client, handler_ref in self._handler_refs:
            lock = get_account_lock(account_name)
            async with lock:
                try:
                    client.remove_handler(*handler_ref)
                except Exception:
                    pass
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
        self._handler_refs = []
        self._rules = []
        self._active_key = ""

        # 发布停止事件
        await self._publish_bus_event("service_status", {
            "status": "stopped",
        })


_keyword_monitor_service: Optional[KeywordMonitorService] = None


def get_keyword_monitor_service() -> KeywordMonitorService:
    global _keyword_monitor_service
    if _keyword_monitor_service is None:
        _keyword_monitor_service = KeywordMonitorService()
    return _keyword_monitor_service

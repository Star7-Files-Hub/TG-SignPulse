"""Common helper functions shared across API routes."""
from __future__ import annotations

import asyncio
from typing import Optional


def trigger_side_effects() -> None:
    """Schedule sync_jobs and restart keyword monitors in background.

    Replaces the previously duplicated pattern:
        asyncio.ensure_future(sync_jobs())
        asyncio.ensure_future(_restart_keyword_monitors())
    """
    from backend.scheduler import sync_jobs

    asyncio.ensure_future(sync_jobs())

    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        asyncio.ensure_future(get_keyword_monitor_service().restart_from_tasks())
    except Exception:
        pass


def resolve_account_name(
    task: dict,
    account_name: Optional[str],
    sign_service=None,
) -> str:
    """Resolve a concrete account name from a possibly wildcard/empty value.

    When account_name is empty/None or "*", this function looks up the first
    real account name from the sign task's account_names list or falls back
    to the task's account_name field.

    Returns an empty string if no concrete account name can be resolved.
    """
    if account_name and account_name != "*":
        return account_name

    resolved = ""

    # Try from task's account_names list
    if task:
        account_names = task.get("account_names")
        if isinstance(account_names, list):
            for name in account_names:
                if name and name != "*":
                    resolved = str(name)
                    break

    # Fallback to task's account_name field
    if (not resolved or resolved == "*") and task:
        raw = str(task.get("account_name", ""))
        if raw and raw != "*":
            resolved = raw

    return resolved

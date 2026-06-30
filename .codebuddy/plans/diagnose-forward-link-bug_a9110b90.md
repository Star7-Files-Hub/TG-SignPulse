---
name: diagnose-forward-link-bug
overview: 将关键词监听的调试日志改为 WARNING 级别使其立即出现在 error.log 中，诊断转发链接生成逻辑的 bug，确认问题后修复，最后清理诊断代码。
todos:
  - id: add-diag-logs
    content: 在 keyword_monitor.py 转发链路的 6 个关键节点添加 logger.warning() 诊断日志
    status: completed
  - id: deploy-and-verify
    content: 将代码推送到服务器 216.144.224.133 并重启服务，用户检查 error.log 确认诊断日志可见
    status: completed
    dependencies:
      - add-diag-logs
  - id: fix-link-bug
    content: 根据诊断日志中的 forward_from_chat/forward_origin/existing_link 属性值，修复链接生成逻辑
    status: completed
    dependencies:
      - deploy-and-verify
  - id: cleanup-diag-logs
    content: 将诊断用的 logger.warning() 降级为 logger.info()，并为 keyword_monitor 添加独立的 monitor.log FileHandler
    status: completed
    dependencies:
      - fix-link-bug
---

## 用户需求

临时将关键词监听器转发链路中的关键调试日志从 INFO 级别改为 WARNING 级别，使其立即可见于服务器的 error.log 文件，用于诊断：

1. **转发链路是否被执行** — 确认关键词命中后 `forward_chat_id is not None` 分支进入情况
2. **链接生成是否正确** — 确认三层优先级的链接生成逻辑（已有🔗 → forward_from_chat → 当前消息）每一步的取值
3. **小号转发的链接指向错误** — 目标：小号 (1555) 转发消息时，附加的 `🔗` 链接应指向原始来源消息，而非中间频道

诊断完成后，根据日志输出修复链接生成 bug，最后将诊断日志降回合理级别。

## 技术方案

### 实施策略

分三步走：

1. **诊断埋点**：在 `keyword_monitor.py` 转发链路的 6 个关键节点添加 `logger.warning()`，将之前不可见的 INFO 日志提升为 WARNING
2. **远程验证**：推送代码到服务器 216.144.224.133，重启服务，用户检查 error.log 确认日志输出
3. **根据日志修复**：分析 WARNING 日志中暴露的 `forward_from_chat`、`forward_origin`、`existing_link` 等属性值，定位并修复链接生成 bug

### 关键诊断埋点位置（均在 keyword_monitor.py 同一文件中）

| 埋点 | 行号区域 | 目的 |
| --- | --- | --- |
| ① 转发入口 | 第 1921 行后 | 确认进入转发分支 |
| ② 去重通过 | 第 1991 行后 | 确认消息未被去重拦截 |
| ③ forward_messages 前后 | 第 2001-2006 行附近 | 确认原生转发是否成功执行 |
| ④ 链接生成详情 | 第 2042-2046 行（替换原 LINK_DEBUG） | 输出 forward 属性 + 计算出的链接 |
| ⑤ send_message 链接发送前后 | 第 2047-2052 行附近 | 确认链接消息是否发出 |
| ⑥ 转发完成 | 第 2053-2057 行区域 | 确认整条链路走完 |


### 临时日志格式设计

```python
logger.warning("FWD_ENTRY [%s] push_channel=forward target=%s msg_chat=%s msg_id=%s text_len=%s",
    account_name, forward_chat_id, message.chat.id, message.id, len(text or ""))

logger.warning("FWD_DEDUP_PASS [%s] 去重已通过，准备转发 msg=%s chat=%s",
    account_name, message.id, message.chat.id)

logger.warning("FWD_LINK [%s] raw_chat=%s fwd_from_chat=%s fwd_from_msg_id=%s fwd_origin_chat=%s existing_link=%s final_link=%s",
    account_name, raw_chat_id, fwd_src_chat_id, fwd_from_msg_id, fo_chat_id, existing_link, msg_link)

logger.warning("FWD_LINK_SENT [%s] link=%s target=%s", account_name, msg_link, forward_chat_id)

logger.warning("FWD_DONE [%s] chat=%s → target=%s link=%s", account_name, raw_chat_id, forward_chat_id, msg_link)
```

### 性能考量

- 短期增加 5-6 条 WARNING 日志/每次转发，转发频率受关键词命中率限制（通常数分钟一次），不构成性能瓶颈
- 诊断完成后需将日志降回合理级别，避免 error.log 长期被 flood

### 向后兼容

- 仅修改日志级别，不改变任何业务逻辑
- 不引入新的依赖或配置项
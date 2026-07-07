---
name: tg-assistant-full-refactor
overview: 对 TG-Assistant 进行全栈重构：清理死代码、拆分超大文件、统一项目命名、抽取公共逻辑、优化前端架构。
todos:
  - id: cleanup-and-rename
    content: 清理与命名统一：删除 2 个 Git 冲突副本文件，统一项目命名为 TG-Assistant（涵盖 pyproject.toml、deploy.sh、backend/core/config.py、前端 localStorage key 等 45 个文件中的命名替换，以及 README 文档更新）
    status: completed
  - id: remove-old-task-system
    content: 移除旧任务系统死代码：删除 tasks.py 路由/服务/模型/模型/Schema，从 scheduler 中移除 DB 任务同步和 _job_run_task，将 cleanup_old_logs 核心逻辑迁移到 scheduler 的 _job_maintenance，移除 events.py 中基于 TaskLog 的 SSE 端点，清理前端 api.ts 和 types.ts 中旧 API 函数和类型
    status: completed
    dependencies:
      - cleanup-and-rename
  - id: extract-common-patterns
    content: 抽取公共代码模式：创建 backend/api/routes/_utils.py，抽取 _post_mutation_side_effects() 替换 sign_tasks_v2.py 中 7 处重复的 sync_jobs/reconnect 调用，抽取 _resolve_account_names() 替换 5 处通配符账号解析；清理 sign_tasks_v2.py 中 Pydantic v1/v2 兼容层
    status: completed
    dependencies:
      - remove-old-task-system
  - id: split-backend-services
    content: 拆分后端超大服务文件：将 sign_tasks.py（146KB）拆为 crud/executor/log_manager，keyword_monitor.py（110KB）拆为 engine/forwarder/redpacket，telegram.py（97KB）拆为 client/qr/account_ops，tg_signer/core.py（131KB）拆为 handlers/checkin/click/action_chain，各模块通过 __init__.py 保持原导出接口不变
    status: completed
    dependencies:
      - extract-common-patterns
  - id: refactor-frontend
    content: 重构前端：将 api.ts（31KB）按领域拆分为 api/ 目录下 6 个模块（auth/accounts/sign-tasks/monitors/emby/config + client），将 useI18n.ts（41KB）硬编码翻译迁移到 locales/zh-CN.json 和 locales/en.json，拆分 Monitors.vue（36KB）为卡片+表单子组件，拆分 Tasks.vue（28KB）和 TaskForm.vue（30KB）为功能子表单
    status: completed
---

## 用户需求

对 TG-SignPulse 项目进行全面重构，涵盖后端架构优化和前端代码重组。

## 产品概述

TG-Assistant 是一个 Telegram 多功能自动化助手，提供签到任务编排、关键词监听转发、红包抢抢、Emby 保号等功能。当前项目处于功能成熟但代码结构混乱的状态，需要进行系统性重构以提升可维护性和可扩展性。

## 核心重构目标

- **统一命名**：项目标识从 TG-SignPulse / tg-signer 统一为 TG-Assistant
- **移除死代码**：删除已被 sign_tasks_v2 完全取代的旧任务系统（tasks.py / Task / TaskLog 模型）
- **拆分超大文件**：将 4 个超过 97KB 的后端服务文件和 5 个前端巨型组件拆分为模块化结构
- **消除代码重复**：抽取路由层重复的调度同步+监听器重启模式为公共函数
- **清理技术债务**：删除 Git 冲突残留文件、移除 Pydantic v1/v2 兼容层、前端国际化迁移到 JSON 文件

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy / APScheduler / Pyrogram (kurigram)
- **前端**：Vue 3 / Vite / TypeScript / Tailwind CSS 4 / Pinia
- **无需引入新依赖**，全部基于现有技术栈进行代码重组

## 实现方案

### 总体策略

采用**渐进式重构**策略，每个阶段独立可验证、不破坏现有功能。按依赖关系从底层（清理死代码）到顶层（前端重组）逐步推进。

### 架构调整

#### 1. 后端服务层拆分

**sign_tasks.py (146KB)** 按职责拆分为 3 个模块：

- `services/sign_tasks/crud.py` — 任务的 CRUD 操作（创建、读取、更新、删除、批量添加）
- `services/sign_tasks/executor.py` — 任务执行引擎（run_task_with_logs、异步执行、重试逻辑）
- `services/sign_tasks/log_manager.py` — 日志管理（TaskLogHandler、日志清理、日志查询）
- `services/sign_tasks/__init__.py` — 暴露统一入口 get_sign_task_service()

**keyword_monitor.py (110KB)** 按功能拆分为 3 个模块：

- `services/monitor/engine.py` — 监听引擎核心（启动/停止/重启监听器）
- `services/monitor/forwarder.py` — 消息转发逻辑（正则匹配、去重、智能数值比对）
- `services/monitor/redpacket.py` — 红包抢抢逻辑（关键词匹配、按钮点击、延迟回复）
- `services/monitor/__init__.py` — 暴露统一入口 get_keyword_monitor_service()

**telegram.py (97KB)** 按操作类型拆分为 3 个模块：

- `services/telegram/client.py` — Telegram 客户端管理（连接/断连/状态检测）
- `services/telegram/qr.py` — QR 码登录流程
- `services/telegram/account_ops.py` — 账号操作（重命名、删除、信息获取）
- `services/telegram/__init__.py` — 暴露统一入口 get_telegram_service()

**tg_signer/core.py (131KB)** 按 action handler 拆分为 4 个模块：

- `tg_signer/handlers/checkin.py` — 签到处理器
- `tg_signer/handlers/click.py` — AI 识图点击处理器
- `tg_signer/handlers/action_chain.py` — 自定义动作序列处理器
- `tg_signer/handlers/__init__.py` — 统一注册
- `tg_signer/core.py` — 精简后的核心引擎（仅保留 UserSigner 主类和路由逻辑）

#### 2. 公共代码抽取

在 `backend/api/routes/_utils.py` 新建模块，提供：

- `_post_mutation_side_effects()` — 替换 sign_tasks_v2.py 中 7 处重复的 `asyncio.ensure_future(sync_jobs())` + `asyncio.ensure_future(_restart_keyword_monitors())`
- `_resolve_account_names()` — 抽取 sign_tasks_v2.py 中 5 处重复的通配符账号解析逻辑

#### 3. 前端模块拆分

**api.ts (31KB)** 按领域拆分为 6 个 API 模块：

- `api/auth.ts` — 认证相关 (login, logout, refreshToken)
- `api/accounts.ts` — 账号管理
- `api/sign-tasks.ts` — 签到任务（原 sign_tasks_v2 对应 API）
- `api/monitors.ts` — 监听器
- `api/emby.ts` — Emby 保号
- `api/config.ts` — 系统配置 / 日志
- `api/client.ts` — 保留通用 fetch 封装和 request 函数

**useI18n.ts (41KB)** 硬编码翻译迁移为 JSON：

- `locales/zh-CN.json` — 简体中文
- `locales/en.json` — 英文
- `composables/useI18n.ts` — 精简为 JSON 加载 + 响应式切换逻辑

**Monitors.vue (36KB)** 拆分为：

- `Monitors.vue` — 主视图（列表 + 筛选）
- `components/monitors/MonitorCard.vue` — 单个监听器卡片
- `components/monitors/MonitorFormModal.vue` — 监听器创建/编辑表单

**Tasks.vue (28KB)** 拆分为：

- `Tasks.vue` — 主视图（列表 + 筛选）
- `components/tasks/TaskCard.vue` — 单个任务卡片

**TaskForm.vue (30KB)** 拆分为：

- `components/tasks/TaskForm.vue` — 主表单（组合子表单）
- `components/tasks/form/BasicInfoSection.vue` — 基本信息（名称、账号、调度）
- `components/tasks/form/ChatConfigSection.vue` — 聊天配置
- `components/tasks/form/ActionSequenceSection.vue` — 动作序列

## 实现细节

### 性能考虑

- 后端服务拆分保持单例模式不变，`__init__.py` 中的 `get_*_service()` 延迟导入子模块，避免启动时加载所有代码
- 前端 API 拆分后通过统一的 `api/client.ts` 共享 token 管理，无需重复请求拦截逻辑
- 国际化 JSON 文件通过 Vite 的 `import.meta.glob` 动态加载，支持 tree-shaking

### 向后兼容

- 所有拆分的后端模块通过 `__init__.py` 保持原有的导出接口不变（如 `get_sign_task_service()`），路由层不需要修改 import 路径
- 前端 `localStorage` key 从 `tg-signer-token` 改为 `tg-assistant-token` 时，需在 auth store 中添加迁移逻辑：首次读取时检查旧 key 并自动迁移
- deploy.sh 中路径变更需同步更新 systemd service 配置

### 风险控制

- 命名统一（tg-signpulse → tg-assistant）仅影响部署路径和显示名称，不影响数据库 schema
- 旧任务系统移除后，`cleanup_old_logs` 的核心逻辑需迁移到 `scheduler/__init__.py` 的 `_job_maintenance` 中，确保日志清理功能不丢失
- events.py 的 SSE 端点基于 TaskLog 表，移除后需确认前端是否还依赖该端点；如不再使用，直接删除该路由
<h1 align="center">TG-SignPulse</h1>

<p align="center">
  <strong>⚠️ 本项目已归档，不再维护 ⚠️</strong>
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

---

## 项目说明

TG-SignPulse 是一个 **AI Vibe Coding 技术学习项目**，用于探索和实践以下技术栈的整合方式：

- 前后端分离架构（Vue 3 + FastAPI）
- 现代 Python 异步编程模式
- AI/LLM API 集成（OpenAI 兼容接口调用）
- 任务调度系统设计（APScheduler）
- Web 认证方案（JWT + TOTP 2FA）
- 数据库支持：SQLite（默认）/ PostgreSQL（可选）

本项目是作者在学习 AI 辅助编程（Vibe Coding）过程中的练手作品，旨在通过一个完整的全栈项目来实践 AI 驱动的开发流程。项目代码主要由 AI 辅助生成，用于展示 AI 编程工具在实际项目中的应用效果。

---

## 快速部署

### 系统要求

- **操作系统**: Debian 11+ / Ubuntu 20.04+
- **内存**: 最低 512MB，推荐 1GB+
- **Python**: 3.10+
- **Node.js**: 20+（仅构建前端时需要）

### 一键部署

```bash
# 1. 上传并解压项目
tar -xzf tg-signpulse.tar.gz
mkdir -p /root/tg-signpulse
cp -r tg-signpulse/* /root/tg-signpulse/

# 2. 运行部署脚本
cd /root/tg-signpulse
chmod +x deploy.sh
sudo ./deploy.sh
```

部署完成后访问 `http://服务器IP:8080`，管理员密码存储在 `/data/tg-signpulse/.admin_bootstrap_password`。

### 使用 PostgreSQL（可选）

部署前设置环境变量即可自动切换：

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/tg_signpulse"
sudo -E ./deploy.sh
```

或部署后手动切换，参见下方【数据库切换】。

### 配置 AI 模型

项目支持 AI 识图/计算等动作，需在 Settings 页面配置 OpenAI API Key，或在 `.env` 中设置：

```bash
echo 'OPENAI_API_KEY=sk-xxx' >> /opt/tg-signpulse/.env
echo 'OPENAI_BASE_URL=https://api.openai.com/v1' >> /opt/tg-signpulse/.env
echo 'OPENAI_MODEL=gpt-4o' >> /opt/tg-signpulse/.env
systemctl restart tg-signpulse
```

### 数据库切换

**从 SQLite 迁移到 PostgreSQL：**

```bash
# 安装 PostgreSQL
apt install -y postgresql postgresql-client libpq-dev
systemctl start postgresql

# 创建数据库和用户
sudo -u postgres psql -c "CREATE USER tguser WITH PASSWORD 'yourpass';"
sudo -u postgres psql -c "CREATE DATABASE tg_signpulse OWNER tguser;"

# 迁移数据
pgloader sqlite:////data/tg-signpulse/db.sqlite postgresql://tguser:yourpass@localhost/tg_signpulse

# 配置应用
cd /opt/tg-signpulse
source venv/bin/activate
pip install -e ".[postgresql]"
echo 'DATABASE_URL=postgresql://tguser:yourpass@localhost:5432/tg_signpulse' >> .env
systemctl restart tg-signpulse
```

### 常用运维命令

```bash
systemctl start tg-signpulse      # 启动
systemctl stop tg-signpulse       # 停止
systemctl restart tg-signpulse    # 重启
systemctl status tg-signpulse     # 状态
journalctl -u tg-signpulse -f     # 实时日志
```

### 更新代码后重新构建

```bash
cd /opt/tg-signpulse
# 后端：直接重启即可（Python 热加载）
systemctl restart tg-signpulse

# 前端：需要重新构建
cd frontend && npm install && npx vite build && cp -r dist/* /web/
```

---

## 项目状态

> 🚫 **本项目已停止维护，不再更新。**
>
> - 不提供预构建镜像或任何形式的分发
> - 不接受新的 Issue 或 Pull Request
> - 代码仅供技术学习参考

---

## 技术栈

本项目涉及的技术栈，供学习参考：

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、Vue Router、Pinia、Tailwind CSS 4、Vite |
| 后端 | FastAPI、Uvicorn、SQLAlchemy、SQLite/PostgreSQL、APScheduler |
| 认证 | JWT、TOTP 2FA、bcrypt |
| AI 集成 | OpenAI SDK（API 调用示例） |
| 第三方 API | Pyrogram（Telegram MTProto 协议学习） |

---

## 学习要点

本项目可作为以下方向的学习参考：

1. **全栈项目结构** — 前后端分离的项目组织方式
2. **异步 Python** — FastAPI + asyncio 的实际应用
3. **任务调度** — APScheduler 在 Web 应用中的集成
4. **AI API 调用** — OpenAI 兼容接口的封装与使用
5. **认证系统** — JWT + 2FA 的实现方式
6. **状态管理** — Pinia 在 Vue 3 中的使用模式

---

## 免责声明

- 本项目仅用于 AI 编程技术学习与交流，不鼓励也不支持任何自动化滥用行为
- 作者不对任何人使用本代码产生的后果负责
- 本项目不提供任何形式的技术支持或部署服务
- 代码中涉及的第三方 API 调用仅作为技术示例，使用者需自行遵守相关服务条款

---

## 致谢

本项目的 Telegram 协议交互部分参考了 [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii)。

---

## License

[BSD-3-Clause](LICENSE)

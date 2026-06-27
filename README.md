# TG-Assistant

Telegram 多功能自动化助手 — 签到、转发、抢红包、Emby 保号一站管理。

## ✨ 功能

| 模块 | 说明 |
|------|------|
| 📊 **仪表盘** | 账号/任务/监听器/失败概览 |
| 👤 **账号管理** | 多 Telegram 账号登录、会话管理、状态检测 |
| ⚡ **任务编排** | 定时签到、AI 识图点击、自定义动作序列、多会话批量添加 |
| 📻 **监听器** | 独立于任务的实时消息监听系统 |
| → 📨 **秒转消息** | 正则匹配命中后原生转发，多账号多频道、去重、智能数值比对 |
| → 🧧 **抢红包** | 自动点击按钮 / 关键词抢包，数字提取、延迟回复、自定义模板 |
| 🎬 **Emby 保号** | 模拟播放会话保持 Emby 账号活跃，Bemby 同款 UA 预设 |
| 📋 **日志** | 任务日志 / 审计日志 / 监听日志 / Emby 日志，实时轮询 |
| ⚙ **系统设置** | Telegram API、Bot 通知、AI 模型、时区切换、配置导入导出 |

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / Uvicorn / SQLAlchemy / SQLite/PostgreSQL |
| 前端 | Vue 3 / Vite / TypeScript / Tailwind CSS |
| 调度 | APScheduler |
| Telegram | Pyrogram (MTProto) |
| AI | OpenAI 兼容接口 |
| 容器 | Docker 可选 |

## 🚀 快速部署

### 系统要求

- **操作系统**: Debian 11+ / Ubuntu 20.04+
- **内存**: 最低 512MB，推荐 1GB+
- **Python**: 3.10+
- **Node.js**: 20+ (仅构建前端时)

### 一键部署

```bash
# 1. 上传并解压
mkdir -p /root/tg-signpulse
tar -xzf tg-signpulse.tar.gz -C /root/tg-signpulse

# 2. 运行部署脚本
cd /root/tg-signpulse
chmod +x deploy.sh
sudo ./deploy.sh
```

访问 `http://服务器IP:8080`，管理员密码：
```bash
cat /data/tg-signpulse/.admin_bootstrap_password
```

### 使用 PostgreSQL

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/tg_signpulse"
sudo -E ./deploy.sh
```

### 配置 AI

Settings → AI 模型配置，或：

```bash
echo 'OPENAI_API_KEY=sk-xxx' >> /opt/tg-signpulse/.env
echo 'OPENAI_BASE_URL=https://api.openai.com/v1' >> /opt/tg-signpulse/.env
echo 'OPENAI_MODEL=gpt-4o' >> /opt/tg-signpulse/.env
systemctl restart tg-signpulse
```

### 配置 Emby 保号

Emby 保号页 → 添加任务 → 填写 Emby 服务器地址、用户名密码 → 选择 UA 预设 → 保存。

系统会每天在配置的时间窗口内随机执行一次模拟播放。

### 常用命令

```bash
systemctl start tg-signpulse     # 启动
systemctl stop tg-signpulse      # 停止
systemctl restart tg-signpulse   # 重启
systemctl status tg-signpulse    # 状态
journalctl -u tg-signpulse -f    # 实时日志
```

### 更新后重新构建

```bash
cd /opt/tg-signpulse
systemctl restart tg-signpulse

# 前端需重新构建
cd frontend && npm install && npx vite build && cp -r dist/* /web/
```

## 📄 许可证

MIT License

---

本项目是作者在学习 AI 辅助编程过程中的练手作品。

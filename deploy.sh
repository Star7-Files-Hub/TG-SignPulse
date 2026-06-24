#!/usr/bin/env bash
# ============================================================
# TG-SignPulse 一键部署脚本
# 适用: Ubuntu 20.04+ / Debian 11+ 的 1c1g 云服务器
# 用法: chmod +x deploy.sh && sudo ./deploy.sh
# ============================================================
set -euo pipefail

# ---- 配置区（可按需修改）----
APP_PORT="${APP_PORT:-8080}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_DATA_DIR="${APP_DATA_DIR:-/data/tg-signpulse}"
APP_TIMEZONE="${APP_TIMEZONE:-Asia/Shanghai}"
PROJECT_DIR="/opt/tg-signpulse"
SERVICE_NAME="tg-signpulse"
PYTHON_MIN_VERSION="3.10"
NODE_MIN_VERSION="20"
# ------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${BLUE}==== $* ====${NC}"; }

# ============================================================
# 0. 权限检查
# ============================================================
if [[ $EUID -ne 0 ]]; then
    log_error "请使用 root 权限运行: sudo ./deploy.sh"
    exit 1
fi

# ============================================================
# 1. 检测系统
# ============================================================
log_step "检测系统环境"

if ! command -v apt &>/dev/null; then
    log_error "此脚本仅支持 Debian/Ubuntu 系统"
    exit 1
fi

# 内存检查（友好提醒）
TOTAL_MEM=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
log_info "检测到内存: ${TOTAL_MEM}MB"
if [[ $TOTAL_MEM -lt 800 ]]; then
    log_warn "内存不足 800MB，部署后运行可能吃力，建议至少 1GB"
fi

# ============================================================
# 2. 安装系统依赖
# ============================================================
log_step "安装系统依赖"

apt update -qq
apt install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    build-essential \
    libssl-dev \
    libffi-dev \
    &>/dev/null

log_info "系统依赖安装完成"

# ============================================================
# 3. 检查/安装 Python
# ============================================================
log_step "检查 Python 版本"

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log_info "当前 Python 版本: $PYTHON_VERSION"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"; then
    log_error "需要 Python >= 3.10，当前版本: $PYTHON_VERSION"
    log_info "尝试安装 Python 3.10..."
    apt install -y -qq python3.10 python3.10-venv python3.10-dev &>/dev/null || {
        log_error "无法安装 Python 3.10，请手动升级系统或使用 Docker"
        exit 1
    }
    PYTHON_CMD="python3.10"
else
    PYTHON_CMD="python3"
fi

# ============================================================
# 4. 安装 Node.js（仅用于构建前端）
# ============================================================
log_step "检查/安装 Node.js (用于构建前端)"

NEED_NODE=false
if ! command -v node &>/dev/null; then
    NEED_NODE=true
else
    NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
    if [[ $NODE_VERSION -lt $NODE_MIN_VERSION ]]; then
        NEED_NODE=true
    fi
fi

if $NEED_NODE; then
    log_info "安装 Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - &>/dev/null
    apt install -y -qq nodejs &>/dev/null
    log_info "Node.js $(node -v) 安装完成"
else
    log_info "Node.js $(node -v) 已满足要求"
fi

# ============================================================
# 5. 部署项目文件
# ============================================================
log_step "部署项目文件"

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -d "$PROJECT_DIR" ]]; then
    log_warn "$PROJECT_DIR 已存在，将备份并覆盖"
    mv "$PROJECT_DIR" "${PROJECT_DIR}.bak.$(date +%Y%m%d%H%M%S)"
fi

log_info "复制项目文件到 $PROJECT_DIR ..."
cp -r "$SCRIPT_DIR" "$PROJECT_DIR"

# 排除不需要的文件以节省空间
rm -rf "$PROJECT_DIR/.git" 2>/dev/null || true
rm -rf "$PROJECT_DIR/__pycache__" 2>/dev/null || true
rm -rf "$PROJECT_DIR/.codebuddy" 2>/dev/null || true
rm -rf "$PROJECT_DIR/node_modules" 2>/dev/null || true

# ============================================================
# 6. 构建前端
# ============================================================
log_step "构建前端"

cd "$PROJECT_DIR/frontend"

log_info "安装前端依赖..."
npm install --silent

log_info "构建生产版本..."
npx vue-tsc -b 2>/dev/null && npx vite build || {
    log_warn "TypeScript 类型检查有警告，尝试跳过类型检查直接构建..."
    npx vite build
}

if [[ ! -d "$PROJECT_DIR/frontend/dist" ]]; then
    log_error "前端构建失败，未找到 dist 目录"
    exit 1
fi

log_info "前端构建完成"

# 复制前端产物到 /web（FastAPI 从此目录读取静态文件）
log_info "部署前端静态文件到 /web ..."
rm -rf /web 2>/dev/null || true
mkdir -p /web
cp -r "$PROJECT_DIR/frontend/dist/"* /web/
log_info "前端静态文件部署完成"

# 前端构建完成后可以清理 node_modules 节省空间
log_info "清理前端构建依赖以节省空间..."
rm -rf "$PROJECT_DIR/frontend/node_modules"
log_info "已清理 node_modules，释放了约 300MB 空间"

# ============================================================
# 7. 安装 Python 依赖
# ============================================================
log_step "安装 Python 依赖"

cd "$PROJECT_DIR"

log_info "创建 Python 虚拟环境..."
$PYTHON_CMD -m venv venv
source venv/bin/activate

log_info "升级 pip..."
pip install --upgrade pip -q

log_info "安装项目依赖（这可能需要几分钟）..."
pip install -e . -q

# 修复 bcrypt 与 passlib 的兼容性问题
# 新版 bcrypt 移除了 __about__ 属性，passlib 依赖它
log_info "修复 bcrypt/passlib 兼容性..."
pip install "bcrypt==4.0.1" -q

log_info "Python 依赖安装完成"
deactivate

# ============================================================
# 8. 创建数据目录
# ============================================================
log_step "创建数据目录"

mkdir -p "$APP_DATA_DIR"
mkdir -p "$APP_DATA_DIR/sessions"
mkdir -p "$APP_DATA_DIR/logs"

log_info "数据目录: $APP_DATA_DIR"

# ============================================================
# 9. 生成配置文件
# ============================================================
log_step "生成配置文件"

# 生成随机密钥
SECRET_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_urlsafe(48))")

cat > "$PROJECT_DIR/.env" << EOF
# TG-SignPulse 生产环境配置
APP_SECRET_KEY=$SECRET_KEY
APP_PORT=$APP_PORT
APP_HOST=$APP_HOST
APP_DATA_DIR=$APP_DATA_DIR
APP_TIMEZONE=$APP_TIMEZONE
APP_CORS_ALLOW_ORIGINS=http://localhost:$APP_PORT,http://127.0.0.1:$APP_PORT
EOF

log_info ".env 配置文件已生成"

# ============================================================
# 10. 创建 systemd 服务
# ============================================================
log_step "创建 systemd 服务"

# 获取运行用户（如果是 root 运行，创建一个专用用户）
if [[ "$SUDO_USER" && "$SUDO_USER" != "root" ]]; then
    APP_USER="$SUDO_USER"
else
    APP_USER="tg-signpulse"
    if ! id -u "$APP_USER" &>/dev/null; then
        useradd -r -s /usr/sbin/nologin -m "$APP_USER"
        log_info "创建专用用户: $APP_USER"
    fi
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=TG-SignPulse Service
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/uvicorn backend.main:app --host ${APP_HOST} --port ${APP_PORT} --workers 1 --log-level warning
Restart=always
RestartSec=5
StandardOutput=append:$APP_DATA_DIR/logs/app.log
StandardError=append:$APP_DATA_DIR/logs/error.log

# 安全加固
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DATA_DIR /web
ReadOnlyPaths=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF

# 确保用户有权限访问数据目录
chown -R "$APP_USER:$APP_USER" "$APP_DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$PROJECT_DIR"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

log_info "systemd 服务已创建: $SERVICE_NAME"

# ============================================================
# 11. 启动服务
# ============================================================
log_step "启动服务"

systemctl start "$SERVICE_NAME"

# 等待服务启动
sleep 3

# 检查服务状态
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log_info "服务启动成功!"
else
    log_error "服务启动失败，查看日志: journalctl -u $SERVICE_NAME -n 50"
    systemctl status "$SERVICE_NAME" --no-pager || true
    exit 1
fi

# 等待应用就绪（最多等 30 秒）
log_info "等待应用就绪..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${APP_PORT}/readyz" 2>/dev/null | grep -q "ready"; then
        log_info "应用已就绪"
        break
    fi
    if [[ $i -eq 30 ]]; then
        log_warn "应用可能还在启动中，请稍后访问"
    fi
    sleep 1
done

# ============================================================
# 12. 部署完成
# ============================================================
log_step "部署完成!"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           TG-SignPulse 部署成功!                        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  访问地址:  ${BLUE}http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'YOUR_IP'):${APP_PORT}${NC}"
echo -e "${GREEN}║${NC}  项目目录:  ${PROJECT_DIR}"
echo -e "${GREEN}║${NC}  数据目录:  ${APP_DATA_DIR}"
echo -e "${GREEN}║${NC}  前端文件:  /web"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  常用命令:                                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  systemctl start ${SERVICE_NAME}     # 启动服务          ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  systemctl stop ${SERVICE_NAME}      # 停止服务          ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  systemctl restart ${SERVICE_NAME}   # 重启服务          ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  systemctl status ${SERVICE_NAME}    # 查看状态          ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  journalctl -u ${SERVICE_NAME} -f    # 实时日志          ${GREEN}║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  默认管理员账户将在首次启动时自动创建                    ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  请查看日志获取初始密码:                                ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  grep -i 'admin' ${APP_DATA_DIR}/logs/app.log            ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 尝试输出初始管理员信息
log_info "检查初始管理员账户..."
sleep 2
grep -i 'admin' "$APP_DATA_DIR/logs/app.log" 2>/dev/null | tail -5 || log_warn "未找到管理员信息，请稍后查看日志"

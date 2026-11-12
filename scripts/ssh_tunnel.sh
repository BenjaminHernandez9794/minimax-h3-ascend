#!/bin/bash

# ================= 配置区域 =================
# 可直接改下面的默认值，也可用同名环境变量覆盖（推荐用环境变量传密码，避免把密码提交进仓库）:
#   REMOTE_HOST=1.2.3.4 REMOTE_PASS=xxx bash scripts/ssh_tunnel.sh start
REMOTE_USER="${REMOTE_USER:-root}"               # 公网服务器用户名
REMOTE_HOST="${REMOTE_HOST:-x.x.x.x}"            # 公网服务器 IP 或域名
SSH_PORT="${SSH_PORT:-22}"                       # 公网服务器 SSH 端口
REMOTE_PASS="${REMOTE_PASS:-你的实际密码}"        # 公网服务器 SSH 密码
REMOTE_BIND_PORT="${REMOTE_BIND_PORT:-18188}"    # 公网服务器暴露的端口
LOCAL_PORT="${LOCAL_PORT:-8188}"                 # 容器本地服务端口 (如 ComfyUI)
LOG_FILE="${LOG_FILE:-./ssh_tunnel.log}"         # 日志保存路径
# ============================================

# 自动检测并安装缺失的依赖工具 (ssh / sshpass)
check_and_install_dependencies() {
    local missing_pkgs=()

    if ! command -v ssh >/dev/null 2>&1; then
        missing_pkgs+=("ssh")
    fi
    if ! command -v sshpass >/dev/null 2>&1; then
        missing_pkgs+=("sshpass")
    fi

    if [ ${#missing_pkgs[@]} -eq 0 ]; then
        return 0
    fi

    echo "[依赖检查] 缺少工具: ${missing_pkgs[*]}，准备自动安装..."

    # 识别系统包管理器并自动安装
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq && apt-get install -y -qq openssh-client sshpass
    elif command -v yum >/dev/null 2>&1; then
        yum install -y epel-release 2>/dev/null || true
        yum install -y openssh-clients sshpass
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y epel-release 2>/dev/null || true
        dnf install -y openssh-clients sshpass
    elif command -v apk >/dev/null 2>&1; then
        apk update && apk add openssh-client sshpass
    else
        echo "[错误] 未识别的包管理器，请手动安装: ${missing_pkgs[*]}"
        exit 1
    fi

    # 二次验证是否安装成功
    if ! command -v ssh >/dev/null 2>&1 || ! command -v sshpass >/dev/null 2>&1; then
        echo "[失败] 依赖安装未能成功，请检查容器网络或源配置。"
        exit 1
    fi
    echo "[成功] 依赖工具安装完成！"
}

# 组合 SSH 穿透命令
SSH_CMD="sshpass -p '${REMOTE_PASS}' ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -R 0.0.0.0:${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT} -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_HOST}"

start_tunnel() {
    if [ "$REMOTE_HOST" = "x.x.x.x" ] || [ "$REMOTE_PASS" = "你的实际密码" ]; then
        echo "[错误] 请先设置 REMOTE_HOST 和 REMOTE_PASS（改脚本配置区域或用环境变量）"
        exit 1
    fi
    # 启动前必须确保依赖齐备
    check_and_install_dependencies

    PID=$(pgrep -f "StrictHostKeyChecking=no -o ServerAliveInterval=30.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}")
    if [ -n "$PID" ]; then
        echo "[提示] 隧道已经在运行中 (PID: $PID)"
        return
    fi

    echo "[启动] 正在建立 SSH 反向隧道..."
    nohup bash -c "
        while true; do
            echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] 隧道启动/连接中...\" >> ${LOG_FILE}
            ${SSH_CMD} >> ${LOG_FILE} 2>&1
            echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] 隧道断开，5秒后尝试重连...\" >> ${LOG_FILE}
            sleep 5
        done
    " > /dev/null 2>&1 &

    sleep 1
    echo "[成功] 隧道守护进程已在后台运行！"
    echo "本地服务: 127.0.0.1:${LOCAL_PORT} -> 公网访问: http://${REMOTE_HOST}:${REMOTE_BIND_PORT}"
    echo "查看实时日志命令: tail -f ${LOG_FILE}"
}

stop_tunnel() {
    echo "[停止] 正在关闭隧道..."
    pkill -f "StrictHostKeyChecking=no -o ServerAliveInterval=30.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}"
    pkill -f "sshpass -p"
    pkill -f "${LOG_FILE}"
    echo "[完成] 隧道已关闭。"
}

status_tunnel() {
    PID=$(pgrep -f "StrictHostKeyChecking=no -o ServerAliveInterval=30.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}")
    if [ -n "$PID" ]; then
        echo "[运行中] 隧道正常工作 (PID: $PID)"
    else
        echo "[未运行] 隧道未启动"
    fi
}

case "$1" in
    start)
        start_tunnel
        ;;
    stop)
        stop_tunnel
        ;;
    restart)
        stop_tunnel
        sleep 1
        start_tunnel
        ;;
    status)
        status_tunnel
        ;;
    *)
        echo "使用方法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
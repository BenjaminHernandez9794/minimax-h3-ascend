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
# 国内容器的默认 apt/yum 源（archive/ports.ubuntu.com 等）常年卡住，且 -qq 会把输出全吞掉，看起来像没反应。
# 这里给每步加超时并显示进度；默认源超时就自动换华为云镜像（APT_MIRROR 可改）再试一次。
APT_MIRROR="${APT_MIRROR:-http://repo.huaweicloud.com}"   # 用 http：精简镜像可能没装 ca-certificates
PKG_TIMEOUT="${PKG_TIMEOUT:-120}"   # 每步最长秒数

_apt_install() {
    local opts=(-o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o Acquire::Retries=1)
    export DEBIAN_FRONTEND=noninteractive
    echo "  apt-get update（最多 ${PKG_TIMEOUT}s）..."
    if timeout "$PKG_TIMEOUT" apt-get "${opts[@]}" update && \
       timeout "$PKG_TIMEOUT" apt-get "${opts[@]}" install -y --no-install-recommends openssh-client sshpass; then
        return 0
    fi
    echo "  默认源不通或太慢，切换到 ${APT_MIRROR} 再试（原配置备份为 *.bak-tunnel）"
    local f
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
        [ -f "$f" ] || continue
        [ -f "$f.bak-tunnel" ] || cp "$f" "$f.bak-tunnel"
        sed -i -E \
            -e "s#https?://([a-z0-9.-]+\.)?(archive|security|ports)\.ubuntu\.com/ubuntu(-ports)?#${APT_MIRROR}/ubuntu\3#g" \
            -e "s#https?://(deb|security)\.debian\.org/debian(-security)?#${APT_MIRROR}/debian\2#g" \
            -e "s#https?://mirrors\.[a-z0-9.-]+/ubuntu(-ports)?#${APT_MIRROR}/ubuntu\1#g" \
            "$f"
    done
    timeout "$PKG_TIMEOUT" apt-get "${opts[@]}" update && \
    timeout "$PKG_TIMEOUT" apt-get "${opts[@]}" install -y --no-install-recommends openssh-client sshpass
}

_yum_install() {  # $1 = yum 或 dnf（openEuler / CentOS / 麒麟）
    local pm=$1
    echo "  $pm install（最多 ${PKG_TIMEOUT}s）..."
    timeout "$PKG_TIMEOUT" "$pm" install -y openssh-clients sshpass && return 0
    # openEuler 等没有 epel 也能直接装；CentOS 才需要 epel
    timeout "$PKG_TIMEOUT" "$pm" install -y epel-release >/dev/null 2>&1 || true
    timeout "$PKG_TIMEOUT" "$pm" install -y openssh-clients sshpass
}

check_and_install_dependencies() {
    local missing_pkgs=()
    command -v ssh >/dev/null 2>&1 || missing_pkgs+=("ssh")
    command -v sshpass >/dev/null 2>&1 || missing_pkgs+=("sshpass")
    [ ${#missing_pkgs[@]} -eq 0 ] && return 0

    echo "[依赖检查] 缺少工具: ${missing_pkgs[*]}，准备自动安装..."
    if [ "$(id -u)" != 0 ]; then
        if command -v ssh >/dev/null 2>&1; then
            echo "[提示] 非 root 无法装 sshpass，改用 ssh 自带的 SSH_ASKPASS 传密码（需 OpenSSH ≥ 8.4）"
            return 0
        fi
        echo "[错误] 安装系统包需要 root，请用 root 运行或手动安装: openssh-client sshpass"
        exit 1
    fi
    if command -v apt-get >/dev/null 2>&1; then
        _apt_install
    elif command -v dnf >/dev/null 2>&1; then
        _yum_install dnf
    elif command -v yum >/dev/null 2>&1; then
        _yum_install yum
    elif command -v apk >/dev/null 2>&1; then
        timeout "$PKG_TIMEOUT" apk add openssh-client sshpass
    else
        echo "[错误] 未识别的包管理器，请手动安装: ${missing_pkgs[*]}"
        exit 1
    fi

    if ! command -v ssh >/dev/null 2>&1; then
        echo "[失败] ssh 没装上，请检查容器网络或系统源（可设 APT_MIRROR=镜像地址 再试）。"
        exit 1
    fi
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "[提示] sshpass 没装上，改用 ssh 自带的 SSH_ASKPASS 传密码（需 OpenSSH ≥ 8.4）"
    else
        echo "[成功] 依赖工具安装完成！"
    fi
}

# 组合 SSH 穿透命令
SSH_OPTS="-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o ConnectTimeout=15 -N -R 0.0.0.0:${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT} -p ${SSH_PORT} ${REMOTE_USER}@${REMOTE_HOST}"
build_ssh_cmd() {
    # 密码通过环境变量 TUNNEL_PW 传给子进程，不出现在命令行（ps 里看不到）
    if command -v sshpass >/dev/null 2>&1; then
        SSH_CMD="sshpass -e ssh ${SSH_OPTS}"
    else
        ASKPASS_FILE="${ASKPASS_FILE:-/tmp/.ssh_tunnel_askpass.sh}"
        printf '#!/bin/sh\nprintf "%%s\\n" "$SSHPASS"\n' > "$ASKPASS_FILE"; chmod 700 "$ASKPASS_FILE"
        SSH_CMD="SSH_ASKPASS='${ASKPASS_FILE}' SSH_ASKPASS_REQUIRE=force DISPLAY=:0 setsid -w ssh ${SSH_OPTS} </dev/null"
    fi
}

start_tunnel() {
    if [ "$REMOTE_HOST" = "x.x.x.x" ] || [ "$REMOTE_PASS" = "你的实际密码" ]; then
        echo "[错误] 请先设置 REMOTE_HOST 和 REMOTE_PASS（改脚本配置区域或用环境变量）"
        exit 1
    fi
    # 启动前必须确保依赖齐备
    check_and_install_dependencies
    build_ssh_cmd

    PID=$(pgrep -f "ExitOnForwardFailure=yes.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}")
    if [ -n "$PID" ]; then
        echo "[提示] 隧道已经在运行中 (PID: $PID)"
        return
    fi

    echo "[启动] 正在建立 SSH 反向隧道..."
    SSHPASS="$REMOTE_PASS" nohup bash -c "
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
    pkill -f "ExitOnForwardFailure=yes.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}"
    pkill -f "sshpass -e ssh .*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}"
    echo "[完成] 隧道已关闭。"
}

status_tunnel() {
    PID=$(pgrep -f "ExitOnForwardFailure=yes.*${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}")
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
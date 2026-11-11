# shellcheck shell=bash
# 由 setup.sh / scripts/install_nodes.sh source。
# pip_install <pip install 的参数...>：优先用 uv（并行下载 + 并行安装，比 pip 快很多），失败自动回退 pip。
#   USE_UV=0          关闭 uv，全程用 pip
#   UV_AUTO_INSTALL=0 机器上没有 uv 时不自动安装，直接用 pip（默认 1：自动 pip install uv）
#   PIP_MIRROR        uv 自举安装时用的源（各命令自己的 -i / --index-url 照常生效）
# 以下情况直接用 pip：没装上 uv、参数里有 --user（uv 不支持）、当前 Python 的 site-packages 不可写。

USE_UV="${USE_UV:-1}"
UV_AUTO_INSTALL="${UV_AUTO_INSTALL:-1}"
UV_CMD=()
_UV_READY=0

_py_site_writable() {
    python3 -c 'import os,sys,sysconfig; sys.exit(0 if (sys.prefix != sys.base_prefix or os.access(sysconfig.get_paths()["purelib"], os.W_OK)) else 1)' >/dev/null 2>&1
}

uv_init() {
    [ "$_UV_READY" = 1 ] && return 0
    _UV_READY=1
    [ "$USE_UV" = 0 ] && { echo "USE_UV=0：使用 pip 安装依赖"; return 0; }
    if command -v uv >/dev/null 2>&1; then
        UV_CMD=("$(command -v uv)")
    elif python3 -m uv --version >/dev/null 2>&1; then
        UV_CMD=(python3 -m uv)
    elif [ "$UV_AUTO_INSTALL" = 0 ]; then
        echo "未检测到 uv，且已关闭自动安装（UV_AUTO_INSTALL=0 / --no-install-uv），使用 pip"
    else
        echo "未检测到 uv，自动安装（不想装可加 --no-install-uv 或 UV_AUTO_INSTALL=0）..."
        local mirror="${PIP_MIRROR:-https://repo.huaweicloud.com/repository/pypi/simple}" extra=()
        _py_site_writable || extra=(--user)
        if python3 -m pip install -q --prefer-binary --timeout 60 --retries 3 ${extra[@]+"${extra[@]}"} -i "$mirror" uv >/dev/null 2>&1 \
            && python3 -m uv --version >/dev/null 2>&1; then
            UV_CMD=(python3 -m uv)
        fi
    fi
    if [ ${#UV_CMD[@]} -gt 0 ]; then
        echo "使用 $("${UV_CMD[@]}" --version 2>/dev/null) 安装依赖（失败会自动改用 pip）"
    else
        [ "$UV_AUTO_INSTALL" = 0 ] || echo "uv 不可用，使用 pip 安装依赖"
    fi
}

pip_install() {
    uv_init
    local a use_uv=1 timeout=60 uv_args=()
    [ ${#UV_CMD[@]} -gt 0 ] || use_uv=0
    _py_site_writable || use_uv=0
    # 把 pip 专有参数翻译 / 去掉，其余（-i/--index-url/-c/-r/-U/--no-deps/-q）uv 原样支持
    local args=("$@") i=0
    while [ $i -lt ${#args[@]} ]; do
        a="${args[$i]}"
        case "$a" in
            --user) use_uv=0 ;;
            --prefer-binary) ;;
            --timeout) i=$((i+1)); timeout="${args[$i]}" ;;
            --retries) i=$((i+1)) ;;
            --timeout=*) timeout="${a#--timeout=}" ;;
            --retries=*) ;;
            *) uv_args+=("$a") ;;
        esac
        i=$((i+1))
    done
    if [ "$use_uv" = 1 ]; then
        # UV_LINK_MODE=copy：缓存和环境常在不同磁盘，硬链接失败时避免刷警告
        if UV_LINK_MODE="${UV_LINK_MODE:-copy}" UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-$timeout}" \
            "${UV_CMD[@]}" pip install --python "$(command -v python3)" "${uv_args[@]}"; then
            return 0
        fi
        echo "  (uv 安装失败，改用 pip 重试)"
    fi
    python3 -m pip install "$@"
}

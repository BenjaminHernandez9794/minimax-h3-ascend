#!/usr/bin/env bash
# MiniMax-H3 on Ascend —— ComfyUI 启动脚本（自适应 910B/910C，卡数自动识别）
# 用法: bash scripts/start_comfyui.sh          # 前台运行，日志实时输出到终端，同时追加写入日志文件；Ctrl+C 停止
#       bash scripts/start_comfyui.sh -d       # 后台运行（nohup），日志只写文件，用 tail -f 查看
# 环境变量: COMFY_HOME(默认取 setup.sh 记下的目录，否则 /mnt/workspace/ComfyUI)  COMFYUI_PORT(默认 8188)  NPU_DEVICES(可手动指定)
#           DAEMON=1 等同 -d；LOWVRAM=1 / NORMALVRAM=1 显存模式
set -euo pipefail

DAEMON="${DAEMON:-0}"
for a in "$@"; do
    case "$a" in
        -d|--daemon|--background) DAEMON=1 ;;
        -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "!! 未知参数: $a（可用 -d / --daemon）"; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFY_HOME="${COMFY_HOME:-$(cat "$REPO_DIR/.comfy_home" 2>/dev/null || true)}"
COMFY_HOME="${COMFY_HOME:-/mnt/workspace/ComfyUI}"
PORT="${COMFYUI_PORT:-8188}"
RUNTIME="${COMFY_RUNTIME_DIR:-/mnt/workspace/runtime}"
PID_FILE="$RUNTIME/comfyui-$PORT.pid"
LOG_FILE="$RUNTIME/comfyui-$PORT.log"
mkdir -p "$RUNTIME"

# --- 已在运行则先停 ---
if [ -s "$PID_FILE" ]; then
    old=$(cat "$PID_FILE")
    if kill -0 "$old" 2>/dev/null; then
        echo "停止旧服务 PID=$old"
        kill "$old" || true
        for _ in $(seq 1 15); do kill -0 "$old" 2>/dev/null || break; sleep 1; done
        kill -0 "$old" 2>/dev/null && { echo "旧服务未退出，强制结束"; kill -9 "$old" || true; }
    fi
    rm -f "$PID_FILE"
fi

# --- CANN ---
ASCEND_HOME=""
for p in /usr/local/Ascend/ascend-toolkit "$HOME/Ascend/ascend-toolkit" /home/*/Ascend/ascend-toolkit; do
    [ -f "$p/set_env.sh" ] && ASCEND_HOME="$p" && break
done
[ -z "$ASCEND_HOME" ] && { echo "!! 未找到 CANN"; exit 1; }
set +u; source "$ASCEND_HOME/set_env.sh"; set -u

# --- 卡数自适应 ---
if [ -z "${NPU_DEVICES:-}" ]; then
    n=$( (ls -d /dev/davinci[0-9]* 2>/dev/null || true) | wc -l)
    [ "$n" -ge 4 ] && n=4 || true
    [ "$n" -ge 8 ] && n=8 || true
    NPU_DEVICES=$(seq -s, 0 $(( (n>0?n:1) - 1 )))
fi
export ASCEND_RT_VISIBLE_DEVICES="$NPU_DEVICES"
echo "使用 NPU: $NPU_DEVICES"

# --- aarch64 关键修复：预加载原生库，避免“静态 TLS 块耗尽”报错 ---
#   libGLdispatch: opencv(cv2) 在 torch_npu 之后再 import 时会报
#     "libGLdispatch.so.0: cannot allocate memory in static TLS block"
#     ——因为 torch_npu 等先加载占满了静态 TLS，cv2 的 libGLdispatch 再 dlopen 就没槽了。
#     连带弄挂所有 import cv2 的节点：ComfyUI_LayerStyle、ComfyUI-Easy-Use，
#     以及孤海里 GH_MaskCropV2 / GH_CropRestore / TextEncodeQwenImage21GH 等节点。
#   libgomp: torchaudio/numpy 的同类 TLS 报错。
#   预加载让它们在进程启动时（静态 TLS 还够）就拿到槽位。GLdispatch 放最前。
PRELOAD="${LD_PRELOAD:-}"
for _name in libGLdispatch.so.0 libgomp.so.1; do
    for _dir in /lib/aarch64-linux-gnu /usr/lib/aarch64-linux-gnu /lib /usr/lib; do
        if [ -f "$_dir/$_name" ]; then
            PRELOAD="${PRELOAD:+$PRELOAD:}$_dir/$_name"
            break
        fi
    done
done
[ -n "$PRELOAD" ] && export LD_PRELOAD="$PRELOAD"

export HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"
# INT8 线性层: 1 = 补丁内置 npu_quant_matmul 路径 (910B 实测)；0 = 交给 comfy-kitchen 原生 Ascend 后端
export COMFY_NPU_INT8_PATCH="${COMFY_NPU_INT8_PATCH:-1}"
export COMFYUI_MULTI_DEVICE_BACKEND="${COMFYUI_MULTI_DEVICE_BACKEND:-auto}"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy || true

# --- 同步工作流里的 npu_count（避免校验失败）---
python3 "$(dirname "$0")/set_npu_count.py" "$NPU_DEVICES" 2>/dev/null || true

# --- 显存模式 ---
ARGS="--listen 0.0.0.0 --port $PORT --disable-auto-launch --cache-classic"
if [ "${LOWVRAM:-0}" = "1" ]; then
    echo "低显存模式 (--lowvram)：模型逐层卸载到内存，慢但 32GB 卡也能跑"
    ARGS="$ARGS --lowvram"
fi
if [ "${NORMALVRAM:-0}" = "1" ]; then
    ARGS="$ARGS --normalvram"
fi

export PYTHONUNBUFFERED=1   # 日志不缓冲，实时可见
cd "$COMFY_HOME"
echo "日志文件: $LOG_FILE"
echo "访问地址: http://<本机IP>:$PORT"
if [ "$DAEMON" = "1" ]; then
    nohup python3 main.py $ARGS >> "$LOG_FILE" 2>&1 < /dev/null &
    echo "$!" > "$PID_FILE"
    echo "已在后台启动 PID=$!；查看日志: tail -f $LOG_FILE"
    exit 0
fi
echo "前台运行，Ctrl+C 停止（需要后台运行请加 -d）"
echo "===== $(date '+%F %T') 启动 =====" >> "$LOG_FILE"
echo "$$" > "$PID_FILE"
# 终端与日志文件同时输出
exec > >(tee -a "$LOG_FILE") 2>&1
exec python3 main.py $ARGS

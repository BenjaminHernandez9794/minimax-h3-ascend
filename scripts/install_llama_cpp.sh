#!/usr/bin/env bash
# 在没有官方 wheel 的机器上（如昇腾 910B 的 Linux aarch64）从源码编译 llama-cpp-python（CPU 版）。
# 孤海「Qwen image 2.1 提示词优化」节点要用它跑 PE 模型（要求 JamePeng 分支 >= 0.3.48，PyPI 上的版本太旧）。
#
# 用法: bash scripts/install_llama_cpp.sh [--ref TAG|分支] [--jobs N] [--force] [--gh-proxy URL]
#   --ref      JamePeng/llama-cpp-python 的 tag 或分支，默认 main
#   --jobs N   并行编译数，默认 CPU 核数
#   --force    已安装且版本够新也重新编译
#   环境变量: PIP_MIRROR、GH_PROXY、LLAMA_CMAKE_ARGS（追加给 CMake）、LLAMA_NATIVE=1（aarch64 改用 -mcpu=native）、PYTHON（默认 python3）、BUILD_DIR（默认 /tmp/llama-cpp-build）
#
# 只用 CPU 推理（llama.cpp 不支持昇腾 NPU），9B 级别的 Q5 模型生成一段提示词大约要几十秒，具体取决于 CPU 核数。
set -euo pipefail

REF="main"; JOBS="$(nproc 2>/dev/null || echo 4)"; FORCE=0
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
    case "$1" in
        --ref)        REF="${2:?--ref 需要一个值}"; shift 2 ;;
        --jobs)       JOBS="${2:?--jobs 需要一个数字}"; shift 2 ;;
        --force)      FORCE=1; shift ;;
        --gh-proxy)   GH_PROXY="${2:?--gh-proxy 需要一个地址}"; shift 2 ;;
        --gh-proxy=*) GH_PROXY="${1#*=}"; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "!! 未知参数: $1"; usage; exit 1 ;;
    esac
done

PY="${PYTHON:-python3}"
MIN_VER="0.3.48"
REPO_URL="https://github.com/JamePeng/llama-cpp-python.git"
SUB_URL="https://github.com/ggml-org/llama.cpp.git"
BUILD_DIR="${BUILD_DIR:-/tmp/llama-cpp-build}"
if [ -n "${PIP_MIRROR:-}" ]; then PIP_MIRROR_FROM="环境变量 PIP_MIRROR"; else PIP_MIRROR_FROM="默认"; fi
PIP_MIRROR="${PIP_MIRROR:-https://repo.huaweicloud.com/repository/pypi/simple}"
echo "Python: $($PY -c 'import sys;print(sys.executable, sys.version.split()[0])')"
echo "Python 包源: $PIP_MIRROR（$PIP_MIRROR_FROM）"

# 1. 已装且够新、并且能 import Qwen35ChatHandler 就跳过
if [ "$FORCE" = 0 ] && $PY - "$MIN_VER" <<'EOF' 2>/dev/null
import sys, importlib.metadata as m, re
v = m.version("llama-cpp-python")
t = lambda s: tuple(int(x) for x in re.findall(r"\d+", s)[:3])
assert t(v) >= t(sys.argv[1]), v
from llama_cpp.llama_chat_format import Qwen35ChatHandler  # noqa
import diskcache  # noqa
print("已安装 llama-cpp-python", v, "，跳过（--force 强制重编）")
EOF
then exit 0; fi

# 2. 编译工具：gcc/g++、cmake、git
need=()
command -v gcc >/dev/null || need+=(gcc)
command -v g++ >/dev/null || need+=(g++)
command -v git >/dev/null || need+=(git)
command -v ar  >/dev/null || need+=(ar)   # binutils
if [ ${#need[@]} -gt 0 ]; then
    echo "缺少: ${need[*]}，尝试安装..."
    SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo -n"
    if command -v apt-get >/dev/null; then
        timeout 300 $SUDO apt-get -o Acquire::http::Timeout=15 update || true
        timeout 600 $SUDO apt-get install -y --no-install-recommends gcc g++ make git binutils || true
    elif command -v dnf >/dev/null; then timeout 600 $SUDO dnf install -y gcc gcc-c++ make git binutils || true
    elif command -v yum >/dev/null; then timeout 600 $SUDO yum install -y gcc gcc-c++ make git binutils || true
    fi
    for t in gcc g++ git ar; do command -v "$t" >/dev/null || { echo "!! 仍然没有 $t，请先手动安装（如 apt-get install gcc g++ git）"; exit 1; }; done
fi
echo "编译器: $(gcc --version | head -1)"

PIP=($PY -m pip install --prefer-binary --timeout 60 --retries 3 -i "$PIP_MIRROR")
# cmake/ninja 用 pip 装最省事（系统 cmake 可能太旧）
if ! command -v cmake >/dev/null || ! $PY - <<'EOF' 2>/dev/null
import subprocess, re
v = re.search(r"(\d+)\.(\d+)", subprocess.check_output(["cmake", "--version"], text=True)).groups()
assert tuple(map(int, v)) >= (3, 21)
EOF
then "${PIP[@]}" cmake ninja; fi
"${PIP[@]}" "scikit-build-core[pyproject]>=0.9.2" diskcache "jinja2>=3.1.0" "typing-extensions>=4.8.0" Pillow

# 3. 拉源码（含 llama.cpp 子模块），可走 GH_PROXY
GH_PROXY="${GH_PROXY:-}"; GH_PROXY="${GH_PROXY%/}"
if [ -n "$GH_PROXY" ] && [[ "$GH_PROXY" != http://* && "$GH_PROXY" != https://* ]]; then GH_PROXY="https://$GH_PROXY"; fi
GITC=(git)
if [ -n "$GH_PROXY" ]; then
    if timeout 30 git ls-remote --heads "$GH_PROXY/$REPO_URL" >/dev/null 2>&1; then
        GITC=(git -c "url.$GH_PROXY/https://github.com/.insteadOf=https://github.com/")
        echo "GitHub 代理: $GH_PROXY"
    else echo "!! 代理 $GH_PROXY 不可用，改为直连"; fi
fi
SRC="$BUILD_DIR/llama-cpp-python"
rm -rf "$SRC"; mkdir -p "$BUILD_DIR"
echo "--- 下载 JamePeng/llama-cpp-python ($REF)"
"${GITC[@]}" clone --depth 1 --branch "$REF" "$REPO_URL" "$SRC"
"${GITC[@]}" -C "$SRC" submodule update --init --depth 1 vendor/llama.cpp

# 4. 编译安装。aarch64 按 /proc/cpuinfo 实际支持的指令集拼 -march（-mcpu=native 在部分编译器上会多开指令，
#    运行时报 Illegal instruction）；鲲鹏 920 一般得到 armv8.2-a+dotprod+fp16。LLAMA_NATIVE=1 改回 GGML_NATIVE。
ARCH_ARGS="-DGGML_NATIVE=ON"
if [ "$(uname -m)" = aarch64 ] && [ "${LLAMA_NATIVE:-0}" != 1 ]; then
    feats=" $(grep -m1 -i '^Features' /proc/cpuinfo | cut -d: -f2) "
    march="armv8.2-a"
    [[ "$feats" == *" asimdhp "* ]] && march+="+fp16"
    [[ "$feats" == *" asimddp "* ]] && march+="+dotprod"
    [[ "$feats" == *" i8mm "* ]]    && march+="+i8mm"
    ARCH_ARGS="-DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=$march"
fi
export CMAKE_ARGS="$ARCH_ARGS -DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_BLAS=OFF -DLLAMA_CURL=OFF ${LLAMA_CMAKE_ARGS:-}"
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"
echo "--- 编译（$JOBS 线程，CMAKE_ARGS=$CMAKE_ARGS），大约 10~20 分钟"
# 依赖已单独装好；本体用 --no-deps，避免 numpy<=2.3.2 的上限去动已装的 numpy（ComfyUI / torch_npu 依赖固定版本）
$PY -c "import numpy" 2>/dev/null || "${PIP[@]}" "numpy>=1.21.6,<=2.3.2"
LOG="$BUILD_DIR/build.log"
if ! "${PIP[@]}" --no-deps --no-build-isolation -v "$SRC" > "$LOG" 2>&1; then
    grep -E 'FAILED|error:|fatal|not found|ERROR' "$LOG" | grep -v -- '-Werror' | tail -20
    echo "!! 编译失败，完整日志: $LOG"; exit 1
fi
grep -E '^\s*\[[0-9]+/[0-9]+\]' "$LOG" | tail -1 || true

# 5. 自检
$PY - <<'EOF'
import importlib.metadata as m
import llama_cpp
from llama_cpp.llama_chat_format import Qwen35ChatHandler  # noqa
print("OK: llama-cpp-python", m.version("llama-cpp-python"), "| system_info:", llama_cpp.llama_print_system_info().decode()[:160])
EOF
echo "完成。重启 ComfyUI 后，把「Qwen image 2.1 提示词优化」节点取消绕过（Ctrl+B）即可使用。"
rm -rf "$SRC"

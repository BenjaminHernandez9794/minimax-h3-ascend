#!/usr/bin/env bash
# =============================================================
# MiniMax-H3 on Ascend 一键部署脚本
# 适用: CANNLab / 昇腾 910B / 910C 容器与环境
# 用法: bash setup.sh [--comfy-home DIR] [--gh-proxy URL] [--profile latest|legacy] [--nodes LIST]
#   --comfy-home DIR ComfyUI 安装目录（默认 /mnt/workspace/ComfyUI，也可用环境变量 COMFY_HOME）；
#                   会记到仓库里的 .comfy_home，之后下载模型/装节点/启动脚本自动沿用
#   --gh-proxy URL  GitHub 加速代理（前缀式，如 https://gp.1314510.xyz），
#                   拉取时用 URL/https://github.com/...；也可用环境变量 GH_PROXY
#   没有 torch / torch_npu 时按 CANN 版本自动装配套版本（默认 torch 2.7.1，TORCH_VERSION 可改）
#   --nodes LIST    顺带安装额外自定义节点（逗号分隔，也可用环境变量 CUSTOM_NODES），如
#                   qwen21 / qwen21-full / goohai,rgthree；详见 bash scripts/install_nodes.sh --list
# =============================================================
set -euo pipefail

usage() { sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
    case "$1" in
        --gh-proxy)   GH_PROXY="${2:?--gh-proxy 需要一个地址}"; shift 2 ;;
        --gh-proxy=*) GH_PROXY="${1#*=}"; shift ;;
        --profile)    COMFY_PROFILE="${2:?--profile 需要 latest 或 legacy}"; shift 2 ;;
        --profile=*)  COMFY_PROFILE="${1#*=}"; shift ;;
        --comfy-home)   COMFY_HOME="${2:?--comfy-home 需要一个目录}"; shift 2 ;;
        --comfy-home=*) COMFY_HOME="${1#*=}"; shift ;;
        --nodes)      CUSTOM_NODES="${2:?--nodes 需要节点列表}"; shift 2 ;;
        --nodes=*)    CUSTOM_NODES="${1#*=}"; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "!! 未知参数: $1"; usage; exit 1 ;;
    esac
done
GH_PROXY="${GH_PROXY:-}"
GH_PROXY="${GH_PROXY%/}"
if [ -n "$GH_PROXY" ] && [[ "$GH_PROXY" != http://* && "$GH_PROXY" != https://* ]]; then
    GH_PROXY="https://$GH_PROXY"
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ComfyUI 目录：--comfy-home / COMFY_HOME > 上次记下的 .comfy_home > 默认 /mnt/workspace/ComfyUI
COMFY_HOME="${COMFY_HOME:-$(cat "$REPO_DIR/.comfy_home" 2>/dev/null || true)}"
COMFY_HOME="${COMFY_HOME:-/mnt/workspace/ComfyUI}"
COMFY_HOME="${COMFY_HOME/#\~/$HOME}"
mkdir -p "$(dirname "$COMFY_HOME")"
COMFY_HOME="$(cd "$(dirname "$COMFY_HOME")" && pwd)/$(basename "$COMFY_HOME")"
echo "$COMFY_HOME" > "$REPO_DIR/.comfy_home"
echo "ComfyUI 目录: $COMFY_HOME"
# COMFY_PROFILE 选择 ComfyUI 版本与对应补丁:
#   latest (默认): ComfyUI 61e524bd (v0.44.0 之后 37 个提交, 2026-11) + 重新 rebase 的补丁
#   legacy       : ComfyUI bd34f338 (v0.32.0, 2026-08) + 原始 Ascend-SACT 补丁 (910B 已实测)
COMFY_PROFILE="${COMFY_PROFILE:-latest}"
case "$COMFY_PROFILE" in
    latest)
        COMFY_COMMIT="61e524bdba7a4e193b45c2697f1af83c1beb86d6"
        DEFAULT_BRANCH="ascend-npu-v0.44"
        PATCH_FILE="$REPO_DIR/assets/patches/comfyui-61e524bd.patch"
        ;;
    legacy)
        COMFY_COMMIT="bd34f338ac505ea79e43968753968a464060e609"
        DEFAULT_BRANCH="ascend-npu-v0.32"
        PATCH_FILE="$REPO_DIR/assets/patches/comfyui-bd34f338.patch"
        ;;
    *) echo "!! 未知 COMFY_PROFILE=$COMFY_PROFILE (可选 latest / legacy)"; exit 1 ;;
esac
# ComfyUI 源码仓库：默认本项目维护的 fork（含昇腾补丁分支 ascend-npu-v0.44），可用 COMFY_REPO 覆盖
COMFY_REPO="${COMFY_REPO:-https://github.com/BenjaminHernandez9794/ComfyUI-npu.git}"
# 适配 NPU 的分支（已包含昇腾补丁）。latest → ascend-npu-v0.44，legacy → ascend-npu-v0.32；可用 COMFY_BRANCH 覆盖。
# 若仓库里没有该分支（例如 COMFY_REPO 指向官方），自动退回「固定 commit + 打补丁」；也可用 COMFY_USE_PATCH=1 强制走补丁。
COMFY_BRANCH="${COMFY_BRANCH:-$DEFAULT_BRANCH}"
COMFY_USE_PATCH="${COMFY_USE_PATCH:-0}"
PIP_MIRROR="${PIP_MIRROR:-https://repo.huaweicloud.com/repository/pypi/simple}"
# 实际拉取地址：设置了 GH_PROXY 且仓库在 github.com 时走代理
COMFY_FETCH_URL="$COMFY_REPO"
if [ -n "$GH_PROXY" ] && [[ "$COMFY_REPO" == https://github.com/* ]]; then
    COMFY_FETCH_URL="$GH_PROXY/$COMFY_REPO"
fi

echo "=== [1/6] 环境检查 ==="

# --- 定位 CANN ---
ASCEND_HOME=""
for p in /usr/local/Ascend/ascend-toolkit "$HOME/Ascend/ascend-toolkit" /home/*/Ascend/ascend-toolkit; do
    if [ -f "$p/set_env.sh" ]; then ASCEND_HOME="$p"; break; fi
done
if [ -z "$ASCEND_HOME" ]; then
    echo "!! 未找到 CANN (ascend-toolkit/set_env.sh)。请先安装 CANN >= 9.0.0"; exit 1
fi
echo "CANN: $ASCEND_HOME"
# shellcheck disable=SC1091
set +u; source "$ASCEND_HOME/set_env.sh"; set -u

# --- 检查 NPU ---
NPU_COUNT=$(ls -d /dev/davinci[0-9]* 2>/dev/null | wc -l)
[ "$NPU_COUNT" -eq 0 ] && { echo "!! 未发现 NPU 设备 (/dev/davinci*)"; exit 1; }
# npu_count 仅支持 1/2/4，取最接近的合法值
if [ "$NPU_COUNT" -ge 4 ]; then NPU_COUNT=4; elif [ "$NPU_COUNT" -ge 2 ]; then NPU_COUNT=2; else NPU_COUNT=1; fi
echo "NPU 数量(用于 npu_count): $NPU_COUNT"

# --- 检查 torch / torch_npu，缺了就按 CANN 版本自动装配套版本 ---
# 配套关系来自 Ascend/pytorch COMPATIBILITY.md。默认 torch 2.7.1（本项目在 910B 实测的版本），
# 可用 TORCH_VERSION=2.9.0 之类改；TORCH_NPU_VERSION 可直接指定 torch_npu 安装包版本。
# 格式: <CANN 版本前缀> <torch> <torch_npu>；按顺序取第一条前缀匹配的（更具体的写在前面）
TORCH_NPU_TABLE="
9.2 2.7.1 2.7.1.post11
9.2 2.9.0 2.9.0.post9
9.2 2.10.0 2.10.0.post7
9.2 2.11.0 2.11.0.post3
9.2 2.12.0 2.12.0.post3
9.2 2.13.0 2.13.0
9.2 2.14.0 2.14.0
9.1.0 2.7.1 2.7.1.post8
9.1.0 2.9.0 2.9.0.post6
9.1.0 2.10.0 2.10.0.post4
9.1.0 2.11.0 2.11.0
9.1.0 2.12.0 2.12.0
9.1 2.7.1 2.7.1.post10
9.1 2.9.0 2.9.0.post8
9.1 2.10.0 2.10.0.post6
9.1 2.11.0 2.11.0.post2
9.1 2.12.0 2.12.0.post2
9.0 2.7.1 2.7.1.post4
9.0 2.8.0 2.8.0.post4
9.0 2.9.0 2.9.0.post2
9.0 2.10.0 2.10.0
8.5 2.7.1 2.7.1.post2
8.5 2.8.0 2.8.0.post2
8.5 2.9.0 2.9.0
8.3 2.7.1 2.7.1
8.3 2.8.0 2.8.0
"
cann_version() {
    local root="${ASCEND_TOOLKIT_HOME:-$ASCEND_HOME/latest}" f v
    for f in "$root"/*/ascend_toolkit_install.info "$root"/ascend_toolkit_install.info \
             "$root"/compiler/version.info "$root"/runtime/version.info "$root"/version.cfg; do
        [ -f "$f" ] || continue
        v=$(grep -m1 -oiE '^version=[0-9A-Za-z.]+' "$f" 2>/dev/null | cut -d= -f2)
        [ -n "$v" ] && { echo "$v"; return; }
    done
    # 兜底：从目录名里找（如 .../ascend-toolkit/9.0.0）
    v=$(readlink -f "$root" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.(RC)?[0-9]+' | tail -1)
    echo "${v:-unknown}"
}
pick_torch_npu() {  # $1=CANN 版本 $2=torch 版本 → torch_npu 安装包版本（找不到输出空）
    local cann="$1" tv="$2" c t n
    while read -r c t n; do
        [ -n "$c" ] || continue
        if [ "$t" = "$tv" ] && [[ "$cann" == "$c"* ]]; then echo "$n"; return; fi
    done <<< "$TORCH_NPU_TABLE"
}
py_site_writable() {
    python3 -c 'import os,sys,sysconfig; sys.exit(0 if (sys.prefix != sys.base_prefix or os.access(sysconfig.get_paths()["purelib"], os.W_OK)) else 1)' >/dev/null 2>&1
}
# pip_install：优先 uv（快很多），失败自动回退 pip；USE_UV=0 关闭
source "$REPO_DIR/scripts/pip_fast.sh"
pip_boot() {  # 系统 Python 只读时自动加 --user（此时走 pip，uv 不支持 --user）
    local extra=()
    py_site_writable || extra=(--user)
    pip_install --prefer-binary --timeout 60 --retries 3 ${extra[@]+"${extra[@]}"} "$@"
}

HAVE_TORCH=0; HAVE_NPU=0
python3 -c "import torch" >/dev/null 2>&1 && HAVE_TORCH=1
[ "$HAVE_TORCH" = 1 ] && python3 -c "import torch, torch_npu" >/dev/null 2>&1 && HAVE_NPU=1
if [ "$HAVE_NPU" = 0 ]; then
    CANN_VER=$(cann_version)
    PIP_MIRROR_BOOT="${PIP_MIRROR:-https://repo.huaweicloud.com/repository/pypi/simple}"
    if [ "$HAVE_TORCH" = 1 ]; then
        TV=$(python3 -c "import torch; print(torch.__version__.split('+')[0])")
        echo "检测到 torch $TV 但没有 torch_npu（CANN $CANN_VER），自动安装配套 torch_npu"
    else
        TV="${TORCH_VERSION:-2.7.1}"
        echo "未检测到 torch（CANN $CANN_VER），自动安装 torch $TV + 配套 torch_npu"
    fi
    NPU_VER="${TORCH_NPU_VERSION:-$(pick_torch_npu "$CANN_VER" "$TV")}"
    if [ -z "$NPU_VER" ]; then
        echo "  !! 配套表里没有 CANN $CANN_VER + torch $TV 的组合，改装 torch_npu==${TV}.* 的最新版（可能与 CANN 不配套）"
        echo "     可用 TORCH_VERSION / TORCH_NPU_VERSION 手动指定，配套表见 https://github.com/Ascend/pytorch/blob/master/COMPATIBILITY.md"
        NPU_SPEC="torch_npu==${TV}.*"
    else
        NPU_SPEC="torch_npu==${NPU_VER}"
    fi
    echo "  → torch==${TV}  ${NPU_SPEC}"
    if [ "$HAVE_TORCH" = 0 ]; then
        if [ "$(uname -m)" = "x86_64" ]; then
            # x86 上 PyPI 的 torch 会拖进几 GB 的 CUDA 依赖，昇腾只需 CPU 版
            pip_boot --index-url https://download.pytorch.org/whl/cpu "torch==${TV}+cpu" \
                || pip_boot -i "$PIP_MIRROR_BOOT" "torch==${TV}" \
                || { echo "!! torch ${TV} 安装失败"; exit 1; }
        else
            pip_boot -i "$PIP_MIRROR_BOOT" "torch==${TV}" || { echo "!! torch ${TV} 安装失败"; exit 1; }
        fi
    fi
    pip_boot -i "$PIP_MIRROR_BOOT" "$NPU_SPEC" || { echo "!! ${NPU_SPEC} 安装失败"; exit 1; }
    # CANN 编译算子时需要的 Python 依赖（缺了首次运行会报 No module named 'decorator' / 'attrs' 等）
    pip_boot -i "$PIP_MIRROR_BOOT" pyyaml attrs decorator psutil absl-py cloudpickle ml-dtypes scipy tornado \
        || echo "  (CANN 的 Python 依赖部分没装上，若首次推理报缺模块再手动装)"
fi

python3 - <<'PY'
import torch, torch_npu
print(f"torch {torch.__version__} / torch_npu {torch_npu.__version__} / npu_available={torch.npu.is_available()}")
assert torch.npu.is_available(), "torch_npu 不可用，请检查 CANN 与 torch_npu 版本配套（或驱动/固件）"
PY

echo "=== [2/6] 获取 ComfyUI (profile=$COMFY_PROFILE) ==="
echo "仓库: $COMFY_REPO"
[ "$COMFY_FETCH_URL" != "$COMFY_REPO" ] && echo "经 GitHub 代理: $COMFY_FETCH_URL"
if [ -d "$COMFY_HOME/.git" ]; then
    COMFY_EXISTING=1
    echo "检测到已有 ComfyUI 仓库: $COMFY_HOME —— 跳过克隆，只切换分支并更新"
elif [ -d "$COMFY_HOME" ] && [ -n "$(ls -A "$COMFY_HOME" 2>/dev/null)" ]; then
    echo "!! $COMFY_HOME 已存在且非空，但不是 git 仓库；请移走该目录或用 COMFY_HOME 指定其他位置"
    exit 1
else
    COMFY_EXISTING=0
    echo "克隆到: $COMFY_HOME"
    mkdir -p "$COMFY_HOME"
    git -C "$COMFY_HOME" init -q
fi
cd "$COMFY_HOME"
# 已有目录（例如之前从官方仓库克隆的）统一把 origin 指向本次的拉取地址
set_origin() {
    if git remote get-url origin >/dev/null 2>&1; then
        local cur; cur=$(git remote get-url origin)
        if [ "$cur" != "$1" ]; then
            echo "origin 原为 $cur，改为 $1"
            git remote set-url origin "$1"
        fi
    else
        git remote add origin "$1"
    fi
}
set_origin "$COMFY_FETCH_URL"
# 旧版 setup.sh 是把补丁直接打在工作区里的；切分支前先把本地改动收起来，避免 checkout 冲突
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    git stash push -q -u -m "setup.sh auto-stash $(date +%Y%m%d-%H%M%S)" && \
        echo "本地有未提交改动（多为旧版打的补丁），已 git stash 保存，可用 git stash list 查看"
fi
# 新克隆或本来就是浅克隆的仓库用 --depth 1；已有完整历史的仓库不加，避免把它变成浅克隆
FETCH_DEPTH=()
if [ "$COMFY_EXISTING" = "0" ] || [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
    FETCH_DEPTH=(--depth 1)
fi

retry() { "$@" || { echo "网络问题，重试..."; sleep 3; "$@"; }; }
# 检查分支是否存在：0=存在，2=仓库可达但没有该分支，其他=网络/仓库不可达
probe_branch() {
    local rc=0
    git ls-remote --exit-code --heads origin "$COMFY_BRANCH" >/dev/null 2>&1 || rc=$?
    if [ "$rc" != 0 ] && [ "$rc" != 2 ]; then
        sleep 3; rc=0
        git ls-remote --exit-code --heads origin "$COMFY_BRANCH" >/dev/null 2>&1 || rc=$?
    fi
    return "$rc"
}
USE_BRANCH=0
if [ "$COMFY_USE_PATCH" != "1" ] && [ -n "$COMFY_BRANCH" ]; then
    rc=0; probe_branch || rc=$?
    if [ "$rc" != 0 ] && [ "$rc" != 2 ] && [ "$COMFY_FETCH_URL" != "$COMFY_REPO" ]; then
        echo "!! 代理 $GH_PROXY 不可用，改为直连 $COMFY_REPO"
        COMFY_FETCH_URL="$COMFY_REPO"; set_origin "$COMFY_FETCH_URL"
        rc=0; probe_branch || rc=$?
    fi
    case "$rc" in
        0)
            OLD_REMOTE=$(git rev-parse -q --verify "refs/remotes/origin/$COMFY_BRANCH" || true)
            retry git fetch ${FETCH_DEPTH[@]+"${FETCH_DEPTH[@]}"} origin "+refs/heads/$COMFY_BRANCH:refs/remotes/origin/$COMFY_BRANCH"
            USE_BRANCH=1 ;;
        2)  echo "!! 仓库中没有分支 $COMFY_BRANCH，改用固定 commit ${COMFY_COMMIT:0:8} + 补丁" ;;
        *)  echo "!! 无法访问 $COMFY_FETCH_URL；国内网络可加 --gh-proxy https://gp.1314510.xyz 之类的 GitHub 代理"; exit 1 ;;
    esac
fi

if [ "$USE_BRANCH" = "1" ]; then
    REMOTE_REF="refs/remotes/origin/$COMFY_BRANCH"
    if git show-ref --verify -q "refs/heads/$COMFY_BRANCH"; then
        git checkout -q "$COMFY_BRANCH"
        OLD_HEAD=$(git rev-parse --short HEAD)
        if [ "$(git rev-parse HEAD)" = "$(git rev-parse "$REMOTE_REF")" ]; then
            echo "分支 $COMFY_BRANCH 已是最新 ($OLD_HEAD)"
        elif [ -n "$OLD_REMOTE" ] && [ "$(git rev-parse HEAD)" = "$OLD_REMOTE" ]; then
            # 本地没有自己的提交（停在上次拉到的远端位置），直接对齐（浅克隆下快进判断不可靠）
            git reset -q --hard "$REMOTE_REF"
            echo "分支 $COMFY_BRANCH 已更新: $OLD_HEAD -> $(git rev-parse --short HEAD)"
        elif git merge -q --ff-only "$REMOTE_REF" 2>/dev/null; then
            echo "分支 $COMFY_BRANCH 已更新: $OLD_HEAD -> $(git rev-parse --short HEAD)"
        else
            # 本地分支有远端没有的提交（或浅克隆看不到共同祖先）：备份后对齐远端
            BACKUP="$COMFY_BRANCH-backup-$(date +%Y%m%d-%H%M%S)"
            git branch -q "$BACKUP"
            git reset -q --hard "$REMOTE_REF"
            echo "分支 $COMFY_BRANCH 无法快进，原状态已备份为 $BACKUP，已对齐远端: $OLD_HEAD -> $(git rev-parse --short HEAD)"
        fi
    else
        git checkout -q -b "$COMFY_BRANCH" "$REMOTE_REF"
        echo "已切换到 NPU 适配分支: $COMFY_BRANCH"
    fi
    git branch -q --set-upstream-to="origin/$COMFY_BRANCH" "$COMFY_BRANCH" 2>/dev/null || true
    git log --oneline -1
    echo "=== [3/6] 检查昇腾适配补丁 ==="
    if git apply --reverse --check "$PATCH_FILE" 2>/dev/null; then
        echo "分支已包含补丁 $(basename "$PATCH_FILE")"
    else
        echo "提示: 分支内容与 $(basename "$PATCH_FILE") 不完全一致（分支可能已有后续修正），以分支为准"
    fi
else
    retry git fetch ${FETCH_DEPTH[@]+"${FETCH_DEPTH[@]}"} origin "$COMFY_COMMIT"
    git checkout -q --detach FETCH_HEAD
    git log --oneline -1
    echo "=== [3/6] 应用昇腾适配补丁 ==="
    if git apply --reverse --check "$PATCH_FILE" 2>/dev/null; then
        echo "补丁已存在，跳过"
    else
        git apply --check "$PATCH_FILE" && git apply "$PATCH_FILE" || { echo "!! 补丁无法应用到 ${COMFY_COMMIT:0:8}"; exit 1; }
    fi
fi
echo "昇腾适配来源: Ascend-SACT/MiniMax-H3-Comfy-NPU (Apache-2.0)"

echo "=== [4/6] 安装 Python 依赖 ==="
echo "pip 源: $PIP_MIRROR"
PIP=(pip_install --prefer-binary --timeout 60 --retries 3 -i "$PIP_MIRROR")
# 新版 ComfyUI 的 av>=17、comfy-angle 只提供 manylinux_2_28 轮子，pip<20.3 识别不了会转去源码编译（看起来像卡住）
PIP_VER=$(python3 -m pip --version | awk '{print $2}')
if ! python3 - "$PIP_VER" <<'PY'
import sys
v = [int(x) for x in sys.argv[1].split(".")[:2] if x.isdigit()]
sys.exit(0 if v >= [20, 3] else 1)
PY
then
    echo "pip $PIP_VER 过旧，先升级 pip"
    "${PIP[@]}" -U "pip>=23"
fi
# 锁住预装的 torch / torch_npu 等，防止 requirements 里的 torch、torchvision、spandrel、kornia 把 torch 升级掉
# （升级既要下载数 GB 的轮子，也会破坏 torch_npu 配套）
PIP_CONSTRAINTS=/tmp/minimax_h3_constraints.txt
# torchaudio 不锁：它必须跟 torch 同版本，锁住一个不匹配的旧装版本会让后面的 torchaudio==<torch 版本> 无解
python3 -m pip list --format=freeze 2>/dev/null | grep -i -E '^(torch|torch[-_]npu|torchvision)==' > "$PIP_CONSTRAINTS" || true
echo "锁定已安装版本: $(tr '\n' ' ' < "$PIP_CONSTRAINTS")"
# ComfyUI 核心依赖（跳过需要 py3.12 的模板包）
grep -v -E 'comfyui-workflow-templates|comfyui-embedded-docs' requirements.txt > /tmp/req_core.txt
"${PIP[@]}" -c "$PIP_CONSTRAINTS" -r /tmp/req_core.txt
"${PIP[@]}" --no-deps comfyui-workflow-templates comfyui-embedded-docs
TORCH_VER=$(python3 -c "import torch; print(torch.__version__.split('+')[0])")
if [ "$COMFY_PROFILE" = "legacy" ]; then
    # 旧版 ComfyUI 强依赖 torchaudio，且必须与 torch 同版本
    "${PIP[@]}" "torchaudio==${TORCH_VER}" || \
        python3 -m pip install --timeout 60 --retries 2 --index-url https://download.pytorch.org/whl/cpu "torchaudio==${TORCH_VER}"
    "${PIP[@]}" -c "$PIP_CONSTRAINTS" comfy-kitchen==0.2.30 comfy-aimdo==0.4.13
else
    # 新版 ComfyUI 已移除 torchaudio 硬依赖 (#16457)，装不上不影响 H3；只试国内源，不再回退到 download.pytorch.org（国内常年超时）
    # 注意：torchaudio 必须与 torch 同 ABI，否则一 import 就崩（undefined symbol: torch_library_impl）。
    # transformers 只按“包是否存在”决定要不要 import torchaudio，所以一个装着但崩的 torchaudio 会
    # 静默弄挂所有 import transformers 的自定义节点（LayerStyle 等）。这里以“能否真正 import”为准，崩的直接卸掉。
    TA_VER=$(python3 -m pip list --format=freeze 2>/dev/null | grep -i '^torchaudio==' | cut -d= -f3 | cut -d+ -f1)
    if [ -z "$TA_VER" ]; then
        "${PIP[@]}" -c "$PIP_CONSTRAINTS" "torchaudio==${TORCH_VER}" || echo "torchaudio 跳过（可选，ComfyUI 与 H3 都不需要）"
    elif python3 -c "import torchaudio" >/dev/null 2>&1; then
        echo "torchaudio ${TA_VER} 已安装且可正常 import，保留"
    else
        # 装着但 import 崩（通常是与 torch ${TORCH_VER} ABI 不匹配）。ComfyUI/H3 及工作流节点都不需要音频。
        # 先试卸载让 transformers 当它不存在、跳过音频分支，避免连带弄挂 LayerStyle 等依赖 transformers 的节点。
        echo "检测到 torchaudio ${TA_VER} 无法 import（与 torch ${TORCH_VER} ABI 不匹配），尝试处理以免弄挂依赖 transformers 的节点"
        if python3 -m pip uninstall -y torchaudio >/dev/null 2>&1 && ! python3 -c "import torchaudio" >/dev/null 2>&1; then
            echo "  已卸载坏 torchaudio"
        else
            # 卸不掉（常见：装在只读的系统 Python，如 /opt/buildtools），改为把匹配版本装到用户目录覆盖它
            echo "  无法卸载（可能装在只读系统目录），改为安装匹配版 torchaudio==${TORCH_VER} 到用户目录覆盖"
            python3 -m pip install --user "torchaudio==${TORCH_VER}" \
                || python3 -m pip install --user --index-url https://download.pytorch.org/whl/cpu "torchaudio==${TORCH_VER}" \
                || echo "  !! 自动修复 torchaudio 失败，见下方手动办法"
            if ! python3 -c "import torchaudio" >/dev/null 2>&1; then
                echo "  提示: torchaudio 仍无法 import。坏版本装在系统目录且无写权限时，可任选其一手动修复："
                echo "    a) 在虚拟环境里跑 ComfyUI（venv 的 site-packages 可写，卸载即可）"
                echo "    b) sudo python3 -m pip uninstall -y torchaudio"
                echo "    c) python3 -m pip install --user torchaudio==${TORCH_VER}"
            fi
        fi
    fi
    # comfy-kitchen / comfy-aimdo 版本由 ComfyUI requirements.txt 锁定 (0.2.41 / 0.6.0)
fi
"${PIP[@]}" -c "$PIP_CONSTRAINTS" imageio-ffmpeg hf_transfer
python3 -c "import torch, torch_npu; print('依赖安装完成: torch', torch.__version__, '/ torch_npu', torch_npu.__version__)"

echo "=== [5/6] 安装验证版 Turbo 节点 ==="
mkdir -p "$COMFY_HOME/custom_nodes"
tar xzf "$REPO_DIR/assets/ComfyUI-MiniMax-H3-Turbo-verified.tgz" -C /tmp/
rm -rf "$COMFY_HOME/custom_nodes/ComfyUI-MiniMax-H3-Turbo"
cp -r /tmp/additional_files/custom_nodes/ComfyUI-MiniMax-H3-Turbo "$COMFY_HOME/custom_nodes/"

echo "=== [6/6] 安装工作流 ==="
mkdir -p "$COMFY_HOME/user/default/workflows/minimax-h3"
cp "$REPO_DIR"/workflows/*.json "$COMFY_HOME/user/default/workflows/minimax-h3/"
# i2v 工作流需要的图占位
mkdir -p "$COMFY_HOME/input"

if [ -n "${CUSTOM_NODES:-}" ]; then
    echo "=== [+] 安装额外自定义节点: $CUSTOM_NODES ==="
    COMFY_HOME="$COMFY_HOME" PIP_MIRROR="$PIP_MIRROR" GH_PROXY="$GH_PROXY" \
        bash "$REPO_DIR/scripts/install_nodes.sh" "$CUSTOM_NODES" || \
        echo "!! 部分自定义节点没装好（见上方输出），不影响 MiniMax-H3；可稍后单独重跑: bash scripts/install_nodes.sh $CUSTOM_NODES"
fi

cat <<EOF

============================================================
✅ 部署完成！

下一步：
  1) 下载模型（默认约 121GB，--lowvram 约 61GB，可断点续传）:
       bash scripts/download_models.sh
  2) 启动服务:
       bash scripts/start_comfyui.sh
  3) 浏览器打开: http://127.0.0.1:8188
     从 Workflows → minimax-h3 选择工作流出片

提示: ComfyUI 装在 $COMFY_HOME（已记到 .comfy_home，其它脚本自动沿用；
      临时换目录可在命令前加 COMFY_HOME=/其它/路径）
============================================================
EOF

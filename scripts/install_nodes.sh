#!/usr/bin/env bash
# =============================================================
# 安装额外的 ComfyUI 自定义节点（克隆/更新 + 装依赖，不会动预装的 torch / torch_npu）
# 用法: bash scripts/install_nodes.sh [--gh-proxy URL] [--no-install-uv] [--list] <名称|别名|GitHub 地址> ...
#   名称: goohai rgthree layerstyle easyuse comfyroll（可用逗号分隔）
#   别名: qwen21      = goohai,rgthree,layerstyle      （Qwen-Image 2.1 Turbo 整合工作流必需）
#         qwen21-full = qwen21 + easyuse,comfyroll      （连旁路分组里的节点一起装）
#         moss        = rgthree,easyuse                 （MOSS-Image 整合工作流必需的；
#                       另需 ResolutionSelector 节点，整合包来源待确认，需手动装；
#                       SeedVR2 超分 / TE-Speed-MOSS 均为旁路可选，TE-Speed-MOSS 仅 Windows 不装）
#   也可直接写 https://github.com/<作者>/<仓库>
#   --no-install-uv 没有 uv 时不自动安装、直接用 pip
#   环境变量: COMFY_HOME（默认取 setup.sh 记下的目录，否则 /mnt/workspace/ComfyUI）、PIP_MIRROR、GH_PROXY、UV_AUTO_INSTALL、USE_UV
# =============================================================
set -uo pipefail

usage() { sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'; }

declare -A NODE_URL=(
    [goohai]=https://github.com/goohai/Goohaitools-comfyui.git
    [rgthree]=https://github.com/rgthree/rgthree-comfy.git
    [layerstyle]=https://github.com/chflame163/ComfyUI_LayerStyle.git
    [easyuse]=https://github.com/yolain/ComfyUI-Easy-Use.git
    [comfyroll]=https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git
    [seedvr2]=https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git
)
declare -A NODE_ALIAS=(
    [qwen21]="goohai rgthree layerstyle"
    [qwen21-full]="goohai rgthree layerstyle easyuse comfyroll"
    [moss]="rgthree easyuse"
    [moss-full]="rgthree easyuse seedvr2"
)

ITEMS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --gh-proxy)   GH_PROXY="${2:?--gh-proxy 需要一个地址}"; shift 2 ;;
        --gh-proxy=*) GH_PROXY="${1#*=}"; shift ;;
        --list)
            for k in goohai rgthree layerstyle easyuse comfyroll seedvr2; do printf '  %-11s %s\n' "$k" "${NODE_URL[$k]}"; done
            for k in qwen21 qwen21-full moss moss-full; do printf '  %-11s = %s\n' "$k" "${NODE_ALIAS[$k]}"; done
            exit 0 ;;
        --no-install-uv) UV_AUTO_INSTALL=0; shift ;;
        --install-uv)    UV_AUTO_INSTALL=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        -*) echo "!! 未知参数: $1"; usage; exit 1 ;;
        *) IFS=', ' read -r -a parts <<< "$1"; ITEMS+=("${parts[@]}"); shift ;;
    esac
done
[ ${#ITEMS[@]} -gt 0 ] || { usage; exit 1; }

GH_PROXY="${GH_PROXY:-}"; GH_PROXY="${GH_PROXY%/}"
if [ -n "$GH_PROXY" ] && [[ "$GH_PROXY" != http://* && "$GH_PROXY" != https://* ]]; then
    GH_PROXY="https://$GH_PROXY"
fi
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFY_HOME="${COMFY_HOME:-$(cat "$REPO_DIR/.comfy_home" 2>/dev/null || true)}"
COMFY_HOME="${COMFY_HOME:-/mnt/workspace/ComfyUI}"
PIP_MIRROR="${PIP_MIRROR:-https://repo.huaweicloud.com/repository/pypi/simple}"
NODES_DIR="$COMFY_HOME/custom_nodes"
[ -d "$COMFY_HOME" ] || { echo "!! 找不到 ComfyUI: $COMFY_HOME（先跑 setup.sh，或设置 COMFY_HOME）"; exit 1; }
mkdir -p "$NODES_DIR"

# 展开别名、去重，得到 URL 列表
URLS=()
add_url() { local u="$1" x; for x in ${URLS[@]+"${URLS[@]}"}; do [ "$x" = "$u" ] && return; done; URLS+=("$u"); }
for it in "${ITEMS[@]}"; do
    [ -n "$it" ] || continue
    if [ -n "${NODE_ALIAS[$it]:-}" ]; then
        for k in ${NODE_ALIAS[$it]}; do add_url "${NODE_URL[$k]}"; done
    elif [ -n "${NODE_URL[$it]:-}" ]; then
        add_url "${NODE_URL[$it]}"
    elif [[ "$it" == https://* ]]; then
        add_url "$it"
    else
        echo "!! 未知节点: $it（可选: ${!NODE_URL[*]} ${!NODE_ALIAS[*]}，或 GitHub 地址）"; exit 1
    fi
done

# 代理可用性只探测一次
PROXY_OK=0
if [ -n "$GH_PROXY" ]; then
    if git ls-remote --heads "$GH_PROXY/${URLS[0]}" >/dev/null 2>&1; then PROXY_OK=1
    else echo "!! 代理 $GH_PROXY 不可用，改为直连"; fi
fi
fetch_url() { if [ "$PROXY_OK" = 1 ] && [[ "$1" == https://github.com/* ]]; then echo "$GH_PROXY/$1"; else echo "$1"; fi; }

# 锁住预装的 torch / torch_npu / torchvision / numpy，防止节点依赖把它们升级掉
CONSTRAINTS=/tmp/minimax_h3_nodes_constraints.txt
python3 -m pip list --format=freeze 2>/dev/null | grep -i -E '^(torch|torch[-_]npu|torchvision|numpy)==' > "$CONSTRAINTS" || true
source "$REPO_DIR/scripts/pip_fast.sh"   # pip_install：优先 uv，失败回退 pip（USE_UV=0 关闭）
PIP=(pip_install --prefer-binary --timeout 60 --retries 3 -i "$PIP_MIRROR" -c "$CONSTRAINTS")

FAILED=()
NEED_XIMGPROC=0
for url in "${URLS[@]}"; do
    name=$(basename "$url" .git)
    dir="$NODES_DIR/$name"
    src=$(fetch_url "$url")
    echo "--- $name"
    if [ -d "$dir/.git" ]; then
        git -C "$dir" remote set-url origin "$src"
        if git -C "$dir" pull -q --ff-only; then echo "已更新: $(git -C "$dir" log --oneline -1)"
        else echo "!! $name 更新失败（本地有改动或网络问题），保留现有版本"; fi
    elif [ -e "$dir" ]; then
        echo "!! $dir 已存在且不是 git 仓库，跳过（要重装请先删除它）"; FAILED+=("$name"); continue
    else
        if ! git clone -q --depth 1 "$src" "$dir"; then
            sleep 3; git clone -q --depth 1 "$src" "$dir" || { echo "!! $name 克隆失败"; FAILED+=("$name"); continue; }
        fi
        echo "已安装: $(git -C "$dir" log --oneline -1)"
    fi
    [ "$name" = ComfyUI_LayerStyle ] && NEED_XIMGPROC=1
    if [ -f "$dir/requirements.txt" ]; then
        # torch 系列不装（会破坏 torch_npu 配套）；opencv 统一在下面处理（多个变体同时装会互相覆盖 cv2）；
        # dlib 在 aarch64 没有轮子要现场编译，孤海只有人脸类节点用它，跳过
        req=/tmp/req_node_$name.txt
        grep -v -i -E '^\s*(torch|torchvision|torchaudio|torch[-_]npu|opencv|dlib)\b' "$dir/requirements.txt" > "$req" || true
        if grep -q -v -E '^\s*(#|$)' "$req"; then
            "${PIP[@]}" -r "$req" || { echo "!! $name 部分依赖安装失败，节点可能只有部分可用"; FAILED+=("$name(依赖)"); }
        fi
    fi
done

# opencv：没有就装 contrib-headless（LayerStyle 需要 contrib 里的 ximgproc，headless 不依赖 libGL）。
# 孤海依赖的 mediapipe 会拉进带 GUI 的 opencv-contrib-python，容器里缺 libGL 时 import cv2 会失败 → 换成 headless
if ! python3 -c "import cv2" 2>/dev/null; then
    if python3 -m pip show -q opencv-python opencv-contrib-python >/dev/null 2>&1; then
        echo "import cv2 失败（多半缺 libGL），改用 opencv-contrib-python-headless"
        python3 -m pip uninstall -y opencv-python opencv-contrib-python >/dev/null 2>&1 || true
        python3 -m pip uninstall -y opencv-contrib-python-headless >/dev/null 2>&1 || true
    fi
    "${PIP[@]}" opencv-contrib-python-headless || FAILED+=("opencv")
    python3 -c "import cv2" 2>/dev/null || { echo "!! import cv2 仍失败"; FAILED+=("opencv"); }
elif [ "$NEED_XIMGPROC" = 1 ] && ! python3 -c "import cv2; cv2.ximgproc" 2>/dev/null; then
    echo "提示: 已装的 opencv 不含 contrib 模块，LayerStyle 的部分节点（引导滤波等）不可用。如需要可执行:"
    echo "      pip uninstall -y opencv-python opencv-python-headless && pip install opencv-contrib-python-headless"
fi

# Comfyroll 的 CR Select Font 在 Linux 上写死读 /usr/share/fonts/truetype，精简容器没有这个目录时
# 前端加载节点列表会报 FileNotFoundError。没有就建上，并链接 Comfyroll 自带的字体（CR 文字节点本来就从它自己的 fonts/ 取字体）
CR_FONTS="$NODES_DIR/ComfyUI_Comfyroll_CustomNodes/fonts"
SYS_FONTS=/usr/share/fonts/truetype
if [ -d "$CR_FONTS" ] && [ "$(uname -s)" = Linux ] && [ ! -d "$SYS_FONTS" ]; then
    if mkdir -p "$SYS_FONTS" 2>/dev/null; then
        for f in "$CR_FONTS"/*.ttf; do [ -e "$f" ] && ln -sf "$f" "$SYS_FONTS/"; done
        echo "已创建 $SYS_FONTS 并链接 Comfyroll 自带字体（修复 CR Select Font 报错）"
    else
        echo "提示: 缺少 $SYS_FONTS 且无权限创建，CR Select Font 节点会报错（其它节点不受影响）。可执行:"
        echo "      sudo mkdir -p $SYS_FONTS && sudo ln -sf $CR_FONTS/*.ttf $SYS_FONTS/"
    fi
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "!! 未完全成功: ${FAILED[*]}"; exit 1
fi
echo "自定义节点安装完成，重启 ComfyUI 生效"

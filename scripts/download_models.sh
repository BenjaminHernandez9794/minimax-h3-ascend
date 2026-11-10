#!/usr/bin/env bash
# 模型下载（hf-mirror 分片并行，实测 ~40MB/s，支持断点续传）
# 用法:
#   bash scripts/download_models.sh                       # 默认清单 model_lists/ascend.txt（约 121GB，含 Ref2VA 与无审查文本编码器）
#   bash scripts/download_models.sh --lowvram             # 低配档（约 61GB：精简版主模型+文本编码器+VAE+LoRA，32GB 单卡可用）
#   bash scripts/download_models.sh --lowvram --with ref2va,heretic   # 低配档再加 Ref2VA 主模型与无审查文本编码器
#   bash scripts/download_models.sh -l my_models.txt      # 指定模型清单（可多次 -l）
#   bash scripts/download_models.sh --with pruned --without heretic,ref2va
#   bash scripts/download_models.sh --dry-run             # 只列出要下载的文件
#   bash scripts/download_models.sh --help                # 全部参数
# 清单格式见 model_lists/README.md。其余参数原样传给 scripts/dl_models.py。
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export COMFY_HOME="${COMFY_HOME:-/mnt/workspace/ComfyUI}"

ARGS=()
for a in "$@"; do
    case "$a" in
        --lowvram)
            echo "=== 低配档：精简版主模型（21GB）替代完整版（34GB），不下载 Ref2VA（21GB）与无审查文本编码器（26GB）==="
            ARGS+=(--without full,ref2va,heretic --with pruned) ;;
        *) ARGS+=("$a") ;;
    esac
done

echo "模型将下载到: $COMFY_HOME/models"
exec python3 "$REPO_DIR/scripts/dl_models.py" ${ARGS[@]+"${ARGS[@]}"}

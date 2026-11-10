#!/usr/bin/env bash
# N 卡（RTX 4090 / 5090 等）模型下载，清单 model_lists/nvidia.txt
# 用法:
#   bash scripts/download_models_nvidia.sh                 # fp8 精简版（默认）
#   bash scripts/download_models_nvidia.sh --with w6a8     # 再加 w6a8（更省显存）；旧写法 W6A8=1 仍可用
#   bash scripts/download_models_nvidia.sh --with nvfp4    # 50 系 Blackwell 专用 nvfp4 文本编码器；旧写法 NVFP4_TE=1
#   其余参数同 download_models.sh（-l / --with / --without / --dry-run ...）
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export COMFY_HOME="${COMFY_HOME:-$HOME/ComfyUI}"
echo "=== N 卡模式，模型下载到: $COMFY_HOME/models"
echo "详见 docs/NVIDIA显卡部署指南.md"
HAS_LIST=0
for a in "$@"; do case "$a" in -l|--list|--list=*) HAS_LIST=1 ;; esac; done
if [ "$HAS_LIST" = 0 ]; then set -- -l nvidia.txt "$@"; fi
exec python3 "$REPO_DIR/scripts/dl_models.py" "$@"

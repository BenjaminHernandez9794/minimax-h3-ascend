#!/usr/bin/env bash
# 检查 ComfyUI 的 models 目录缺哪些模型（只读）。参数见: bash scripts/check_models.sh --help
#   bash scripts/check_models.sh                                  # model_lists/ 全部清单概览
#   bash scripts/check_models.sh -l qwen_image_2.1_outfit.txt     # 某个清单
#   bash scripts/check_models.sh -w 工作流.json                    # 按工作流里引用的模型检查
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFY_HOME="${COMFY_HOME:-$(cat "$REPO_DIR/.comfy_home" 2>/dev/null || true)}"
COMFY_HOME="${COMFY_HOME:-/mnt/workspace/ComfyUI}"
export COMFY_HOME
exec python3 "$REPO_DIR/scripts/check_models.py" "$@"

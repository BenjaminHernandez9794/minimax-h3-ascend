# 模型清单格式

`scripts/dl_models.py` / `scripts/download_models.sh` 按清单下载模型。每行一个文件：

```
<来源>  <目标>  [条件标签]
```

- **来源**
  - `组织/仓库:仓库内路径` —— Hugging Face 文件，走 `HF_ENDPOINT`（默认 hf-mirror.com）
  - `组织/仓库:仓库内路径@revision` —— 指定分支 / tag / commit（默认 `main`）
  - `civitai:<modelVersionId>@<fileId>` —— Civitai 文件（`@fileId` 省略则取该版本的主文件）。
    需要 API Key：`export CIVITAI_TOKEN=xxxx`（civitai.com → 用户设置 → API Keys）；
    站点可用 `CIVITAI_ENDPOINT` 换镜像域名（如 `https://civitai.red`）。ID 就在模型页地址里：
    `civitai.com/models/3015644/dirty-moss?modelVersionId=3423156` → 版本 3423156，fileId 用
    `curl https://civitai.com/api/v1/model-versions/3423156` 查 `files[].id`。
  - `https://...` —— 任意直链（需支持 Range 才能多连接，否则自动单连接）
- **目标**：相对 `$COMFY_HOME/models`（也可写绝对路径）
  - `loras` 或 `loras/` —— 目录，文件名沿用来源
  - `loras/my_name.safetensors` —— 带扩展名则视为完整路径，可改名
- **条件标签**（可选，逗号或空格分隔）：`tag` 表示该标签开启才下载，`!tag` 表示该标签开启时**不**下载。
  无标签的行总是下载。

指令：

- `#@default tag1 tag2` —— 默认开启的标签
- `#@include other.txt` —— 引入另一个清单（相对当前文件）

路径里有空格时写成 `%20`（如 `org/repo:My%20Lora.safetensors`），本地按解码后的文件名保存。

`#` 开头为注释，行尾 ` # ...` 也视为注释。

## 示例：自定义清单

```
# my_models.txt
#@include ascend.txt
#@default full
Comfy-Org/MiniMax-H3:loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors  loras
some-org/some-lora:my_style.safetensors   loras/my_style_v2.safetensors
https://example.com/files/upscaler.safetensors  upscale_models
```

```bash
bash scripts/download_models.sh -l my_models.txt                 # 用自己的清单
bash scripts/download_models.sh -l my_models.txt --without heretic
bash scripts/download_models.sh --list-tags                      # 看默认清单有哪些标签
bash scripts/download_models.sh --dry-run                        # 只看要下什么
```

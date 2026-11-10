# 更新记录

> 这个仓库是**活的** —— 每次真机实测、每个新机型、每个新坑都会记在这里。
> 如果你看到某个仓库内容和这里一模一样但**没有后续更新**，那大概率是搬运的死仓库。

## 2026-11-10

- 新增 `scripts/install_nodes.sh` 与 `setup.sh --nodes LIST`（或 `CUSTOM_NODES`）：安装额外自定义节点（goohai、rgthree、layerstyle、easyuse、comfyroll，别名 `qwen21` / `qwen21-full`，也可填 GitHub 地址）。走 `--gh-proxy`；已存在则 `git pull --ff-only`；依赖安装时锁住 torch/torch_npu/torchvision/numpy，跳过 torch 系列、opencv 与 dlib；opencv 统一为 contrib，import 失败时换 headless。
- 新增 `model_lists/qwen_image_2.1_turbo.txt`：Qwen-Image 2.1 Turbo 9 步整合工作流（编辑/扩图/移除/重绘/文生图）的模型清单，默认约 17.8GB，可选标签 `pe`、`bfs`、`pe_gguf`。
- dl_models.py：清单里的来源和目标支持 `%20` 等 URL 转义（文件名带空格时用），本地按解码后的名字保存。
- setup.sh：pip 约束文件不再锁 torchaudio（已装的不匹配版本会让 `torchaudio==<torch 版本>` 无解，910B 实测 torchaudio 2.11.0+cpu 配 torch 2.7.1 报 ResolutionImpossible）。
- **setup.sh：latest 档自动卸载“装着但 import 崩”的 torchaudio**。910B 实测 LayerStyle `IMPORT FAILED`，根因是 torchaudio 2.11 与 torch 2.7.1 ABI 不匹配（`undefined symbol: torch_library_impl`）：transformers 只按“包是否存在”决定要不要 `import torchaudio`，于是坏掉的 torchaudio 会静默弄挂所有 import transformers 的自定义节点。现在 setup.sh 以“能否真正 `import torchaudio`”为准，崩的直接 `pip uninstall -y torchaudio`（ComfyUI/H3 与工作流节点都不需要音频，卸载后 transformers 自动跳过音频分支）。
- `model_lists/qwen_image_2.1_turbo.txt`：注释掉提示词优化相关模型（`pe` 两个 Qwen3.5-9B PE 编码器、`pe_gguf` 三个 GGUF），默认与 `--with pe/pe_gguf` 都不再下载；必需三件套与 BFS 换头/换身 LoRA 保留，去掉行前 `#` 即可恢复。
- **修复 910B 上 VAE 加载报错 `'torch.device' object has no attribute 'dtype'`**：torch_npu 给 `nn.Module` 打了同名方法 `cast_weight(device)`，`Module.to()` 会调用它，与新版 ComfyUI `RMSNorm.cast_weight(input)` 冲突。ComfyUI-npu `ascend-npu-v0.44` 新提交 d7a39826 按参数类型分流；同时为 SQLite < 3.24（无 UPSERT）的 Python 加回退，修复 `Failed to persist prompt history ... near "ON": syntax error`。`assets/patches/comfyui-61e524bd.patch` 已按分支重新生成。
- **start_comfyui.sh 默认前台运行并实时显示日志**：输出同时 tee 到 `/mnt/workspace/runtime/comfyui-<端口>.log`（原来只写文件，终端无输出）；`-d` / `DAEMON=1` 后台运行；`PYTHONUNBUFFERED=1`；停旧进程时最多等 15 秒再强杀；`COMFY_RUNTIME_DIR` 可改日志目录；无 /dev/davinci* 时不再因 pipefail 静默退出。
- **`download_models.sh --lowvram` 改为约 61GB**：原来文档写约 57GB，但 Ref2VA 主模型（21GB）和无审查文本编码器（26GB）默认开启，实际约 108GB（旧版脚本同样如此）。现在 --lowvram 同时关掉 ref2va、heretic，需要时加 `--with ref2va,heretic`；`--with/--without` 按出现顺序生效。下载开始前列出每个文件大小、合计、本地已完成量；默认清单实为约 121GB，文档已更正。
- **setup.sh 已有目录只切分支并更新**：`COMFY_HOME` 已是 git 仓库时跳过克隆；本地分支无自有提交则对齐远端，否则备份为 `<分支>-backup-<时间>` 后对齐；已有完整历史的仓库不再用 `--depth 1`（避免变成浅克隆）；非 git 的非空目录报错退出。
- **setup.sh 支持 GitHub 代理**：`--gh-proxy URL` / `GH_PROXY`（前缀式，如 https://gp.1314510.xyz），代理不通自动直连；新增 `--profile`、`-h`；区分「仓库无此分支」与「网络不通」，后者直接报错并提示加代理。
- **setup.sh 依赖安装防卡死**：去掉 `pip -q` 显示下载进度；`--prefer-binary --timeout 60 --retries 3`；pip<20.3 先升级（新版 av>=17、comfy-angle 只有 manylinux_2_28 轮子，旧 pip 会转去源码编译）；用约束文件锁住预装的 torch / torch_npu / torchvision / torchaudio，防止被 requirements 升级；latest 档 torchaudio 不再回退到 download.pytorch.org；`PIP_MIRROR` 可覆盖。
- **setup.sh 自动切到 NPU 适配分支**：latest → `ascend-npu-v0.44`，legacy → `ascend-npu-v0.32`（新建，= bd34f338 + 原版补丁），`COMFY_BRANCH` 可覆盖；仓库没有该分支时退回 commit + 补丁（`COMFY_USE_PATCH=1` 可强制）。首次获取改为浅拉取分支，不再完整 clone；已有工作区改动会先 stash。补丁打不上时直接报错退出。
- **setup.sh 改从 fork 拉 ComfyUI**：默认 `https://github.com/BenjaminHernandez9794/ComfyUI-npu.git`，可用 `COMFY_REPO` 覆盖；已有的 ComfyUI 目录会把 origin 改指向该地址。
- **模型下载器通用化**：`scripts/dl_models.py` 改为按清单文件下载，默认清单 `model_lists/ascend.txt` / `nvidia.txt`。
  `download_models.sh -l <清单>` 可指定自己的列表（支持多个、`#@include`、`@revision`、任意 https 直链、目标改名），
  `--with` / `--without` 开关可选模型，另有 `--dry-run`、`--list-tags`、`--verify`（HF sha256）、`HF_TOKEN`。
  旧参数与环境变量（`--lowvram`、`INCLUDE_HERETIC_TE`、`W6A8`、`NVFP4_TE`、`MAX_CONN` 等）保持兼容，默认下载内容不变。
- **修复续传缺陷**：旧版先把目标文件预分配到完整大小，中断后重跑会因"大小一致"直接跳过，留下半成品。
  现在下载到 `.part` 并用 `.part.json` 记录已完成分段，全部完成才改名；发现旧版残留会自动重下。
  另外检查服务器是否真的返回 206，不支持 Range 的源自动退回单连接；CDN 签名链接过期会自动刷新。

## 2026-10-13

- **跨平台口径修正**：**H3 的 GGUF 文本编码器在两条路线上都不可用** —— 所有 H3 的 GGUF 编码器仓库
  都缺 mmproj 视觉塔，`ClipLoaderGGUF` 必崩（N 卡真机验证）。原先"GGUF 是 N 卡专属"的写法不准确：
  **GGUF 只适合 N 卡的"主模型"**，编码器一律 safetensors + 官方 `CLIPLoader`。
  README 注意事项、姊妹项目说明与英文摘要均已改口径。
- **新增 N 卡实测数据对照**（姊妹项目 2026-10-13 真机）：RTX 4090-48G（显存魔改）在
  **无 SLA** 条件下 0.4MP/5s **54 秒**、0.6MP/4 步 84 秒、0.98MP/6 步 **243 秒**，显存峰值 48.1~48.5GB
  —— 用来和本仓库 910B 档（480P 热机 20~25 秒/条、1.0MP 段约 11 分钟）横向对照。
- **姊妹项目新增文档**：《真机踩坑与前置要求》（磁盘容量账本、GGUF 编码器不可用、SLA 崩溃因果链、
  远程运维小坑），昇腾用户跑 N 卡路线时可直接参考。
- 仓库清理：移除误入库的 `scripts/__pycache__/*.pyc`。

## 2026-10-12

- **社区增强件章节**：新增 Spectrum（省 30~35% 时间）与 Latent Upscaler（潜空间放大）的
  **昇腾兼容性判断**（纯张量运算 / 3D 卷积，理论上 torch_npu 可跑，但**全网无人实测**）。
  这是本仓库的开放式 TODO —— 谁先测出来，谁就是全网第一份数据。
- **Issue 模板**：新增「提交实测数据」模板，把昇腾机型 / CANN 版本 / 耗时做成结构化表单
  （昇腾路线的公开实测数据极少，靠社区一起补）。
- **README 流量优化**：居中标题 + 徽章 + 目录 + 一句话卖点 + 英文摘要 + 姊妹项目互链 + Star CTA。
- **口径修正**：新增「关于无审查文本编码器的说明」——Heretic 作者本人公开否认"换 encoder 能解锁内容"，
  ClipProj 实测条件张量余弦差仅 0.0023。自由度来自**全程本地推理**，不是那个文件名。
- **修错误链接**：GitHub 仓库实际名为 `minimax-h3-ascend`（原先写的 `-uncensored` 会 404）。
- **gitattributes**：yml 也强制 LF。

## 2026-10-12（上午）

- **N 卡路线**：`setup_nvidia.sh` + `download_models_nvidia.sh` + `docs/NVIDIA显卡部署指南.md`
  + 硬件性价比对比表（免费昇腾 > 32G 低配 > 4090 > 5090 > 910C）。
- **下载提速**：`dl_models.py` 单文件并发 16 → 32，支持 `MAX_CONN` / `FILES_PARALLEL` 环境变量，
  多文件并行；实测聚合 **40MB/s**，90GB 约 35~40 分钟（官方单连接仅 ~2MB/s）。
- **32GB 单卡低配档**：`fl2va_4step_480P低显存.json` + `--lowvram` 启动选项
  + `download_models.sh --lowvram` + 显存账本（TE 26GB 卸载 + DiT 21GB + VAE 3.4GB + 激活 2~5GB ≈ 27~30GB）。

## 2026-10-11

- **README 全面升级**：主打去审核版 + 完整模型清单表（审查 / 硬件要求 / 测试状态）
  + 低配昇腾指南 + 换机复原 FAQ + 3 张演示图（从 60 秒成片抽帧）。
- **仓库改名**：`minimax-h3-ascend-uncensored`，双平台地址同步。
- **初始版本**：一键部署 + 全流程脚本 + 实测数据 ——
  包含 910B 双卡真机跑通的完整方案与 17 条踩坑修复。

# 更新记录

> 这个仓库是**活的** —— 每次真机实测、每个新机型、每个新坑都会记在这里。
> 如果你看到某个仓库内容和这里一模一样但**没有后续更新**，那大概率是搬运的死仓库。

## 2026-11-11

- `start_comfyui.sh`：除 `-d` 外的参数原样透传给 ComfyUI（如 `--disable-mmap`），也可用 `COMFY_ARGS`。
- 新增 `scripts/npu_load_test.py`：把一个 safetensors 模型逐个张量拷到 NPU，带 NPU 自检、慢张量提示、出错时报出具体张量，`--ram` 对比 mmap 与先读进内存。用来排查加载模型时卡住 / `vector core timeout (507034)`。

- `install_nodes.sh`：修复 Comfyroll 的 `CR Select Font` 报 `FileNotFoundError: /usr/share/fonts/truetype`（该节点在 Linux 写死读这个目录，精简容器没有）。装了 Comfyroll 且目录不存在时自动创建，并链接 Comfyroll 自带的 ttf 字体；没权限则打印 sudo 命令。

- 修复启动时报 `comfyui-workflow-templates is not installed`：模板元包一直用 `--no-deps` 装（为了跳过约 1.1GB 的示例图片/视频包），但新版元包 import 时需要 `comfyui-workflow-templates-core` / `-json`，缺了就报这个错、模板浏览为空。现在 `setup.sh` / `setup_nvidia.sh` 按 requirements.txt 的版本装元包和文档包，并按元包声明的版本补装 core + json（约 8MB），媒体包仍然跳过。

- 依赖安装改用 **uv**（并行下载 + 并行安装，第 4 步「Installing collected packages」那种一个个装的长等待会短很多）：`setup.sh` 和 `scripts/install_nodes.sh` 的 pip 安装都走新的 `scripts/pip_fast.sh`。机器上没有 uv 时先从镜像装一个（约 20MB）；uv 失败自动回退 pip；系统 Python 只读（需要 `--user`）时直接用 pip。`USE_UV=0` 可完全改回 pip。没有 uv 时是否自动安装由 `--no-install-uv`（setup.sh / install_nodes.sh 参数）或 `UV_AUTO_INSTALL=0` 控制，关掉后直接用 pip；默认自动装。

- 默认 pip 镜像从清华 TUNA 换成华为云（`https://repo.huaweicloud.com/repository/pypi/simple`）：`setup.sh`、`scripts/install_nodes.sh`、`scripts/setup_nvidia.sh` 及几个小脚本统一改。`PIP_MIRROR=<地址>` 仍可覆盖（`setup_nvidia.sh` 现在也支持）。华为云上 torch 2.7.1、torch_npu 2.7.1.post2～post11（aarch64 / py3.11）都在。

- `setup.sh`：没有 torch / torch_npu 时不再直接报 `No module named 'torch'`，而是读取 CANN 版本（`ascend_toolkit_install.info` / `version.info`），按 Ascend/pytorch 官方配套表自动安装：默认 torch 2.7.1（910B 实测版本）+ 配套 torch_npu（CANN 9.0 → 2.7.1.post4，9.1.0 → post8，9.1.x → post10，9.2 → post11，8.5 → post2），再装 CANN 算子编译需要的 Python 依赖（attrs、decorator、psutil 等）。只有 torch 缺 torch_npu 时按现有 torch 版本配。x86 走 PyTorch CPU 源避免拖进 CUDA；系统 Python 只读时自动 `--user`。`TORCH_VERSION` / `TORCH_NPU_VERSION` 可覆盖。

- `setup.sh` 新增 `--comfy-home DIR`（等同环境变量 `COMFY_HOME`）指定 ComfyUI 安装目录，支持相对路径和 `~`。选定的目录写入仓库根的 `.comfy_home`（已 gitignore），`scripts/download_models.sh`、`install_nodes.sh`、`start_comfyui.sh` 默认读它，不用每次再设 `COMFY_HOME`；命令前临时写 `COMFY_HOME=...` 仍然优先。

- `scripts/dl_models.py` 支持 Civitai：清单来源写 `civitai:<modelVersionId>@<fileId>`，用 `CIVITAI_TOKEN` 鉴权（只在请求时拼到链接上，不打印），`CIVITAI_ENDPOINT` 可换镜像域名。Civitai 不允许 HEAD，改用 `GET Range: bytes=0-0` 探测大小，仍是分片并行 + 断点续传；没 token 时 dry-run 用公开 API 显示大小。顺带：`HF_TOKEN` 现在只发给 HF 源，不再随请求发到其它站点。
- `model_lists/moss_image.txt` 加入 7 个 Moss 特调模型（Civitai，均 INT8，按整合包文件名落到 `diffusion_models/Moss_image/`）：标签 `dirty`、`pornmaster`、`qizhen`（绮真）、`artius`（+`artius_te` 配套文本编码器/VAE）、`imagine`、`miaomiao`；`mix` 改为工作流原版 Moody-Moss-Mix V1 25STEPS CFG3（之前是 HF 上的 V4.1 近似替代）。各模型推荐采样器/CFG/步数写在清单注释里。

- 新增 `model_lists/moss_image.txt`：MOSS-Image 生图整合工作流的模型清单。默认约 15.4GB（工作流默认启用的一组：SFT INT8 主模型 + Qwen3.5-9B INT8 文本编码器 + flux2 小 VAE），可选标签 `vaefull`、`base`、`bf16`、`w4a8`、`turbo8`（8 步蒸馏 LoRA）、`mix`（Moody-Moss-Mix 风格混合）、`seedvr2`（SeedVR2 7B 超分）。11 个链接已 dry-run + HEAD 验证。源：Comfy-Org/MOSS-Image、lodestones/MOSS-Image-SFT-8-steps-dmd、catlover1937/moody-moss-mix、Comfy-Org/SeedVR2。
- `scripts/install_nodes.sh`：新增 `seedvr2` 节点与 `moss`（rgthree+easyuse）、`moss-full`（+seedvr2）别名。注：工作流默认启用的 `ResolutionSelector` 节点来源待确认需手动装；`TE-Speed-MOSS`（TESpeedMoss 加速节点）仅 Windows x64 + Py3.13、以 nodes.pyd 发布，昇腾/aarch64 无法加载，好在工作流里默认旁路，不影响出图。

## 2026-11-10

- **修复 910B 上 cv2 导入报错 `libGLdispatch.so.0: cannot allocate memory in static TLS block`**：torch_npu 等先加载占满静态 TLS，等 opencv 的 libGLdispatch 再 dlopen 就没槽了。症状是 `import cv2` 崩，连带弄挂所有 import cv2 的节点——ComfyUI_LayerStyle、ComfyUI-Easy-Use 整个 IMPORT FAILED，孤海包虽加载成功但 `GH_MaskCropV2`、`GH_CropRestore`、`TextEncodeQwenImage21GH` 等 import cv2 的节点被静默跳过（工作流里显示缺失节点）。`start_comfyui.sh` 现在把 `libGLdispatch.so.0`（和 `libgomp.so.1`）加入 `LD_PRELOAD`，在进程启动、静态 TLS 还够时就拿到槽位。

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

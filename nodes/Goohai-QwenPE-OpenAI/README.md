# Qwen image 2.1 提示词优化（OpenAI 兼容接口）

孤海「Qwen image 2.1 提示词优化」(`QwenImagePromptOptimizer`) 的远程版，节点 ID `QwenImagePromptOptimizerOpenAI`，分类「孤海工具箱/提示词」。

和原节点一样的部分（直接调用已安装的 Goohaitools-comfyui 里 `resources/qwen_image_runtime.py` 的函数，孤海更新后自动跟随）：
- 文生图 / 图生图 / 反推（有图且提示词为空）三套系统提示词，自定义 skill 输入
- 输出语言锁、透明背景改写与后处理、图像编号约束、图片缩放（1 张 768、反推 1536、2~4 张 512、更多 256）
- 采样参数 temperature 0.3、top_p 0.9、top_k 30、min_p 0.05、关闭思考、max_tokens 2048、种子
- JSON 解析失败时带 `response_format=json_object` 重试一次
- 输出 `prompt`、`json`、`是否反推`

不同的部分：
- 推理走 `POST {接口地址}/chat/completions`。`top_k`、`min_p`、`chat_template_kwargs` 是 llama.cpp / vLLM 的扩展参数，接口不认（400/422）时自动去掉
- 默认用流式请求（`stream: true`），避免 Cloudflare 等网关在模型思考时报 524；`QWEN_PE_STREAM=0` 关闭。HTTP 429 / 5xx / 524 自动重试 2 次
- 不需要 llama-cpp-python 和 GGUF 模型，也没有「卸载模型」选项
- 图生图和反推要求接口上的模型支持图像输入（如 Qwen3-VL / Qwen2.5-VL 系列）。用孤海 PE 模型本身的话，可以在另一台机器上用 `llama-server -m Qwen-Image-2.1-PE-I2I.Q5_K_S.gguf --mmproj Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf` 起服务再填地址，效果与本地节点一致

配置（节点里留空时按顺序读取）：
1. 环境变量 `QWEN_PE_BASE_URL`、`QWEN_PE_MODEL`、`QWEN_PE_API_KEY`（再没有就用 `OPENAI_API_KEY`）
2. 本目录的 `config.json`：`{"base_url": "...", "model": "...", "api_key": "..."}`

接口地址可以写到 `/v1`，也可以写完整的 `/chat/completions`；只写域名会自动补 `/v1`。API Key 写在节点里会随工作流保存，分享前清空。

许可证：逻辑改写自 goohai/Goohaitools-comfyui（GPL-3.0），同样以 GPL-3.0 分发。依赖：孤海工具箱需已安装。

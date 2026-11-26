"""Qwen image 2.1 提示词优化（OpenAI 兼容接口）

复刻孤海工具箱「Qwen image 2.1 提示词优化」(QwenImagePromptOptimizer) 节点的完整流程：
系统提示词（文生图 / 图生图 / 反推）、语言锁、透明背景改写、图像编号约束、
采样参数、JSON 解析与重试、透明背景后处理、三个输出全部与原节点一致，
只把本地 llama-cpp-python 推理换成远程 OpenAI 兼容接口（/v1/chat/completions）。

系统提示词和处理函数直接从已安装的 Goohaitools-comfyui 的
resources/qwen_image_runtime.py 读取，孤海更新提示词后这里自动跟随，不会出现两份不一致。

基于 goohai/Goohaitools-comfyui（GPL-3.0）的逻辑改写，同样以 GPL-3.0 分发。
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import folder_paths

NODE_ID = "QwenImagePromptOptimizerOpenAI"
DISPLAY_NAME = "Qwen image 2.1 提示词优化（OpenAI 兼容接口）"
_HERE = Path(__file__).resolve().parent
_CONFIG_FILE = _HERE / "config.json"
_RT = None


# ---------------------------------------------------------------- 孤海运行时
def _goohai_runtime():
    """拿到孤海的 qwen_image_runtime 模块（已加载就复用，否则按路径加载）。"""
    global _RT
    if _RT is not None:
        return _RT
    mod = sys.modules.get("resources.qwen_image_runtime")
    if mod is not None and "goohai" in str(getattr(mod, "__file__", "")).lower():
        _RT = mod
        return _RT
    candidates = []
    for root in folder_paths.get_folder_paths("custom_nodes"):
        p = Path(root)
        if not p.is_dir():
            continue
        for d in sorted(p.iterdir()):
            if d.is_dir() and d.name.lower().startswith("goohaitools"):
                f = d / "resources" / "qwen_image_runtime.py"
                if f.is_file():
                    candidates.append(f)
    if not candidates:
        raise RuntimeError(
            "找不到孤海工具箱（Goohaitools-comfyui）的 resources/qwen_image_runtime.py。"
            "本节点直接复用孤海的系统提示词，请先安装：bash scripts/install_nodes.sh goohai"
        )
    spec = importlib.util.spec_from_file_location("goohai_qwen_image_runtime_openai", candidates[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _RT = mod
    return _RT


# ---------------------------------------------------------------- 配置
def _config() -> dict:
    try:
        return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[QwenPE-OpenAI] config.json 读取失败：{exc}", flush=True)
        return {}


def _pick(widget: str, env: str, key: str, default: str = "") -> str:
    v = str(widget or "").strip()
    if v:
        return v
    v = os.environ.get(env, "").strip()
    if v:
        return v
    return str(_config().get(key, "") or default).strip()


def _endpoint(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if not re.search(r"/v\d+[a-z]*$", url):
        url += "/v1"
    return url + "/chat/completions"


# ---------------------------------------------------------------- HTTP
class _HTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status


def _post(url: str, api_key: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _HTTPError(exc.code, exc.read().decode("utf-8", "replace")) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 {url}：{exc.reason}") from None


_NO_EXTRAS: set[str] = set()


def _chat(url, api_key, payload, extras, timeout):
    """先带上 llama.cpp / vLLM 风格的额外采样参数；服务端不认（HTTP 400/422）就去掉重试，并记住该地址。"""
    if extras and url not in _NO_EXTRAS:
        try:
            return _post(url, api_key, {**payload, **extras}, timeout)
        except _HTTPError as exc:
            if exc.status not in (400, 422):
                raise
            _NO_EXTRAS.add(url)
            print(f"[QwenPE-OpenAI] 接口不接受额外参数 {list(extras)}，去掉后重试", flush=True)
    return _post(url, api_key, payload, timeout)


def _content(resp: dict) -> str:
    try:
        msg = resp["choices"][0]["message"]
    except Exception:
        raise RuntimeError(f"接口返回格式不对：{json.dumps(resp, ensure_ascii=False)[:500]}") from None
    text = msg.get("content")
    if isinstance(text, list):  # 少数服务端返回分段 content
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return str(text or "")


# ---------------------------------------------------------------- 节点
class QwenImagePromptOptimizerOpenAI:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "用户提示词": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "接口地址": ("STRING", {"default": "", "tooltip": "OpenAI 兼容接口，如 https://api.example.com/v1。留空则读环境变量 QWEN_PE_BASE_URL 或本节点目录的 config.json"}),
                "模型名称": ("STRING", {"default": "", "tooltip": "接口上的模型 ID（需支持图像输入才能用图生图/反推）。留空读 QWEN_PE_MODEL 或 config.json"}),
                "API_Key": ("STRING", {"default": "", "tooltip": "留空读 QWEN_PE_API_KEY / OPENAI_API_KEY 或 config.json。写在这里会被保存进工作流文件，分享工作流前请清空"}),
                "输出语言": (["自动", "中文", "English"], {"default": "自动"}),
                "透明背景": ("BOOLEAN", {"default": False}),
                "种子值": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFF}),
                "种子模式": (["固定", "随机"], {"default": "固定"}),
                "超时秒数": ("INT", {"default": 180, "min": 10, "max": 1800}),
            },
            "optional": {
                **{f"图像_{index:02d}": ("IMAGE",) for index in range(1, 11)},
                "自定义skill": ("STRING", {
                    "forceInput": True,
                    "tooltip": "连接自定义 skill 或一句简单要求作为系统提示词；未连接或文本为空时使用内置系统提示词。",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("prompt", "json", "是否反推")
    FUNCTION = "optimize"
    CATEGORY = "孤海工具箱/提示词"

    @classmethod
    def IS_CHANGED(cls, 种子值=0, 种子模式="固定", **kwargs):
        if 种子模式 == "随机":
            return float("nan")  # 每次都重新执行
        return max(0, min(0xFFFFFFFF, int(种子值)))

    def optimize(self, 用户提示词, 接口地址, 模型名称, API_Key, 输出语言, 透明背景, 种子值,
                 种子模式="固定", 超时秒数=180, 自定义skill=None, **kwargs):
        rt = _goohai_runtime()
        base_url = _pick(接口地址, "QWEN_PE_BASE_URL", "base_url")
        model = _pick(模型名称, "QWEN_PE_MODEL", "model")
        api_key = _pick(API_Key, "QWEN_PE_API_KEY", "api_key") or os.environ.get("OPENAI_API_KEY", "").strip()
        if not base_url:
            raise ValueError("没有设置接口地址：填写节点的「接口地址」，或设置环境变量 QWEN_PE_BASE_URL")
        if not model:
            raise ValueError("没有设置模型名称：填写节点的「模型名称」，或设置环境变量 QWEN_PE_MODEL")

        # ---- 以下与 QwenImagePromptOptimizer.optimize 相同 ----
        images = rt.collect_images(kwargs)
        has_images = bool(images)
        reverse_mode = has_images and not str(用户提示词 or "").strip()
        if reverse_mode:
            base_system = rt.REVERSE_SYSTEM_PROMPT
            prompt_input = rt.reverse_prompt_instruction(bool(透明背景))
        elif has_images:
            base_system = rt.I2I_SYSTEM_PROMPT
            prompt_input = str(用户提示词 or "").strip()
        else:
            base_system = rt.T2I_SYSTEM_PROMPT
            prompt_input = str(用户提示词 or "").strip()

        if 透明背景 and not reverse_mode:
            prompt_input = rt.rewrite_user_prompt_for_transparency(用户提示词, True)

        custom_system = str(自定义skill or "")
        normalized_skill = " ".join(custom_system.lstrip("\ufeff").split())
        if normalized_skill and normalized_skill != " ".join(base_system.split()):
            base_system = (
                "Optimize the image prompt using these requirements:\n\n"
                + custom_system
                + "\n\nNODE OUTPUT CONTRACT (overrides conflicting format instructions): "
                'Return only JSON: {"rewritten_prompt":"complete final image prompt",'
                '"wh_ratio":"requested width:height ratio or empty string"'
                + (',"ratio_follow":"canvas image tag, e.g. <image1>, or empty string"'
                   if has_images and not reverse_mode else "")
                + "}. rewritten_prompt must be non-empty. No analysis or Markdown fences. "
                + ("ratio_follow is the exact tag of the supplied canvas image, such as "
                   "<image1>, whose aspect ratio should be followed when no explicit ratio "
                   "is requested. Never fill both wh_ratio and ratio_follow; leave "
                   "ratio_follow empty if wh_ratio is specified or no canvas image applies. "
                   if has_images and not reverse_mode else "")
                + "Put all requested content inside rewritten_prompt."
            )
        system_prompt = rt._rewrite_language_rules(
            base_system, 输出语言, str(用户提示词 or ""),
            transparent_background=bool(透明背景), reverse_mode=reverse_mode,
        )
        seed = random.randint(0, 0xFFFFFFFF) if 种子模式 == "随机" else max(0, min(0xFFFFFFFF, int(种子值)))

        # ---- 以下对应 QwenImageRuntime.complete，推理换成 HTTP ----
        editing_mode = has_images and not reverse_mode
        image_count = len(images)
        if image_count == 0:
            image_max_size = 0
        elif image_count == 1 and reverse_mode:
            image_max_size = 1536
        elif image_count == 1:
            image_max_size = 768
        elif image_count <= 4:
            image_max_size = 512
        else:
            image_max_size = 256

        wrapped = rt._wrap_user_prompt_for_language(
            prompt_input, 输出语言, str(用户提示词 or ""),
            transparent_background=bool(透明背景), image_count=image_count, reverse_mode=reverse_mode,
        )
        if has_images:
            content = [{"type": "text", "text": wrapped}]
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": rt._image_data_url(image, image_max_size)}})
            selected = "Chinese" if (reverse_mode and 输出语言 == "自动") else rt._selected_output_language(输出语言, str(用户提示词 or ""))
            content.append({"type": "text", "text": rt._final_language_directive(selected)})
        else:
            content = wrapped
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]

        max_tokens = int(getattr(rt, "DEFAULT_MAX_OUTPUT_TOKENS", 2048))
        payload = {"model": model, "messages": messages, "seed": seed, "temperature": 0.3,
                   "top_p": 0.9, "max_tokens": max_tokens, "stream": False}
        # 原节点的 top_k / min_p / reasoning_budget=0（关思考）；OpenAI 官方接口不认时自动去掉
        extras = {"top_k": 30, "min_p": 0.05, "chat_template_kwargs": {"enable_thinking": False}}
        url = _endpoint(base_url)
        timeout = int(超时秒数)

        started = time.perf_counter()
        attempts = 1
        resp = _chat(url, api_key, payload, extras, timeout)
        text = _content(resp)
        try:
            parsed = rt._normalize_result(rt._parse_json(text), editing_mode)
        except ValueError:
            attempts += 1
            retry = dict(payload, response_format={"type": "json_object"})
            try:
                resp = _chat(url, api_key, retry, extras, timeout)
            except _HTTPError as exc:
                if exc.status not in (400, 422):
                    raise
                resp = _chat(url, api_key, payload, extras, timeout)
            text = _content(resp)
            parsed = rt._normalize_result(rt._parse_json(text), editing_mode)
        usage = resp.get("usage", {}) if isinstance(resp, dict) else {}
        print(
            f"[QwenPE-OpenAI] model={model}, total={time.perf_counter() - started:.2f}s, images={image_count}, "
            f"attempts={attempts}, output_chars={len(text)}, prompt_tokens={usage.get('prompt_tokens', '?')}, "
            f"completion_tokens={usage.get('completion_tokens', '?')}",
            flush=True,
        )
        return {
            "ui": {"seed": [seed]},
            "result": (
                rt.prompt_text_from_result(parsed, bool(透明背景)),
                rt.json_text_from_result(parsed, bool(透明背景)),
                reverse_mode,
            ),
        }


NODE_CLASS_MAPPINGS = {NODE_ID: QwenImagePromptOptimizerOpenAI}
NODE_DISPLAY_NAME_MAPPINGS = {NODE_ID: DISPLAY_NAME}

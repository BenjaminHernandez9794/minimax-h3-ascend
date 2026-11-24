# -*- coding: utf-8 -*-
"""
检查 ComfyUI 的 models 目录缺哪些模型（只读，不下载、不改文件）。

两种对照来源，可以同时用：
  -l 清单   按 model_lists/ 里的下载清单检查（标签规则与 download_models.sh 相同：#@default、--with、--without）
  -w 工作流 扫描工作流 JSON（界面格式或 API 格式，含子图）里各加载节点引用的模型文件
都不给时：逐个检查 model_lists/ 下的全部清单（nvidia.txt 除外，加 --nvidia 才查）。

用法：
  bash scripts/check_models.sh                                   # 全部清单概览
  bash scripts/check_models.sh -l qwen_image_2.1_outfit.txt      # 某个清单（默认标签）
  bash scripts/check_models.sh -l ascend.txt --lowvram           # 低配档
  bash scripts/check_models.sh -l ascend.txt --all-tags          # 清单里的可选文件也算上
  bash scripts/check_models.sh -w "Qwen 2.1 换装.json"           # 按工作流检查
  bash scripts/check_models.sh -w a.json -w b.json -l ascend.txt
  bash scripts/check_models.sh -q                                # 只显示有问题的行

状态：
  OK      文件在、大小非 0
  缺失    没有这个文件
  下载中  只有 .part（断点续传的半成品），会显示进度；重跑下载命令即可续传
  空文件  大小为 0，多半是下载中断，建议删掉重下
  目录错  文件在别的模型目录里，对应的加载节点读不到（如 VAE 放进了 loras）
  可选    工作流里被旁路 / 静音的节点用到的模型，缺了不影响运行

退出码：有「缺失 / 下载中 / 空文件 / 目录错」时为 1，否则为 0（可用于脚本判断）。
不联网：Civitai 来源若清单里没写目标文件名，会尝试查一次 Civitai API 拿文件名，查不到就标「未知」。
"""
import argparse
import glob
import json
import os
import sys
import types

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_DIR = os.path.join(REPO_DIR, "model_lists")
sys.path.insert(0, os.path.join(REPO_DIR, "scripts"))
try:
    import requests  # noqa: F401  dl_models 顶层会 import，缺了也不影响检查
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import dl_models as dl  # noqa: E402

MODEL_EXT = (".safetensors", ".sft", ".ckpt", ".pt", ".pt2", ".pth", ".bin", ".gguf", ".onnx", ".pkl", ".engine")

# ComfyUI 的模型目录别名（folder_paths 里同一类会查多个目录）
FOLDER_ALIASES = {
    "diffusion_models": {"diffusion_models", "unet"},
    "unet": {"diffusion_models", "unet"},
    "text_encoders": {"text_encoders", "clip"},
    "clip": {"text_encoders", "clip"},
    "checkpoints": {"checkpoints"},
    "vae": {"vae"},
    "loras": {"loras"},
    "clip_vision": {"clip_vision"},
    "controlnet": {"controlnet", "t2i_adapter"},
    "upscale_models": {"upscale_models", "latent_upscale_models"},
    "latent_upscale_models": {"upscale_models", "latent_upscale_models"},
}

# 加载节点 → (控件序号, 模型目录)；没列出的节点只按文件名在整个 models 下找
NODE_FOLDERS = {
    "UNETLoader": {0: "diffusion_models"},
    "UnetLoaderGGUF": {0: "diffusion_models"},
    "CLIPLoader": {0: "text_encoders"},
    "CLIPLoaderGGUF": {0: "text_encoders"},
    "DualCLIPLoader": {0: "text_encoders", 1: "text_encoders"},
    "TripleCLIPLoader": {0: "text_encoders", 1: "text_encoders", 2: "text_encoders"},
    "QuadrupleCLIPLoader": {0: "text_encoders", 1: "text_encoders", 2: "text_encoders", 3: "text_encoders"},
    "VAELoader": {0: "vae"},
    "CheckpointLoaderSimple": {0: "checkpoints"},
    "ImageOnlyCheckpointLoader": {0: "checkpoints"},
    "LoraLoader": {0: "loras"},
    "LoraLoaderModelOnly": {0: "loras"},
    "CLIPVisionLoader": {0: "clip_vision"},
    "ControlNetLoader": {0: "controlnet"},
    "UpscaleModelLoader": {0: "upscale_models"},
    "LatentUpscaleModelLoader": {0: "latent_upscale_models"},
}
INPUT_FOLDERS = {"unet_name": "diffusion_models", "clip_name": "text_encoders", "clip_name1": "text_encoders",
                 "clip_name2": "text_encoders", "clip_name3": "text_encoders", "clip_name4": "text_encoders",
                 "vae_name": "vae", "ckpt_name": "checkpoints", "lora_name": "loras",
                 "control_net_name": "controlnet", "model_name": None}

GHIL_INDEX = {"服装": ("costume", "costume-zh.json"), "姿势": ("pose", "pose-zh.json"),
              "发型": ("hair", "hairstyle-zh.json"), "人像": ("portrait", "portrait-zh.json")}

BAD = {"缺失", "下载中", "空文件", "目录错"}


def color(s, c):
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return s
    return f"\033[{c}m{s}\033[0m"


STATUS_COLOR = {"OK": "32", "缺失": "31", "下载中": "33", "空文件": "31", "目录错": "35", "可选": "36", "未知": "33"}


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.2f}{u}" if u == "GB" else f"{n:.0f}{u}"
        n /= 1024


# ---------------------------------------------------------------- 文件状态
def file_status(path):
    """返回 (状态, 说明)。"""
    if os.path.isfile(path):
        size = os.path.getsize(path)
        if size == 0:
            return "空文件", "0 字节"
        legacy = glob.glob(glob.escape(path) + ".p[0-9]*")
        if os.path.exists(path + ".part") or legacy:
            return "下载中", "旧文件旁边还有未完成的分片"
        return "OK", human(size)
    part = path + ".part"
    if os.path.exists(part):
        note = "有 .part"
        try:
            st = json.load(open(part + ".json"))
            pct = len(st.get("done", [])) * st.get("chunk", dl.CHUNK) / max(st.get("size", 1), 1) * 100
            note = f"{min(pct, 100):.0f}% / {human(st.get('size', 0))}"
        except Exception:
            pass
        return "下载中", note
    if os.path.isdir(path):
        return "OK", "目录"
    return "缺失", ""


class ModelIndex:
    """models 目录下所有文件，按文件名索引（跟随符号链接），用来找「放错目录」和工作流里的相对路径。"""

    def __init__(self, roots):
        self.roots = roots
        self.by_name = {}
        for root in roots:
            for d, dirs, files in os.walk(root, followlinks=True):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                for f in files:
                    if f.endswith((".part", ".json", ".tmp")):
                        continue
                    rel = os.path.relpath(os.path.join(d, f), root)
                    self.by_name.setdefault(f, []).append((root, rel))

    def find(self, name):
        """name 可以是 'x.safetensors' 或 'sub/x.safetensors'。返回 [(root, rel)]。"""
        base = os.path.basename(name.replace("\\", "/"))
        tail = name.replace("\\", "/")
        hits = [h for h in self.by_name.get(base, []) if h[1].replace(os.sep, "/").endswith(tail)]
        return hits or self.by_name.get(base, [])


def top_folder(rel):
    return rel.replace(os.sep, "/").split("/", 1)[0]


# ---------------------------------------------------------------- 清单
def check_lists(lists, tag_ops, all_tags_on, models_dir, index, endpoint, quiet):
    entries, tags, all_tags = [], set(), set()
    for lp in lists:
        e, d, t = dl.parse_list(lp)
        entries += e; tags |= d; all_tags |= t
    if all_tags_on:
        tags |= all_tags
    for on, v in tag_ops:
        (tags.update if on else tags.difference_update)(dl.split_csv([v]))
    rows, seen = [], set()
    for e in entries:
        if not e.enabled(tags):
            continue
        try:
            _, fname = dl.build_url(e.src, endpoint)
        except SystemExit:
            raise
        except Exception:
            fname = None
        if fname is None or (fname.startswith("civitai_") and not os.path.splitext(dl.unquote(e.dest))[1]):
            rows.append(("未知", e.src, e.dest, "Civitai 文件名查不到（离线？），无法判断"))
            continue
        path = dl.local_path(models_dir, e.dest, fname)
        if path in seen:
            continue
        seen.add(path)
        st, note = file_status(path)
        if st == "缺失":
            hits = [h for h in index.find(fname)]
            if hits:
                st, note = "目录错", "在 " + ", ".join(os.path.join(r, p) for r, p in hits[:2])
        rel = os.path.relpath(path, models_dir) if path.startswith(models_dir) else path
        rows.append((st, rel, e.origin, note))
    print(color(f"== 清单 {', '.join(lists)}", "1") + f"  |  标签: {', '.join(sorted(tags)) or '(无)'}")
    print_rows(rows, quiet)
    bad = [r for r in rows if r[0] in BAD]
    if bad:
        args = " ".join(f"-l {x}" for x in lists)
        ops = []
        if all_tags_on and all_tags:
            ops.append("--with " + ",".join(sorted(all_tags)))
        ops += [("--with " if on else "--without ") + v for on, v in tag_ops]
        print(f"   补齐: bash scripts/download_models.sh {args} {' '.join(ops)}".rstrip())
        if any(r[0] == "目录错" for r in bad):
            print("   「目录错」的文件直接 mv 到清单写的目录即可，不用重下")
    return rows


# ---------------------------------------------------------------- 工作流
def iter_ui_nodes(w):
    for n in w.get("nodes", []) or []:
        yield n
    for sg in (w.get("definitions") or {}).get("subgraphs", []) or []:
        for n in sg.get("nodes", []) or []:
            yield n


def strings_in(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from strings_in(x)
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings_in(x)


def workflow_refs(path):
    """返回 [(节点描述, 文件名, 期望目录或 None, 是否旁路)] 和 GHIL 引用 [(节点描述, 类型, 是否旁路)]。"""
    w = json.load(open(path, encoding="utf-8"))
    refs, ghil, known_dirs = [], [], {}
    if isinstance(w, dict) and "nodes" in w:
        for n in iter_ui_nodes(w):
            ntype = n.get("type", "?")
            off = n.get("mode") in (2, 4)
            who = f"#{n.get('id')} {ntype}"
            for m in (n.get("properties") or {}).get("models", []) or []:
                if m.get("name") and m.get("directory"):
                    known_dirs[m["name"]] = m["directory"]
            wv = n.get("widgets_values")
            if ntype == "GoohaiImageLibrary" and isinstance(wv, list) and wv and wv[0] in GHIL_INDEX:
                ghil.append((who, wv[0], off))
                continue
            fmap = NODE_FOLDERS.get(ntype, {})
            vals = wv if isinstance(wv, list) else list(strings_in(wv))
            for i, v in enumerate(vals):
                for s in strings_in(v):
                    if s.lower().endswith(MODEL_EXT) and "\n" not in s and len(s) < 300:
                        refs.append((who, s, fmap.get(i), off))
    elif isinstance(w, dict):  # API 格式
        for nid, n in w.items():
            if not isinstance(n, dict) or "class_type" not in n:
                continue
            ntype, who = n["class_type"], f"#{nid} {n['class_type']}"
            ins = n.get("inputs", {}) or {}
            if ntype == "GoohaiImageLibrary":
                kind = next((v for v in ins.values() if isinstance(v, str) and v in GHIL_INDEX), None)
                if kind:
                    ghil.append((who, kind, False))
                continue
            for k, v in ins.items():
                if isinstance(v, str) and v.lower().endswith(MODEL_EXT) and "\n" not in v:
                    folder = INPUT_FOLDERS.get(k)
                    if ntype in NODE_FOLDERS and folder is None:
                        folder = NODE_FOLDERS[ntype].get(0)
                    refs.append((who, v, folder, False))
    refs = [(who, s, folder or known_dirs.get(os.path.basename(s)), off) for who, s, folder, off in refs]
    return refs, ghil


def list_hint(fname):
    """在 model_lists 里找哪个清单能下载这个文件。"""
    out = []
    for p in sorted(glob.glob(os.path.join(LIST_DIR, "*.txt"))):
        try:
            for line in open(p, encoding="utf-8"):
                s = line.split(" #", 1)[0].strip()
                if s and not s.startswith("#") and fname in dl.unquote(s.split()[0]):
                    out.append(os.path.basename(p)); break
        except OSError:
            pass
    return out


def check_workflow(path, models_dir, index, quiet):
    refs, ghil = workflow_refs(path)
    rows, seen = [], {}
    for who, name, folder, off in refs:
        key = (name, folder)
        if key in seen:
            continue
        hits = index.find(name)
        want = FOLDER_ALIASES.get(folder, {folder}) if folder else None
        good = [h for h in hits if want is None or top_folder(h[1]) in want]
        if good:
            r, p = good[0]
            st, note = file_status(os.path.join(r, p))
            shown = p
        elif hits:
            st, note, shown = "目录错", f"应在 {folder}/，实际在 {hits[0][1]}", name
        else:
            st, shown = "缺失", (f"{folder}/{name}" if folder else name)
            part = [g for g in glob.glob(os.path.join(models_dir, "**", glob.escape(os.path.basename(name)) + ".part"), recursive=True)]
            if part:
                st, note = file_status(part[0][:-5])
            else:
                lists = list_hint(os.path.basename(name))
                note = ("清单: " + ", ".join(lists)) if lists else "model_lists 里没有，需自行下载"
        real = st
        if off and st in BAD:
            st, note = "可选", f"{real}（节点已旁路/静音）"
        seen[key] = len(rows)
        rows.append((st, shown, who, note, real))
    # 同一个文件既有旁路节点又有正常节点 → 以正常节点为准
    for who, name, folder, off in refs:
        if not off:
            i = seen[(name, folder)]
            if rows[i][0] == "可选":
                rows[i] = (rows[i][4], rows[i][1], who, rows[i][3].split("（")[0], rows[i][4])
    for who, kind, off in ghil:
        sub, idx = GHIL_INDEX[kind]
        p = os.path.join(models_dir, "GHIL", sub, "data", idx)
        st = "OK" if os.path.isfile(p) else "缺失"
        note = "" if st == "OK" else "图库素材，见 nodes/Goohai-ImageLibrary-Comfyui/README.md；改用「上传」可不需要"
        if off and st != "OK":
            st, note = "可选", "缺失（节点已旁路/静音）"
        rows.append((st, f"GHIL/{sub}/data/{idx}", who, note, st))
    print(color(f"== 工作流 {os.path.basename(path)}", "1") + f"  |  引用 {len(rows)} 个模型/图库")
    print_rows([r[:4] for r in rows], quiet)
    return [r[:4] for r in rows]


# ---------------------------------------------------------------- 输出
def pad(s, width):
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)
    return s + " " * max(width - w, 0)


def print_rows(rows, quiet):
    for st, name, src, note in rows:
        if quiet and st in ("OK", "可选"):
            continue
        tag = color(pad(st, 6), STATUS_COLOR.get(st, "0"))
        print(f"   [{tag}] {name}" + (f"  ({note})" if note else "") + (f"  ← {src}" if st != "OK" else ""))
    ok = sum(r[0] == "OK" for r in rows)
    bad = sum(r[0] in BAD for r in rows)
    print(f"   小计: {ok}/{len(rows)} 齐全" + (color(f"，{bad} 项有问题", "31") if bad else ""))


def main():
    ap = argparse.ArgumentParser(description="检查 ComfyUI models 目录缺哪些模型", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("用法：", 1)[1] if "用法：" in __doc__ else None)
    ap.add_argument("-l", "--list", action="append", default=[], help="模型清单（可多次；可写 model_lists/ 下的文件名）")
    ap.add_argument("-w", "--workflow", action="append", default=[], help="工作流 JSON（可多次）")
    ap.add_argument("--with", dest="tag_ops", action=dl.TagOp, metavar="TAGS", help="开启清单可选标签")
    ap.add_argument("--without", dest="tag_ops", action=dl.TagOp, metavar="TAGS", help="关闭清单标签")
    ap.add_argument("--lowvram", action="store_true", help="同 download_models.sh --lowvram（ascend.txt 低配档）")
    ap.add_argument("--all-tags", action="store_true", help="清单里所有可选文件都检查")
    ap.add_argument("--nvidia", action="store_true", help="不带 -l/-w 时也检查 nvidia.txt")
    ap.add_argument("--models-dir", action="append", help="模型根目录（默认 $COMFY_HOME/models；可多次，用于 extra_model_paths）")
    ap.add_argument("-q", "--quiet", action="store_true", help="只显示有问题的行")
    a = ap.parse_args()

    dirs = a.models_dir or [os.path.join(os.environ.get("COMFY_HOME", "/mnt/workspace/ComfyUI"), "models")]
    dirs = [os.path.abspath(d) for d in dirs]
    models_dir = dirs[0]
    if not os.path.isdir(models_dir):
        sys.exit(f"[错误] 找不到模型目录: {models_dir}（设置 COMFY_HOME 或 --models-dir）")
    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    tag_ops = list(a.tag_ops or [])
    if a.lowvram:
        tag_ops = [(False, "full,ref2va,heretic"), (True, "pruned")] + tag_ops

    print(f"模型目录: {', '.join(dirs)}")
    index = ModelIndex(dirs)
    rows = []
    for wf in a.workflow:
        if not os.path.isfile(wf):
            sys.exit(f"[错误] 找不到工作流: {wf}")
        rows += check_workflow(wf, models_dir, index, a.quiet)
    if a.list:
        rows += check_lists(a.list, tag_ops, a.all_tags, models_dir, index, endpoint, a.quiet)
    elif not a.workflow:
        for p in sorted(glob.glob(os.path.join(LIST_DIR, "*.txt"))):
            name = os.path.basename(p)
            if name == "nvidia.txt" and not a.nvidia:
                continue
            rows += check_lists([name], tag_ops, a.all_tags, models_dir, index, endpoint, a.quiet)

    bad = sum(r[0] in BAD for r in rows)
    unknown = sum(r[0] == "未知" for r in rows)
    print()
    if bad:
        print(color(f"共 {bad} 项缺失或不完整", "31") + (f"，{unknown} 项无法判断" if unknown else ""))
        return 1
    print(color("全部齐全", "32") + (f"（{unknown} 项无法判断）" if unknown else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
MiniMax-H3 on Ascend —— 通用模型下载器

特点：分片并行（默认 32 连接/文件）、断点续传、多文件并行、可选 sha256 校验、走 hf-mirror。
下载哪些模型由「模型清单文件」决定（默认 model_lists/ascend.txt），格式见 model_lists/README.md。

用法：
  python3 scripts/dl_models.py                                # 默认清单（昇腾）
  python3 scripts/dl_models.py -l my_models.txt               # 指定清单，可多次 -l
  python3 scripts/dl_models.py -l a.txt --with pruned --without full,heretic
  python3 scripts/dl_models.py --dry-run                      # 只列出将下载的文件
  python3 scripts/dl_models.py --verify                       # 下载后按 HF 的 sha256 校验
  python3 scripts/dl_models.py --list-tags                    # 查看清单里有哪些可选标签

常用环境变量（命令行参数优先）：
  COMFY_HOME       ComfyUI 根目录，模型落到 $COMFY_HOME/models（默认 /mnt/workspace/ComfyUI）
  MODEL_LIST       清单文件，多个用逗号分隔（等价于 -l）
  HF_ENDPOINT      下载源（默认 https://hf-mirror.com）
  HF_TOKEN         访问受限仓库时使用（只发给 HF 源，不会发给其它站点）
  CIVITAI_TOKEN    Civitai API Key（civitai: 来源必需；在 civitai.com 用户设置 → API Keys 生成）
  CIVITAI_ENDPOINT Civitai 站点（默认 https://civitai.com，可换 https://civitai.red 等镜像域名）
  MAX_CONN         每文件并发连接数（默认 32）
  FILES_PARALLEL   同时下载的文件数（默认 2）
  旧变量仍兼容：INCLUDE_HERETIC_TE / INCLUDE_REF2VA / SKIP_FULL_FL2VA / INCLUDE_PRUNED /
               MODE=nvidia / NVFP4_TE / W6A8
"""
import argparse
import hashlib
import json
import os
from urllib.parse import unquote
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_DIR = os.path.join(REPO_DIR, "model_lists")
CHUNK = int(os.environ.get("CHUNK_MB", "64")) * 1024 * 1024
RETRIES = 6


# ---------------------------------------------------------------- 清单解析
class Entry:
    def __init__(self, src, dest, conds, origin):
        self.src, self.dest, self.conds, self.origin = src, dest, conds, origin

    def enabled(self, tags):
        # 所有条件都满足才下载：tag 需开启，!tag 需关闭
        for c in self.conds:
            if c.startswith("!"):
                if c[1:] in tags:
                    return False
            elif c not in tags:
                return False
        return True


def resolve_list_path(p):
    if os.path.exists(p):
        return p
    for cand in (os.path.join(LIST_DIR, p), os.path.join(LIST_DIR, p + ".txt")):
        if os.path.exists(cand):
            return cand
    sys.exit(f"[错误] 找不到模型清单: {p}（也查找了 {LIST_DIR}/）")


def parse_list(path, seen=None):
    """返回 (entries, default_tags, all_tags)。支持 #@default 和 #@include 指令。"""
    path = os.path.abspath(resolve_list_path(path))
    seen = seen if seen is not None else set()
    if path in seen:
        return [], set(), set()
    seen.add(path)
    entries, defaults, all_tags = [], set(), set()
    with open(path, encoding="utf-8") as f:
        for no, raw in enumerate(f, 1):
            line = raw.strip()
            if line.startswith("#@default"):
                defaults |= {t for t in line[len("#@default"):].replace(",", " ").split() if t}
                continue
            if line.startswith("#@include"):
                inc = line[len("#@include"):].strip()
                inc_path = inc if os.path.isabs(inc) else os.path.join(os.path.dirname(path), inc)
                e, d, a = parse_list(inc_path, seen)
                entries += e; defaults |= d; all_tags |= a
                continue
            line = line.split(" #", 1)[0].split("\t#", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                sys.exit(f"[错误] {path}:{no} 至少需要两列：<来源> <目标目录>\n  {raw.rstrip()}")
            conds = []
            for p in parts[2:]:
                conds += [c for c in p.split(",") if c]
            all_tags |= {c.lstrip("!") for c in conds}
            entries.append(Entry(parts[0], parts[1], conds, f"{os.path.basename(path)}:{no}"))
    return entries, defaults, all_tags


CIVITAI_ENDPOINT = os.environ.get("CIVITAI_ENDPOINT", "https://civitai.com").rstrip("/")
CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN") or os.environ.get("CIVITAI_API_KEY") or ""
_civitai_meta = {}


def civitai_file(version, file_id=None):
    """查 Civitai 公开 API，返回 (文件名, 大约字节数)。不需要 token。"""
    key = (version, file_id)
    if key in _civitai_meta:
        return _civitai_meta[key]
    r = requests.get(f"{CIVITAI_ENDPOINT}/api/v1/model-versions/{version}", timeout=60)
    r.raise_for_status()
    files = r.json().get("files", [])
    pick = None
    for f in files:
        if file_id is not None and str(f.get("id")) == str(file_id):
            pick = f
        elif file_id is None and f.get("primary"):
            pick = f
    if pick is None and file_id is None and files:
        pick = files[0]
    if pick is None:
        raise RuntimeError(f"Civitai 版本 {version} 里没有 fileId={file_id}")
    _civitai_meta[key] = (pick["name"], int(pick.get("sizeKB", 0) * 1024) or None)
    return _civitai_meta[key]


def build_url(src, endpoint):
    """repo:path[@rev] → HF resolve URL；civitai:<版本ID>[@<fileId>] → Civitai 下载链接；http(s) 原样返回。"""
    if src.startswith(("http://", "https://")):
        return src, unquote(os.path.basename(src.split("?", 1)[0]))
    if src.startswith("civitai:"):
        ref = src[len("civitai:"):]
        version, file_id = (ref.split("@", 1) + [None])[:2]
        url = f"{CIVITAI_ENDPOINT}/api/download/models/{version}" + (f"?fileId={file_id}" if file_id else "")
        try:
            fname = civitai_file(version, file_id)[0]
        except Exception:
            fname = f"civitai_{version}_{file_id or 'primary'}.safetensors"
        return url, fname
    if ":" not in src:
        sys.exit(f"[错误] 来源格式应为 <repo>:<仓库内路径>[@revision]、civitai:<版本ID>[@<fileId>] 或完整 URL: {src}")
    repo, rpath = src.split(":", 1)
    rev = "main"
    if "@" in rpath:
        rpath, rev = rpath.rsplit("@", 1)
    # 路径里的空格写成 %20（清单按空白分列）；本地文件名按解码后的名字保存
    return f"{endpoint.rstrip('/')}/{repo}/resolve/{rev}/{rpath}", unquote(os.path.basename(rpath))


def is_civitai(url):
    return url.startswith(CIVITAI_ENDPOINT + "/api/download/")


def with_token(url):
    """Civitai 下载链接带上 token（只在真正请求时加，打印时不显示）。"""
    if is_civitai(url) and CIVITAI_TOKEN:
        return url + ("&" if "?" in url else "?") + "token=" + CIVITAI_TOKEN
    return url


HF_HOSTS = set()


def auth_headers(url):
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if tok and urlparse(url).netloc in HF_HOSTS:
        return {"Authorization": f"Bearer {tok}"}
    return {}


def local_path(models_dir, dest, fname):
    # dest 以 / 结尾或最后一段不含 "." → 目录；否则视为完整文件路径（可改名）。%20 等转义会被解码
    dest = unquote(dest)
    if dest.endswith("/") or "." not in os.path.basename(dest):
        p = os.path.join(dest, fname)
    else:
        p = dest
    return p if os.path.isabs(p) else os.path.join(models_dir, p)


# ---------------------------------------------------------------- 下载
lock = threading.Lock()
total = [0]


def probe(session, url):
    """手动跟随跳转，拿到最终 URL、大小、sha256（HF 的 X-Linked-Etag）、是否支持 Range。
    不支持 HEAD 的源（如 Civitai 只允许 GET）改用 GET Range: bytes=0-0 探测。"""
    if is_civitai(url) and not CIVITAI_TOKEN:
        raise RuntimeError("Civitai 下载需要 API Key：export CIVITAI_TOKEN=xxxx（civitai.com 用户设置 → API Keys）")
    sha, size, cur = None, None, with_token(url)
    for _ in range(10):
        r = session.head(cur, allow_redirects=False, timeout=60, headers=auth_headers(cur))
        if r.status_code in (405, 501) or (r.status_code in (400, 403, 404) and cur != with_token(url)):
            # HEAD 不被允许（或预签名链接只签了 GET）：用 GET 取 1 字节
            g = session.get(cur, headers={"Range": "bytes=0-0", **auth_headers(cur)}, stream=True,
                            allow_redirects=False, timeout=60)
            g.close()
            if g.status_code in (301, 302, 303, 307, 308) and g.headers.get("Location"):
                cur = urljoin(cur, g.headers["Location"])
                continue
            if g.status_code == 401:
                raise RuntimeError("401 未授权（CIVITAI_TOKEN 无效或该模型需登录）")
            g.raise_for_status()
            cr = g.headers.get("Content-Range", "")
            if g.status_code == 206 and "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                return cur, int(cr.rsplit("/", 1)[1]), sha, True
            return cur, int(g.headers["Content-Length"]) if g.headers.get("Content-Length") else size, sha, False
        h = r.headers
        if h.get("X-Linked-Size"):
            size = int(h["X-Linked-Size"])
        et = (h.get("X-Linked-Etag") or "").strip('"')
        if len(et) == 64:
            sha = et
        if r.status_code in (301, 302, 303, 307, 308) and h.get("Location"):
            cur = urljoin(cur, h["Location"])
            continue
        if r.status_code == 401:
            raise RuntimeError("401 未授权" + ("（CIVITAI_TOKEN 无效或该模型需登录）" if is_civitai(url) else "（受限仓库请设置 HF_TOKEN）"))
        r.raise_for_status()
        if h.get("Content-Length"):
            size = int(h["Content-Length"])
        ranges = h.get("Accept-Ranges", "").lower() == "bytes"
        return cur, size, sha, ranges
    raise RuntimeError("跳转次数过多")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for buf in iter(lambda: f.read(16 << 20), b""):
            h.update(buf)
    return h.hexdigest()


def download(session, url, path, nconn, verify):
    fname = os.path.basename(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    final, size, sha, ranges_ok = probe(session, url)
    if size is None:
        raise RuntimeError(f"{fname}: 服务器未返回文件大小")

    part, state_f = path + ".part", path + ".part.json"
    legacy = [p for p in os.listdir(os.path.dirname(path)) if p.startswith(fname + ".p") and p[len(fname) + 2:].isdigit()]

    if os.path.exists(path) and os.path.getsize(path) == size and not legacy:
        if verify and sha:
            print(f"[校验] {fname} ...", flush=True)
            if sha256_file(path) != sha:
                print(f"[损坏] {fname} sha256 不符，重新下载", flush=True)
                os.remove(path)
            else:
                print(f"[跳过] {fname} ({size/1e9:.2f}GB 已存在，sha256 正确)")
                return True
        else:
            print(f"[跳过] {fname} ({size/1e9:.2f}GB 已存在)")
            return True
    if os.path.exists(path):
        # 旧版脚本预分配的半成品：没有进度记录，只能重下
        print(f"[重下] {fname}：发现旧版下载残留，无法确认完整性", flush=True)
        os.remove(path)
        for p in legacy:
            os.remove(os.path.join(os.path.dirname(path), p))

    done_chunks = set()
    if os.path.exists(state_f) and os.path.exists(part):
        try:
            st = json.load(open(state_f))
            if st.get("size") == size and st.get("chunk") == CHUNK:
                done_chunks = set(st.get("done", []))
        except Exception:
            pass
    if not os.path.exists(part) or os.path.getsize(part) != size:
        with open(part, "wb") as f:
            f.truncate(size)
        done_chunks = set()

    ranges, s = [], 0
    while s < size:
        e = min(s + CHUNK - 1, size - 1)
        ranges.append((s, e)); s = e + 1
    todo = [rg for rg in ranges if rg[0] not in done_chunks]
    if not ranges_ok and len(ranges) > 1:
        print(f"  [提示] {fname}: 源不声明 Range 支持，改为单连接下载", flush=True)
        todo, nconn, ranges = [(0, size - 1)], 1, [(0, size - 1)]
        done_chunks = set()
    print(f"[下载] {fname} ({size/1e9:.2f}GB，剩余 {len(todo)}/{len(ranges)} 段)", flush=True)

    def save_state():
        with lock:
            tmp = state_f + ".tmp"
            json.dump({"url": url, "size": size, "chunk": CHUNK, "sha256": sha, "done": sorted(done_chunks)}, open(tmp, "w"))
            os.replace(tmp, state_f)

    def get(rg):
        a, b = rg
        for attempt in range(RETRIES):
            pos = a
            try:
                hdr = {"Range": f"bytes={a}-{b}"} if ranges_ok else {}
                r = session.get(cur_url[0], headers={**hdr, **auth_headers(cur_url[0])}, stream=True, timeout=90)
                if r.status_code in (403, 410) and cur_url[0] != url:
                    # CDN 签名链接过期：重新探测后重试本段
                    cur_url[0] = probe(session, url)[0]
                    raise RuntimeError(f"链接过期（{r.status_code}），已刷新")
                r.raise_for_status()
                if ranges_ok and r.status_code != 206:
                    raise RuntimeError(f"期望 206，得到 {r.status_code}")
                with open(part, "r+b") as t:
                    t.seek(a)
                    for buf in r.iter_content(1 << 20):
                        if buf:
                            t.write(buf); pos += len(buf)
                            with lock:
                                total[0] += len(buf)
                if pos != b + 1:
                    raise RuntimeError(f"分段不完整 {pos - a}/{b - a + 1}")
                with lock:
                    done_chunks.add(a)
                save_state()
                return True
            except Exception as e:
                with lock:
                    total[0] -= pos - a
                print(f"  [重试 {attempt + 1}/{RETRIES}] {fname} @{a}: {repr(e)[:80]}", flush=True)
                time.sleep(min(2 ** attempt, 30))
        return False

    cur_url = [final]
    with ThreadPoolExecutor(max_workers=max(1, nconn)) as ex:
        list(ex.map(get, todo))

    if not all(rg[0] in done_chunks for rg in ranges):
        print(f"[未完成] {fname}：{sum(rg[0] not in done_chunks for rg in ranges)} 段失败，重跑即可续传", flush=True)
        return False
    if verify and sha:
        print(f"[校验] {fname} ...", flush=True)
        got = sha256_file(part)
        if got != sha:
            print(f"[损坏] {fname} sha256 不符（期望 {sha[:12]}…，实际 {got[:12]}…），已删除进度，请重跑", flush=True)
            os.remove(part); os.remove(state_f)
            return False
    os.replace(part, path)
    if os.path.exists(state_f):
        os.remove(state_f)
    print(f"[完成] {fname}", flush=True)
    return True


# ---------------------------------------------------------------- 入口
def env_flag(name, default=None):
    v = os.environ.get(name)
    if v is None:
        return default
    return v not in ("0", "", "false", "no")


def split_csv(values):
    out = set()
    for v in values or []:
        out |= {t.strip() for t in v.split(",") if t.strip()}
    return out


class TagOp(argparse.Action):
    def __call__(self, parser, ns, values, option_string=None):
        ops = list(getattr(ns, self.dest, None) or [])
        ops.append((option_string == "--with", values))
        setattr(ns, self.dest, ops)


def gb(n):
    return f"{n/1e9:.2f}GB"


def main():
    ap = argparse.ArgumentParser(description="按清单文件下载模型（分片并行 + 断点续传）")
    ap.add_argument("-l", "--list", action="append", help="模型清单文件，可多次指定；可写 model_lists/ 下的文件名")
    # --with / --without 按出现顺序生效，后面的覆盖前面的（--lowvram 展开在前，用户再写 --with ref2va 即可加回）
    ap.add_argument("--with", dest="tag_ops", action=TagOp, metavar="TAGS", help="开启可选标签，逗号分隔")
    ap.add_argument("--without", dest="tag_ops", action=TagOp, metavar="TAGS", help="关闭标签，逗号分隔")
    ap.add_argument("--models-dir", help="模型根目录（默认 $COMFY_HOME/models）")
    ap.add_argument("--endpoint", help="HF 下载源（默认 $HF_ENDPOINT 或 https://hf-mirror.com）")
    ap.add_argument("--conn", type=int, help="每文件并发连接数（默认 $MAX_CONN 或 32）")
    ap.add_argument("--files-parallel", type=int, help="同时下载文件数（默认 $FILES_PARALLEL 或 2）")
    ap.add_argument("--verify", action="store_true", help="用 HF 提供的 sha256 校验（大文件较慢）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将下载的文件")
    ap.add_argument("--list-tags", action="store_true", help="列出清单中的标签及默认状态")
    a = ap.parse_args()

    lists = a.list or [x for x in os.environ.get("MODEL_LIST", "").split(",") if x]
    if not lists:
        lists = ["nvidia.txt" if os.environ.get("MODE", "ascend") == "nvidia" else "ascend.txt"]

    entries, tags, all_tags = [], set(), set()
    for lp in lists:
        e, d, t = parse_list(lp)
        entries += e; tags |= d; all_tags |= t

    if a.list_tags:
        for t in sorted(all_tags):
            print(f"  {t:12s} {'默认开启' if t in tags else '默认关闭'}")
        return 0

    # 旧环境变量兼容（优先级：清单默认 < 环境变量 < 命令行）
    for env, tag, invert in (("INCLUDE_HERETIC_TE", "heretic", False), ("INCLUDE_REF2VA", "ref2va", False),
                             ("INCLUDE_PRUNED", "pruned", False), ("SKIP_FULL_FL2VA", "full", True),
                             ("NVFP4_TE", "nvfp4", False), ("W6A8", "w6a8", False)):
        v = env_flag(env)
        if v is None:
            continue
        on = (not v) if invert else v
        (tags.add if on else tags.discard)(tag)
        if env == "SKIP_FULL_FL2VA" and v:
            tags.add("pruned")  # 旧行为：跳过完整版时自动加精简版
    mentioned = set()
    for on, v in (a.tag_ops or []):
        ts = split_csv([v]); mentioned |= ts
        (tags.update if on else tags.difference_update)(ts)
    unknown = mentioned - all_tags
    if unknown:
        print(f"[警告] 清单中没有这些标签: {', '.join(sorted(unknown))}", flush=True)

    models_dir = a.models_dir or os.path.join(os.environ.get("COMFY_HOME", "/mnt/workspace/ComfyUI"), "models")
    endpoint = a.endpoint or os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    nconn = a.conn or int(os.environ.get("MAX_CONN", "32"))
    fpar = a.files_parallel or int(os.environ.get("FILES_PARALLEL", "2"))

    jobs, seen = [], set()
    for e in entries:
        if not e.enabled(tags):
            continue
        url, fname = build_url(e.src, endpoint)
        path = local_path(models_dir, e.dest, fname)
        if path in seen:
            continue
        seen.add(path)
        jobs.append((url, path))

    print(f"清单: {', '.join(lists)}  |  标签: {', '.join(sorted(tags)) or '(无)'}")
    print(f"目标: {models_dir}  |  源: {endpoint}  |  {len(jobs)} 个文件")
    if not jobs:
        print("没有要下载的文件。")
        return 0
    if any(is_civitai(u) for u, _ in jobs) and not CIVITAI_TOKEN:
        print(f"[提示] 清单里有 Civitai 文件，需要 API Key：export CIVITAI_TOKEN=xxxx（{CIVITAI_ENDPOINT} 用户设置 → API Keys），否则这些文件会失败", flush=True)

    session = requests.Session()
    HF_HOSTS.update({urlparse(endpoint).netloc, "huggingface.co", "hf-mirror.com"})
    adapter = requests.adapters.HTTPAdapter(pool_connections=fpar * 2, pool_maxsize=nconn * fpar + 8)
    session.mount("https://", adapter); session.mount("http://", adapter)

    # 先列出每个文件的大小、合计和本地已有多少，避免「到底要下多少」心里没数
    def size_of(job):
        try:
            return probe(session, job[0])[1]
        except Exception:
            if is_civitai(job[0]):
                # 没 token 也能从公开 API 拿到大致大小，方便 dry-run
                q = urlparse(job[0]).query
                fid = dict(x.split("=", 1) for x in q.split("&") if "=" in x).get("fileId")
                try:
                    return civitai_file(urlparse(job[0]).path.rstrip("/").rsplit("/", 1)[1], fid)[1]
                except Exception:
                    return None
            return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        sizes = list(ex.map(size_of, jobs))
    grand = have = 0
    for (url, path), sz in zip(jobs, sizes):
        rel = os.path.relpath(path, models_dir)
        done = sz is not None and os.path.exists(path) and os.path.getsize(path) == sz
        state = "已有" if done else ("部分" if os.path.exists(path + ".part") else "")
        print(f"  {gb(sz) if sz else '   ?GB':>9}  {rel}  {state}" + (f"  <-  {url}" if a.dry_run else ""))
        grand += sz or 0
        have += sz if done else 0
    print(f"  合计 {gb(grand)}，本地已完成 {gb(have)}，需下载约 {gb(grand - have)}" + ("（含大小未知的文件）" if None in sizes else ""), flush=True)
    if a.dry_run:
        return 0

    stop = threading.Event()

    def reporter():
        last = 0
        while not stop.wait(30):
            cur = total[0]
            print(f"  --- 速度 {(cur - last)/30/1e6:.1f} MB/s，本次累计 {cur/1e9:.2f} GB", flush=True)
            last = cur

    threading.Thread(target=reporter, daemon=True).start()

    def run(job):
        try:
            return download(session, job[0], job[1], nconn, a.verify)
        except Exception as e:
            print(f"[失败] {os.path.basename(job[1])}: {repr(e)[:120]}", flush=True)
            return False

    with ThreadPoolExecutor(max_workers=max(1, fpar)) as ex:
        results = list(ex.map(run, jobs))
    stop.set()

    failed = [os.path.basename(j[1]) for j, ok in zip(jobs, results) if not ok]
    if failed:
        print(f"\n{len(failed)} 个文件未完成：{', '.join(failed)}。重跑同一命令即可续传。")
        return 1
    print("\n全部模型下载完成。若工作流里选不到新模型，重启 ComfyUI 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

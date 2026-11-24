"""Local GHIL catalogues and image paths."""
import hashlib
import json
import os
import random
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

import folder_paths
from PIL import Image, ImageOps

LIBRARY = Path(folder_paths.models_dir) / "GHIL"
TYPES = {"服装": "costume", "姿势": "pose", "发型": "hair", "人像": "portrait"}
INDEX_FILES = {"costume": "costume-zh.json", "pose": "pose-zh.json", "hair": "hairstyle-zh.json", "portrait": "portrait-zh.json"}
THUMBNAIL_LOCKS = [Lock() for _ in range(16)]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif"}


def library_path(kind, relative):
    if kind not in INDEX_FILES:
        raise ValueError("未知图库类型")
    root = (LIBRARY / kind).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("图像路径超出 GHIL 图库")
    if not path.is_file():
        raise FileNotFoundError(f"文件缺失：{path}")
    return path


def asset(kind, relative):
    if kind not in INDEX_FILES:
        raise ValueError("未知图库类型")
    if relative.startswith(("__custom__/", "__custom_thumbs__/")):
        prefix, relative = relative.split("/", 1)
        root = (LIBRARY / "自定义" / next(label for label, value in TYPES.items() if value == kind)).resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("图像路径超出自定义图库")
        if not path.is_file():
            raise FileNotFoundError(f"文件缺失：{path}")
    else:
        prefix = ""
        path = library_path(kind, relative)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("不支持的图像文件")
    if prefix == "__custom_thumbs__":
        cache = LIBRARY / "自定义" / "thumbs" / next(label for label, value in TYPES.items() if value == kind)
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        thumbnail = cache / (digest + ".webp")
        modified = path.stat().st_mtime_ns
        with THUMBNAIL_LOCKS[int(digest[:2], 16) % len(THUMBNAIL_LOCKS)]:
            if not thumbnail.is_file() or thumbnail.stat().st_mtime_ns != modified:
                cache.mkdir(parents=True, exist_ok=True)
                with Image.open(path) as source:
                    source.draft("RGB", (400, 500))
                    image = ImageOps.exif_transpose(source)
                    image.thumbnail((400, 500))
                    image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                with tempfile.NamedTemporaryFile(dir=cache, suffix=".webp", delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    image.save(temporary_path, "WEBP", quality=90)
                    os.utime(temporary_path, ns=(modified, modified))
                    temporary_path.replace(thumbnail)
                finally:
                    temporary_path.unlink(missing_ok=True)
        return thumbnail
    return path


@lru_cache(maxsize=6)
def read_index(path, modified):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=4096)
def image_size(path, version):
    try:
        with Image.open(path) as source:
            width, height = source.size
            if source.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
            return width, height
    except OSError:
        return 0, 0


def custom_images(directory, root, relative=""):
    with os.scandir(directory) as entries:
        for entry in entries:
            name = f"{relative}/{entry.name}" if relative else entry.name
            if entry.is_dir(follow_symlinks=False):
                if Path(entry.path).resolve().is_relative_to(root):
                    yield from custom_images(entry.path, root, name)
            elif os.path.splitext(entry.name)[1].lower() in IMAGE_SUFFIXES and entry.is_file():
                if not entry.is_symlink() or Path(entry.path).resolve().is_relative_to(root):
                    yield entry, name


def records(kind):
    path = library_path(kind, "data/" + INDEX_FILES[kind])
    rows = [dict(row, prompt=" ".join(row.get("关键词") or [])) for row in read_index(str(path), path.stat().st_mtime_ns)]
    custom = LIBRARY / "自定义" / next(label for label, value in TYPES.items() if value == kind)
    if custom.is_dir():
        custom_root = custom.resolve()
        subcategories = {}
        for category in sorted(custom.iterdir()):
            if category.is_dir() and category.resolve().is_relative_to(custom_root):
                subcategories[category.name] = [child.name for child in sorted(category.iterdir()) if child.is_dir() and child.resolve().is_relative_to(custom_root)]
        images = sorted(custom_images(custom, custom_root), key=lambda item: (
            item[1].split("/", 1)[0].casefold(),
            [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item[0].name.casefold())],
            item[1].casefold(),
        ))
        for entry, relative in images:
            image = Path(entry.path)
            parts = relative.split("/")
            if len(parts) < 2:
                continue
            identity = "__custom__/" + relative
            title, _, prompt = image.stem.partition("-")
            title, prompt = title.strip(), prompt.strip()
            category = parts[0]
            thumbnail = "__custom_thumbs__/" + relative
            stat = entry.stat()
            version = f"{stat.st_mtime_ns}-{stat.st_size}"
            width, height = image_size(str(image), version)
            subcategory = parts[1] if len(parts) > 2 else ""
            row = {"id": identity, "title": title, "prompt": prompt, "custom": True, "subcategory": subcategory, "version": version, "w": width, "h": height}
            if category in subcategories:
                row["subcategories"] = subcategories.pop(category)
            search = f"{title} {prompt} {category} {subcategory}".lower()
            if kind == "costume":
                row.update({"分类": category, "关键词": [prompt] if prompt else [], "英文关键词": "", "检索": search, "原图": identity, "预览图": identity, "缩略图": thumbnail})
            elif kind == "pose":
                row.update({"体系": category, "姿势编号": title, "分类": category, "姿势名称": title, "角度": "正面", "原图": identity, "缩略图": thumbnail, "检索": search})
            else:
                row.update({"section": category, "hair": category, "section_zh": category, "hair_zh": category, "full": identity, "preview": identity, "thumb": thumbnail, "search": search})
            rows.append(row)
    return rows


def image_prompt(image_type, image):
    if image_type not in TYPES:
        return ""
    return next((row["prompt"] for row in records(TYPES[image_type]) if row["id"] == image), "")


def selected_path(image_type, image):
    if image_type == "上传":
        path = Path(folder_paths.get_annotated_filepath(image))
        if not path.is_file():
            raise FileNotFoundError(f"上传图像不存在：{image}")
        return path
    if image_type not in TYPES:
        raise ValueError("类型必须为服装、姿势、发型、人像或上传")
    kind = TYPES[image_type]
    row = next((row for row in records(kind) if row["id"] == image), None)
    if row is None:
        raise ValueError(f"请在{image_type}图库中选择图像：{image}")
    return asset(kind, row["full" if kind in ("hair", "portrait") else "原图"])


def navigate(image_type, image, direction, excluded_categories=(), category=""):
    if image_type not in TYPES:
        raise ValueError("只有服装、姿势、发型、人像支持切换图像")
    rows = records(TYPES[image_type])
    field = "分类" if image_type == "服装" else "体系" if image_type == "姿势" else "hair" if image_type == "发型" else "section"
    if direction == "random" and category:
        rows = [row for row in rows if row.get(field, "") == category] or rows
    if direction == "random" and excluded_categories:
        excluded = {value for value in excluded_categories if isinstance(value, str)}
        rows = [row for row in rows if row.get(field, "") not in excluded]
    if not rows:
        if direction == "random" and image:
            return image
        raise ValueError("当前图库为空")
    if direction == "random":
        choices = [row for row in rows if row["id"] != image]
        return random.choice(choices or rows)["id"]
    if direction not in ("previous", "next"):
        raise ValueError("未知切换方向")
    index = next((i for i, row in enumerate(rows) if row["id"] == image), None)
    if index is None:
        return rows[0]["id"]
    return rows[(index + (1 if direction == "next" else -1)) % len(rows)]["id"]

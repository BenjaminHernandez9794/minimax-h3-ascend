"""Goohai Image Library: an independent, local ComfyUI node."""
import asyncio
import hashlib
import json
import math
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import numpy as np
import torch
from aiohttp import web
from PIL import Image, ImageOps, ImageSequence

import nodes
from comfy_api.latest import IO, ComfyExtension
from server import PromptServer

from .catalog import TYPES, asset, image_prompt, library_path, navigate, records, selected_path

ROOT = Path(__file__).resolve().parent
WEB_DIRECTORY = "./web"
RANDOM_CONFIG = ROOT / "random_categories.json"
RANDOM_CONFIG_LOCK = Lock()
RANDOM_EXCLUDED = {}
FAVORITES_CONFIG = ROOT / "favorites.json"
FAVORITES_LOCK = Lock()


def read_config(path):
    settings = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(settings, dict) or any(
        not isinstance(values, list) or any(not isinstance(value, str) for value in values)
        for values in settings.values()
    ):
        raise ValueError(f"{path.name} 应为按图库类型保存的字符串数组")
    return settings


def write_config(path, settings):
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def favorites_config(kind, add=(), remove=(), rows=None):
    catalog = {row["id"]: row for row in rows} if rows is not None else None
    removed = set(remove)
    with FAVORITES_LOCK:
        settings = read_config(FAVORITES_CONFIG)
        ids = []
        for value in dict.fromkeys([*settings.get(kind, []), *add]):
            if value in removed:
                continue
            if catalog is not None:
                row = catalog.get(value)
                if row is None:
                    continue
                try:
                    asset(kind, row["full" if kind in ("hair", "portrait") else "原图"])
                except (ValueError, FileNotFoundError):
                    continue
            ids.append(value)
        if settings.get(kind, []) != ids:
            settings[kind] = ids
            write_config(FAVORITES_CONFIG, settings)
        return ids


def sync_random_categories(kind, excluded=None, rows=None):
    field = {"costume": "分类", "pose": "体系", "hair": "hair", "portrait": "section"}[kind]
    categories = {row[field] for row in (records(kind) if rows is None else rows) if row.get(field)}
    with RANDOM_CONFIG_LOCK:
        settings = read_config(RANDOM_CONFIG)
        saved = settings.get(kind, [])
        excluded = list(dict.fromkeys(value for value in (saved if excluded is None else excluded) if value in categories))
        if settings.get(kind) != excluded:
            settings[kind] = excluded
            write_config(RANDOM_CONFIG, settings)
        RANDOM_EXCLUDED[kind] = excluded
    return excluded


def get_random_categories(kind):
    if kind not in RANDOM_EXCLUDED:
        return sync_random_categories(kind)
    return RANDOM_EXCLUDED[kind]


def crop_bounds(crop, image_type, image, width, height):
    if not crop:
        return None
    try:
        settings = json.loads(crop)
    except (TypeError, ValueError):
        return None
    if not isinstance(settings, dict) or settings.get("type") != image_type or settings.get("image") != image:
        return None
    rect = settings.get("rect")
    if not isinstance(rect, list) or len(rect) != 4 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in rect):
        return None
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return None
    left = min(width - 1, max(0, math.floor(x * width + .5)))
    top = min(height - 1, max(0, math.floor(y * height + .5)))
    right = min(width, max(left + 1, math.floor((x + w) * width + .5)))
    bottom = min(height, max(top + 1, math.floor((y + h) * height + .5)))
    return left, top, right, bottom


class GoohaiImageLibrary(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="GoohaiImageLibrary",
            display_name="Goohai 加载图库",
            category="Goohai/image",
            inputs=[
                IO.Combo.Input("image_type", display_name="类型", options=["无", "服装", "姿势", "发型", "人像", "上传"], default="服装", socketless=True),
                IO.Boolean.Input("randomize", display_name="随机", default=False, optional=True, socketless=True),
                IO.String.Input("image", display_name="图像", default="AUT-0004", socketless=True, tooltip="选择图库图像，或拖入自己的图像；图库条目保留原始 ID。"),
                IO.String.Input("random_categories", display_name="随机分类设置", default="", optional=True, socketless=True, extra_dict={"hidden": True}),
                IO.String.Input("crop", default="", optional=True, socketless=True, extra_dict={"hidden": True}),
            ],
            outputs=[IO.Image.Output(display_name="image"), IO.String.Output(display_name="prompt")],
        )

    @classmethod
    def validate_inputs(cls, image_type, image, randomize=False, random_categories="", crop=""):
        if image_type == "无":
            return True
        try:
            if randomize and image_type in TYPES:
                if not records(TYPES[image_type]):
                    return "当前图库为空"
            else:
                selected_path(image_type, image)
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        return True

    @classmethod
    def fingerprint_inputs(cls, image_type, image, randomize=False, random_categories="", crop=""):
        if image_type == "无":
            return None
        if randomize and image_type in TYPES:
            return float("nan"), random_categories
        with selected_path(image_type, image).open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest(), image_prompt(image_type, image), crop

    @classmethod
    def execute(cls, image_type, image, randomize=False, random_categories="", crop=""):
        if image_type == "无":
            return IO.NodeOutput(None, "", ui={"ghil_selection": [{"type": "无", "id": ""}]})
        if randomize and image_type in TYPES:
            try:
                settings = json.loads(random_categories or "{}")
            except (TypeError, ValueError):
                settings = {}
            category = settings.get("category", "") if isinstance(settings, dict) else ""
            category = category if isinstance(category, str) else ""
            kind = TYPES[image_type]
            excluded = get_random_categories(kind)
            image = navigate(image_type, image, "random", excluded if not category else [], category)
        try:
            path = selected_path(image_type, image)
        except (ValueError, FileNotFoundError):
            if image_type not in TYPES or not image.startswith("__custom__/"):
                raise
            excluded = sync_random_categories(TYPES[image_type])
            image = navigate(image_type, "", "random" if randomize else "next", excluded)
            path = selected_path(image_type, image)
        ui = {"ghil_selection": [{"type": image_type, "id": image}]}
        if image_type == "上传":
            output, _ = nodes.LoadImage().load_image(image)
            bounds = crop_bounds(crop, image_type, image, output.shape[2], output.shape[1])
            if bounds:
                left, top, right, bottom = bounds
                output = output[:, top:bottom, left:right, :].clone()
            return IO.NodeOutput(output, "", ui=ui)
        frames = []
        with Image.open(path) as source:
            for frame in ImageSequence.Iterator(source):
                frame = ImageOps.exif_transpose(frame).convert("RGBA")
                frame = Image.alpha_composite(Image.new("RGBA", frame.size, "white"), frame).convert("RGB")
                if frames and frame.size != size:
                    continue
                size = frame.size
                bounds = crop_bounds(crop, image_type, image, *size)
                if bounds:
                    frame = frame.crop(bounds)
                frames.append(torch.from_numpy(np.array(frame, dtype=np.float32) / 255.0).unsqueeze(0))
        return IO.NodeOutput(torch.cat(frames, dim=0), image_prompt(image_type, image), ui=ui)


class ImageLibraryExtension(ComfyExtension):
    async def get_node_list(self):
        return [GoohaiImageLibrary]


async def comfy_entrypoint():
    return ImageLibraryExtension()


routes = PromptServer.instance.routes


@routes.get("/ghil/ui/favorites.js")
async def favorites_script_route(request):
    return web.FileResponse(ROOT / "web" / "favorites.js", headers={"Cache-Control": "no-cache"})


@routes.get("/ghil/{kind}/favorites")
@routes.post("/ghil/{kind}/favorites")
async def favorites_route(request):
    kind = request.match_info["kind"]
    if kind not in TYPES.values():
        raise web.HTTPNotFound()
    try:
        add, remove = [], []
        if request.method == "POST":
            data = await request.json()
            if not isinstance(data, dict):
                return web.json_response({"error": "收藏设置必须是对象"}, status=400)
            add, remove = data.get("add", []), data.get("remove", [])
            if any(not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values) for values in (add, remove)):
                return web.json_response({"error": "收藏必须是图像 ID 数组"}, status=400)
        rows = await asyncio.to_thread(records, kind)
        ids = await asyncio.to_thread(favorites_config, kind, add, remove, rows)
        return web.json_response({"ids": ids}, headers={"Cache-Control": "no-store"})
    except (OSError, ValueError) as exc:
        return web.json_response({"error": f"收藏配置读写失败：{exc}"}, status=503)


@routes.get("/ghil/{kind}/random-categories")
@routes.post("/ghil/{kind}/random-categories")
async def random_categories_route(request):
    kind = request.match_info["kind"]
    if kind not in TYPES.values():
        raise web.HTTPNotFound()
    try:
        if request.method == "POST":
            data = await request.json()
            excluded = data.get("excluded") if isinstance(data, dict) else None
            if not isinstance(excluded, list) or any(not isinstance(value, str) for value in excluded):
                return web.json_response({"error": "excluded 必须是分类名称数组"}, status=400)
            excluded = await asyncio.to_thread(sync_random_categories, kind, excluded)
        else:
            excluded = await asyncio.to_thread(get_random_categories, kind)
        return web.json_response({"excluded": excluded}, headers={"Cache-Control": "no-store"})
    except (OSError, ValueError) as exc:
        return web.json_response({"error": f"随机分类配置读写失败：{exc}"}, status=503)


@routes.get("/ghil/{kind}/catalog")
async def catalog_route(request):
    try:
        kind = request.match_info["kind"]
        rows = await asyncio.to_thread(records, kind)
        await asyncio.to_thread(sync_random_categories, kind, rows=rows)
        await asyncio.to_thread(favorites_config, kind, rows=rows)
        return web.json_response(rows, headers={"Cache-Control": "no-cache"})
    except (ValueError, OSError, KeyError) as exc:
        return web.json_response({"error": str(exc)}, status=503)


@routes.get("/ghil/{kind}/assets/{relative:.+}")
async def asset_route(request):
    try:
        path = await asyncio.to_thread(asset, request.match_info["kind"], request.match_info["relative"])
        return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
    except (ValueError, FileNotFoundError):
        raise web.HTTPNotFound()


@routes.get("/ghil/{kind:hair|portrait}/data.js")
async def portrait_data_route(request):
    try:
        kind = request.match_info["kind"]
        rows = [dict(row,
                     full="assets/" + quote(row["full"], safe="/") + ("?v=" + row["version"] if row.get("custom") else ""),
                     thumb="assets/" + quote(row["thumb"], safe="/") + ("?v=" + row["version"] if row.get("custom") else ""),
                     preview="assets/" + quote(row.get("preview", row["thumb"]), safe="/") + ("?v=" + row["version"] if row.get("custom") else "")) for row in records(kind)]
        payload = json.dumps({"records": rows}, ensure_ascii=False)
        return web.Response(text="window.PORTRAIT_DATA = " + payload + ";", content_type="application/javascript", headers={"Cache-Control": "no-cache"})
    except (ValueError, FileNotFoundError) as exc:
        return web.Response(text=str(exc), status=503)


@routes.get("/ghil/selection")
async def selection_route(request):
    try:
        image_type = request.query.get("type", "服装")
        image = request.query.get("image", "")
        if image_type == "无":
            return web.json_response({"name": "", "url": None})
        selected_path(image_type, image)
        if image_type == "上传":
            return web.json_response({"name": image.replace("\\", "/").split("/")[-1]})
        kind = TYPES[image_type]
        row = next(row for row in records(kind) if row["id"] == image)
        relative = row["full" if kind in ("hair", "portrait") else "原图"]
        return web.json_response({"name": row.get("title", row.get("姿势名称", image)), "url": f"/ghil/{kind}/assets/" + quote(relative, safe="/") + ("?v=" + row["version"] if row.get("custom") else "")})
    except (ValueError, FileNotFoundError) as exc:
        return web.json_response({"error": str(exc)}, status=404)


@routes.get("/ghil/navigate")
async def navigate_route(request):
    try:
        image_type = request.query.get("type", "")
        image = navigate(image_type, request.query.get("image", ""), request.query.get("direction", "next"))
        selected_path(image_type, image)
        return web.json_response({"id": image})
    except (ValueError, FileNotFoundError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@routes.get("/ghil/{kind}/gallery")
async def gallery_route(request):
    kind = request.match_info["kind"]
    if kind not in TYPES.values():
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / "web" / "galleries" / ("hair" if kind == "portrait" else kind) / "gallery.html", headers={"Cache-Control": "no-cache"})


@routes.get("/ghil/costume/README.md")
async def costume_readme_route(request):
    try:
        path = library_path("costume", "README.md")
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/plain", charset="utf-8", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except FileNotFoundError:
        raise web.HTTPNotFound()


@routes.get("/ghil/{kind}/ui/{filename}")
async def ui_route(request):
    kind, filename = request.match_info["kind"], request.match_info["filename"]
    assets = {
        "costume": {"gallery.mjs", "style.css", "actions.css", "readme.mjs", "marked.mjs"},
        "pose": {"actions.css"},
        "hair": {"app.mjs"},
        "portrait": {"app.mjs"},
    }
    if kind not in TYPES.values() or filename not in assets.get(kind, set()):
        raise web.HTTPNotFound()
    relative = filename if filename == "actions.css" else f"{'hair' if kind == 'portrait' else kind}/{filename}"
    path = ROOT / "web" / "galleries" / relative
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

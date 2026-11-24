import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { attachCrop, handleCropKey } from "./crop.js";
import { favoriteIds, loadFavorites, setFavorite, receiveFavorites } from "./favorites.js";

const kinds = { "服装": "costume", "姿势": "pose", "发型": "hair", "人像": "portrait" };
const defaults = { "无": "", "服装": "AUT-0004", "姿势": "full_sexy_P031_front", "发型": "h-f71f980dde3", "人像": "f71f980dde3", "上传": "" };
const controllers = new WeakMap();
const widgetNodes = new WeakMap();
const catalogs = new Map();
const randomSettings = new Map();
let hoveredNode = null, activeNode = null;
const categoryField = kind => kind === "costume" ? "分类" : kind === "pose" ? "体系" : "section";
const randomCategoryField = kind => kind === "costume" ? "分类" : kind === "pose" ? "体系" : kind === "hair" ? "hair" : "section";
const hairCategories = [["", "全部"], ["ショート", "短发"], ["ミディアム", "中发"], ["セミロング", "中长发"], ["ロング", "长发"]];
const portraitCategories = [["", "全部人像"], ["face", "正脸参考"], ["styling", "造型参考"]];
const categoryLabel = (kind, category) => category === "__favorites__" ? "收藏" : kind === "portrait" ? (portraitCategories.find(([value]) => value === category)?.[1] || category) : kind === "hair" ? (hairCategories.find(([value]) => value === category)?.[1] || category) : category || "全部";
async function randomExcluded(kind) {
  if (!randomSettings.has(kind)) {
    randomSettings.set(kind, (async () => {
      const response = await api.fetchApi(`/ghil/${kind}/random-categories`);
      const settings = await response.json();
      if (!response.ok) throw new Error(settings.error);
      return new Set(settings.excluded);
    })());
  }
  try { return await randomSettings.get(kind); }
  catch (error) { randomSettings.delete(kind); throw error; }
}
async function getCatalog(kind) {
  if (!catalogs.has(kind)) {
    randomSettings.delete(kind);
    catalogs.set(kind, (async () => {
      const response = await api.fetchApi(`/ghil/${kind}/catalog`);
      const rows = await response.json();
      if (!response.ok) throw new Error(rows.error);
      await loadFavorites(kind, rows);
      return rows;
    })());
  }
  try { return await catalogs.get(kind); }
  catch (error) { catalogs.delete(kind); throw error; }
}
const imageFile = file => file && (file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp|tiff?|avif)$/i.test(file.name));
const style = document.createElement("style");
style.textContent = `
/* Extend only the noninteractive footer into the native resize margin. */
.ghil-preview{width:calc(100% + 30px);height:calc(100% + 12px);margin:0 -15px 0;display:flex;flex-direction:column;align-items:stretch;justify-content:flex-start;box-sizing:border-box;padding:0 0 1px;color:#ccc;font:12px sans-serif;user-select:none;pointer-events:none}
.lg-node .ghil-preview{width:calc(100% + 26px);height:calc(100% + 12px);margin:0 -13px 0}
.ghil-action-row{display:flex;gap:4px;width:100%;height:30px;min-height:30px;margin:0 0 4px;pointer-events:auto}
.ghil-action-row button{flex:1;height:30px;min-width:0;padding:0 8px;border:1px solid #6e7581;border-radius:8px 8px 0 0;background:#242833;color:#ddd;font:13px/28px "Microsoft YaHei",sans-serif;cursor:pointer}
.ghil-action-row button:hover{background:#313745;border-color:#9aa3b5}
.ghil-manual-random{position:absolute;right:0;width:28px;height:60px;display:grid;place-items:center;box-sizing:border-box;padding:8px 0;border:1px solid rgba(235,247,239,.3);border-radius:8px 0 0 8px;background:rgba(100,124,108,.3);color:#566c5d;font:12px "Microsoft YaHei",sans-serif;writing-mode:vertical-rl;text-orientation:upright;letter-spacing:2px;cursor:pointer;visibility:hidden;pointer-events:none;z-index:1}
.ghil-preview.ghil-node-hover .ghil-manual-random{visibility:visible;pointer-events:auto}
.ghil-manual-random:hover{color:#caffdc}
.ghil-manual-random:disabled{display:none}
.dom-widget:has(.ghil-preview),.lg-node div:has(>.ghil-preview){pointer-events:none!important;overflow:visible}
.ghil-preview-stage{position:relative;width:100%;height:auto;flex:1 1 0;min-width:0;min-height:0;background:transparent;border-radius:0;pointer-events:none}
.ghil-preview-stage>img{position:absolute;display:block;object-fit:contain;object-position:center}
.ghil-favorite-notice{position:absolute;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:8px;background:rgba(46,70,54,.3);color:#9bd2aa;font:13px/20px "Microsoft YaHei",sans-serif;white-space:nowrap;opacity:0;pointer-events:none;z-index:2}
.ghil-favorite-notice svg{width:16px;height:16px;fill:currentColor}
.ghil-preview-size{position:absolute;top:100%;left:0;width:100%;margin-top:2px;height:14px;line-height:14px;font-size:11px;color:#999;text-align:center;pointer-events:none}
.ghil-preview-controls{position:absolute;inset:0;opacity:0;pointer-events:none;transition:opacity .12s}
.ghil-preview.ghil-hover .ghil-preview-controls{opacity:1}
.ghil-preview-controls button{position:absolute;pointer-events:none;border:0;cursor:pointer;background:#20252b99;color:#fff;padding:4px 9px;font:26px/1 sans-serif}
.ghil-preview.ghil-hover .ghil-preview-controls button{pointer-events:auto}
.ghil-preview-controls .ghil-previous{left:4px;top:50%;transform:translateY(-50%)}
.ghil-preview-controls .ghil-next{right:4px;top:50%;transform:translateY(-50%)}
.ghil-preview-controls .ghil-previous,.ghil-preview-controls .ghil-next{display:grid;place-items:center;width:24px;height:32px;padding:0;background:#20252b4d}
.ghil-preview-controls svg{display:block;width:14px;height:18px}
.ghil-preview-controls[hidden]{display:none}
.ghil-crop-ratios,.ghil-crop-overlay,.ghil-crop-clear{display:none}
.ghil-cropping .ghil-crop-clear{display:block;color:#f16b6b;margin-top:-3px;margin-bottom:3px;padding-bottom:5px;border-bottom:1px solid #ffffff18}
.ghil-cropping .ghil-manual-random,.ghil-cropping .ghil-preview-controls{display:none!important}
.ghil-cropping .ghil-crop-ratios{position:absolute;left:5px;display:flex;flex-direction:column;gap:2px;width:36px;z-index:5;pointer-events:none}
.ghil-crop-ratios button{padding:2px 0;border:0;background:transparent;color:#ccc;font:11px/16px sans-serif;cursor:pointer;text-align:center}
.ghil-crop-ratios button[data-ratio]{color:#B2B7BD}
.ghil-crop-ratios button[data-ratio].ghil-ratio-hover{color:#eef1f4}
.ghil-crop-ratios button[data-ratio][aria-pressed=true]{color:#8de8b5}
.ghil-cropping .ghil-crop-overlay{position:absolute;display:block;overflow:visible;z-index:4;pointer-events:none;cursor:crosshair}
.ghil-crop-cursor,.ghil-crop-cursor *{cursor:var(--ghil-crop-cursor)!important}
.ghil-crop-selection{position:absolute;container-type:size;box-sizing:border-box;border:1px solid #ddd;outline:1px solid #2228;cursor:move}
.ghil-crop-selection[hidden]{display:none}
.ghil-crop-mask{position:absolute;inset:0;background:#0009;pointer-events:none}
.ghil-crop-mask[hidden]{display:none}
.ghil-crop-thirds{position:absolute;inset:0;background:linear-gradient(to right,transparent 33.2%,#fff7 33.2%,#fff7 calc(33.2% + .3cqh),transparent calc(33.2% + .3cqh),transparent 66.5%,#fff7 66.5%,#fff7 calc(66.5% + .3cqh),transparent calc(66.5% + .3cqh)),linear-gradient(to bottom,transparent 33.2%,#fff7 33.2%,#fff7 33.5%,transparent 33.5%,transparent 66.5%,#fff7 66.5%,#fff7 66.8%,transparent 66.8%);pointer-events:none}
.ghil-crop-center{position:absolute;left:50%;top:50%;width:20px;height:20px;transform:translate(-50%,-50%);fill:none;stroke:var(--ghil-crop-center-color,#000);stroke-width:1.7;pointer-events:none}
.ghil-crop-center-dot{fill:var(--ghil-crop-center-color,#000);stroke:none}
.ghil-crop-handle{position:absolute;width:14px;height:14px;border:3px solid #eee;border-radius:2px;box-sizing:border-box;background:transparent;z-index:1}
.ghil-crop-n,.ghil-crop-s{left:50%;width:24px;height:3px;border:0;background:#eee;transform:translateX(-50%);cursor:ns-resize}
.ghil-crop-n{top:-2px}.ghil-crop-s{bottom:-2px}
.ghil-crop-e,.ghil-crop-w{top:50%;height:24px;width:3px;border:0;background:#eee;transform:translateY(-50%);cursor:ew-resize}
.ghil-crop-e{right:-2px}.ghil-crop-w{left:-2px}
.ghil-crop-nw{left:-3px;top:-3px;border-right:0;border-bottom:0;cursor:nwse-resize}
.ghil-crop-ne{right:-3px;top:-3px;border-left:0;border-bottom:0;cursor:nesw-resize}
.ghil-crop-sw{left:-3px;bottom:-3px;border-right:0;border-top:0;cursor:nesw-resize}
.ghil-crop-se{right:-3px;bottom:-3px;border-left:0;border-top:0;cursor:nwse-resize}
.ghil-crop-drawing .ghil-crop-selection{border:0;outline:0}
.ghil-crop-drawing .ghil-crop-selection::after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(135deg,#fff 0 3px,#111 3px 6px) top/100% 1px no-repeat,repeating-linear-gradient(135deg,#fff 0 3px,#111 3px 6px) bottom/100% 1px no-repeat,repeating-linear-gradient(135deg,#fff 0 3px,#111 3px 6px) left/1px 100% no-repeat,repeating-linear-gradient(135deg,#fff 0 3px,#111 3px 6px) right/1px 100% no-repeat}
.ghil-crop-drawing .ghil-crop-handle,.ghil-crop-drawing .ghil-crop-thirds,.ghil-crop-drawing .ghil-crop-center{display:none}
@media(hover:none){.ghil-preview-controls{opacity:1}.ghil-preview-controls button{pointer-events:auto}}
`;
document.head.append(style);

// Capture drops before the frontend interprets embedded PNG workflow metadata.
function nodeAtEvent(event) {
  const widget = event.target.closest?.("[data-ghil-node-id]");
  if (widget) return widgetNodes.get(widget);
  const host = event.target.closest?.("[data-node-id]");
  if (host) return app.graph?.getNodeById(host.dataset.nodeId);
  if (event.target !== app.canvas?.canvas) return null;
  const point = app.canvas.convertEventToCanvasOffset(event);
  return app.graph?.getNodeOnPos(point[0], point[1]);
}
window.addEventListener("pointermove", event => {
  const node = nodeAtEvent(event);
  if (node !== hoveredNode) controllers.get(hoveredNode)?.hover(null);
  hoveredNode = node;
  controllers.get(node)?.hover(event);
}, true);
window.addEventListener("blur", () => {
  controllers.get(hoveredNode)?.hover(null);
  hoveredNode = null;
});
window.addEventListener("pointerdown", event => {
  const node = nodeAtEvent(event);
  if (node || event.target === app.canvas?.canvas) activeNode = node;
}, true);
function clearCropShortcut(event) {
  if (event.altKey || event.ctrlKey || event.metaKey || !(event.code === "KeyX" || ["x", "X", "ｘ", "Ｘ"].includes(event.key))) return;
  const selected = Object.values(app.canvas?.selected_nodes || {});
  const node = selected.includes(activeNode) ? activeNode : selected.length === 1 ? selected[0] : null;
  const controller = controllers.get(node);
  if (!controller) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (!event.repeat) controller.clearCrop();
}
window.addEventListener("keydown", clearCropShortcut, true);
window.addEventListener("keydown", event => {
  if (handleCropKey(event)) return;
  const saveFavorite = event.code === "KeyS" || ["s", "S", "ｓ", "Ｓ"].includes(event.key);
  if (!saveFavorite && !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  if (event.altKey || event.ctrlKey || event.metaKey || !saveFavorite && event.shiftKey) return;
  if (event.target.closest?.("input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=textbox]") || document.querySelector("dialog[open]")) return;
  const selected = Object.values(app.canvas?.selected_nodes || {});
  if (saveFavorite) {
    const node = selected.includes(activeNode) ? activeNode
      : selected.includes(hoveredNode) ? hoveredNode : selected.length === 1 ? selected[0] : null;
    const controller = controllers.get(node);
    if (!controller?.canFavorite()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!event.repeat) void controller.favorite();
    return;
  }
  const node = controllers.has(hoveredNode) ? hoveredNode
    : selected.includes(activeNode) ? activeNode : selected.length === 1 ? selected[0] : null;
  const controller = controllers.get(node);
  if (!controller?.canNavigate()) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  controller.key(event.key);
}, true);
window.addEventListener("paste", event => {
  if (event.defaultPrevented || event.target.closest?.("input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=textbox]") || document.querySelector("dialog[open]")) return;
  const selected = Object.values(app.canvas?.selected_nodes || {});
  const node = selected.includes(activeNode) ? activeNode : selected.length === 1 ? selected[0] : null;
  const controller = controllers.get(node);
  if (!controller) return;
  const clipboard = event.clipboardData;
  const file = [...(clipboard?.files || [])].find(imageFile)
    || [...(clipboard?.items || [])].filter(item => item.kind === "file").map(item => item.getAsFile()).find(imageFile);
  if (!file) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  void controller.upload(file);
}, true);
for (const eventName of ["dragover", "drop"]) {
  window.addEventListener(eventName, event => {
    const node = nodeAtEvent(event);
    const controller = controllers.get(node);
    if (!controller) return;
    const file = [...(event.dataTransfer?.files || [])].find(imageFile);
    if (eventName === "drop" && !file) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (eventName === "drop") void controller.upload(file);
  }, true);
}

app.registerExtension({
  name: "Goohai.ImageLibrary",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "GoohaiImageLibrary") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const node = this;
      node.color ??= "#647c6c";
      const type = node.widgets.find(widget => widget.name === "image_type");
      const image = node.widgets.find(widget => widget.name === "image");
      const randomCategories = node.widgets.find(widget => widget.name === "random_categories");
      const cropWidget = node.widgets.find(widget => widget.name === "crop");
      let imageId = image.value;
      let imageLabel = image.value;
      const updateImageLabel = () => {
        if (kinds[type.value] && String(imageId).startsWith("__custom__/")) {
          const path = imageId.slice("__custom__/".length);
          const slash = path.lastIndexOf("/");
          const title = path.slice(slash + 1).replace(/\.[^.]+$/, "").split("-", 1)[0].trim();
          image.value = `自定义/${path.split("/")[0]}/${title}`;
        } else image.value = imageId;
        imageLabel = image.value;
      };
      const syncRandomCategories = () => {
        const kind = kinds[type.value];
        if (!randomCategories || !kind) return;
        const category = node.properties.ghilCategories?.[type.value] || "";
        randomCategories.value = JSON.stringify({ category: category === "__favorites__" ? "" : category });
      };
      image.serializeValue = () => imageId;
      const serialized = node.onSerialize;
      node.onSerialize = function (data) {
        serialized?.apply(this, arguments);
        if (data.widgets_values) data.widgets_values[node.widgets.indexOf(image)] = imageId;
        if (data.widgets_values_named) data.widgets_values_named.image = imageId;
      };
      const randomize = node.widgets.find(widget => widget.name === "randomize");
      node.widgets.splice(node.widgets.indexOf(randomize), 1);
      node.widgets.splice(node.widgets.indexOf(type) + 1, 0, randomize);
      type.label = "类型";
      image.label = "图像";
      randomize.label = "随机";
      let dialog = null, frame = null, previewRequest = 0, uploadRequest = 0;
      let galleryObserver = null;
      let selectionRequest = 0;
      let previousType = type.value;
      let manualRandomPending = false;
      let randomHistory = [];
      let randomHistoryIndex = -1;
      let randomHistoryKey = "";
      node.properties.ghilSelections ??= {};
      node.properties.ghilCategories ??= {};
      node.properties.ghilSections ??= {};
      if (kinds[type.value] && imageId === defaults["发型"] && type.value !== "发型") {
        imageId = defaults[type.value];
      }
      if (type.value === "发型" && ["face", "styling"].includes(node.properties.ghilCategories[type.value])) {
        node.properties.ghilSections[type.value] = node.properties.ghilCategories[type.value];
        node.properties.ghilCategories[type.value] = "";
      }
      const root = document.createElement("div");
      root.className = "ghil-preview";
      root.dataset.ghilNodeId = node.id;
      widgetNodes.set(root, node);
      const box = document.createElement("div");
      box.className = "ghil-preview-stage";
      let preview = document.createElement("img");
      preview.draggable = false;
      const favoriteNotice = document.createElement("div");
      favoriteNotice.className = "ghil-favorite-notice";
      favoriteNotice.setAttribute("role", "status");
      favoriteNotice.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4 4.55 12.9a5.22 5.22 0 0 1 7.45-7.32 5.22 5.22 0 0 1 7.45 7.32L12 20.4Z"/></svg><span>已收藏</span>';
      let favoriteAnimation = null;
      const dimensions = document.createElement("div");
      dimensions.className = "ghil-preview-size";
      const controls = document.createElement("div");
      controls.className = "ghil-preview-controls";
      controls.hidden = true;
      for (const [direction, label, title] of [["previous", "‹", "上一张"], ["next", "›", "下一张"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `ghil-${direction}`;
        button.textContent = label;
        if (direction !== "random") {
          const points = direction === "previous" ? "11,4 5,10 11,16" : "5,4 11,10 5,16";
          button.innerHTML = `<svg viewBox="0 0 16 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="${points}"/></svg>`;
        }
        button.setAttribute("aria-label", title);
        button.addEventListener("pointerdown", event => { if (event.button === 0) event.stopPropagation(); });
        button.addEventListener("click", event => {
          event.stopPropagation();
          void navigate(direction);
        });
        controls.append(button);
      }
      const status = document.createElement("div");
      status.setAttribute("role", "status");
      status.style.cssText = "position:absolute;inset:0;display:grid;place-items:center;padding:16px;text-align:center;overflow-wrap:anywhere;pointer-events:none;";
      const actionRow = document.createElement("div");
      actionRow.className = "ghil-action-row";
      box.append(actionRow, preview, status, controls, dimensions, favoriteNotice);
      root.append(box);
      let cropEditor = null;
      const layoutPreview = () => {
        dimensions.textContent = preview.naturalWidth ? `${preview.naturalWidth} × ${preview.naturalHeight}` : "";
        const width = box.clientWidth;
        const actionHeight = actionRow.offsetHeight + 4;
        const height = Math.max(0, box.clientHeight - actionHeight - 16);
        const inset = cropEditor?.editing ? 46 : 0;
        const availableWidth = Math.max(1, width - inset - (inset ? 12 : 0));
        const availableHeight = Math.max(1, height - (inset ? 32 : 0));
        const scale = preview.naturalWidth && preview.naturalHeight
          ? Math.min(availableWidth / preview.naturalWidth, availableHeight / preview.naturalHeight) : 0;
        const imageWidth = scale ? preview.naturalWidth * scale : width;
        const imageHeight = scale ? preview.naturalHeight * scale : height;
        preview.style.width = `${imageWidth}px`;
        preview.style.height = `${imageHeight}px`;
        preview.style.left = `${inset + (availableWidth - imageWidth) / 2}px`;
        preview.style.top = `${actionHeight + (height - imageHeight) / 2}px`;
        dimensions.style.top = `${actionHeight + (height + imageHeight) / 2}px`;
        controls.style.top = `${actionHeight}px`;
        controls.style.bottom = "auto";
        controls.style.height = `${height}px`;
        status.style.top = `${actionHeight}px`;
        status.style.bottom = "auto";
        status.style.height = `${height}px`;
        randomButton.style.top = `${actionHeight + 5}px`;
        favoriteNotice.style.top = `${actionHeight + 8}px`;
        cropEditor?.position();
      };
      const previewObserver = new ResizeObserver(layoutPreview);
      previewObserver.observe(root);
      const picker = document.createElement("input");
      picker.type = "file";
      picker.accept = "image/*";

      const changed = () => { updateImageLabel(); node.setDirtyCanvas(true, true); node.graph?.change(); };
      const suspendRandomForManualSelection = () => {
        if (!randomize.value) return;
        manualRandomPending = true;
      };
      const resetCropForSelection = () => {
        if (cropWidget) cropWidget.value = "";
        void cropEditor.setSource(null);
      };
      const select = (id, manual = false) => {
        if (manual || id !== imageId) resetCropForSelection();
        if (manual) suspendRandomForManualSelection();
        imageId = id;
        node.properties.ghilSelections[type.value] = id;
        changed(); void update();
      };
      const resetRandomHistory = id => {
        randomHistory = id ? [id] : [];
        randomHistoryIndex = id ? 0 : -1;
      };
      const navigate = async direction => {
        if (!kinds[type.value]) return;
        void cropEditor.setSource(null);
        layoutPreview();
        const current = ++selectionRequest, selectedType = type.value;
        const selectedImage = imageId;
        try {
          const kind = kinds[selectedType], field = categoryField(kind);
          let all = await getCatalog(kind);
          if (current !== selectionRequest || selectedType !== type.value || selectedImage !== imageId) return;
          let category = node.properties.ghilCategories[selectedType] || "";
          const section = kind === "hair" ? (node.properties.ghilSections[selectedType] || "all") : "all";
          const favorites = favoriteIds(kind);
          const excluded = !category && (direction === "random" || randomize.value && ["previous", "next"].includes(direction)) ? await randomExcluded(kind) : new Set();
          if (current !== selectionRequest || selectedType !== type.value || selectedImage !== imageId) return;
          const hasFavorites = all.some(row => favorites.has(row.id) && (kind !== "hair" || section === "all" || row.section === section));
          const categories = kind === "portrait" ? [...new Set([...portraitCategories.map(([value]) => value), ...all.map(row => row.section).filter(Boolean)]), "__favorites__"] : kind === "hair"
            ? [...new Set([...hairCategories.map(([value]) => value), ...all.map(row => row.hair).filter(Boolean)]), ...(hasFavorites ? ["__favorites__"] : [])]
            : ["", ...new Set(all.map(row => row[field]).filter(Boolean)), ...(hasFavorites ? ["__favorites__"] : [])];
          if (direction === "up" || direction === "down") {
            const index = Math.max(0, categories.indexOf(category));
            category = categories[(index + (direction === "down" ? 1 : categories.length - 1)) % categories.length];
          }
          let rows = all.filter(row => kind === "hair"
            ? (section === "all" || row.section === section) && (category === "__favorites__" ? favorites.has(row.id) : !category || row.hair === category)
            : (category === "__favorites__" ? favorites.has(row.id) : !category || row[field] === category));
          if (!rows.length) {
            if (kind === "portrait" && (direction === "up" || direction === "down")) {
              node.properties.ghilCategories[selectedType] = category;
              changed(); void update();
              return;
            }
            if (category && category !== "__favorites__") {
              catalogs.delete(kind);
              all = await getCatalog(kind);
              if (current !== selectionRequest || selectedType !== type.value || selectedImage !== imageId) return;
              if (!all.some(row => row[randomCategoryField(kind)] === category)) {
                node.properties.ghilCategories[selectedType] = "";
                await update();
                return;
              }
            }
            throw new Error("当前分类为空");
          }
          if (!category && (direction === "random" || randomize.value && ["previous", "next"].includes(direction))) {
            rows = rows.filter(row => !excluded.has(row[randomCategoryField(kind)]));
            if (!rows.length) return;
          }
          const historyKey = `${selectedType}|${section}|${category}|${JSON.stringify([...excluded])}`;
          if (historyKey !== randomHistoryKey || (randomHistoryIndex >= 0 && randomHistory[randomHistoryIndex] !== selectedImage)) {
            randomHistoryKey = historyKey;
            resetRandomHistory(selectedImage);
          }
          if (!category && randomize.value && ["previous", "next"].includes(direction)) {
            const validIds = new Set(rows.map(row => row.id));
            randomHistory = randomHistory.filter(id => validIds.has(id));
            randomHistoryIndex = randomHistory.indexOf(selectedImage);
          }
          let id;
          if (direction === "up" || direction === "down") id = rows[0].id;
          else if (randomize.value && direction === "previous" && randomHistoryIndex > 0) {
            id = randomHistory[--randomHistoryIndex];
          } else if (randomize.value && direction === "previous") {
            id = rows.some(row => row.id === selectedImage) ? selectedImage : rows[0].id;
          } else if (direction === "random" || randomize.value && direction === "next") {
            const choices = rows.filter(row => row.id !== selectedImage);
            const pool = choices.length ? choices : rows;
            id = pool[Math.floor(Math.random() * pool.length)].id;
            randomHistory.splice(randomHistoryIndex + 1);
            randomHistory.push(id);
            randomHistoryIndex++;
          } else {
            const index = rows.findIndex(row => row.id === selectedImage);
            id = rows[index < 0 ? 0 : (index + (direction === "next" ? 1 : rows.length - 1)) % rows.length].id;
          }
          node.properties.ghilCategories[selectedType] = category;
          if (direction === "up" || direction === "down") {
            randomHistoryKey = historyKey;
            resetRandomHistory(id);
          }
          uploadRequest++;
          select(id, true);
        } catch (error) { if (current === selectionRequest) showError(error); }
      };
      const showError = error => { status.textContent = error.message || String(error); status.style.display = "grid"; };
      const close = () => {
        galleryObserver?.disconnect(); galleryObserver = null;
        window.removeEventListener("message", receive);
        dialog?.remove(); dialog = null; frame = null;
      };
      const updateBrowseLabel = rows => {
        const kind = kinds[type.value];
        if (!kind) {
          browse.name = type.value === "无" ? "选择类型后浏览图库" : "选择上传图像";
          browseButton.textContent = browse.name;
          return;
        }
        const category = node.properties.ghilCategories[type.value] || "";
        const section = node.properties.ghilSections[type.value] || "all";
        const favorites = category === "__favorites__" ? favoriteIds(kind) : null;
        const count = rows?.filter(row => (kind !== "hair" || section === "all" || row.section === section)
          && (favorites ? favorites.has(row.id) : !category || row[kind === "hair" ? "hair" : categoryField(kind)] === category)).length;
        const prefix = `去${type.value}图库选择 · `;
        const label = document.createElement("span");
        label.textContent = categoryLabel(kind, category);
        label.style.color = "#91b69d";
        const suffix = document.createElement("span");
        suffix.textContent = count === undefined ? "" : ` · ${count}张`;
        suffix.style.fontSize = "11px";
        browse.name = prefix + label.textContent + suffix.textContent;
        browseButton.replaceChildren(prefix, label, suffix);
      };
      const update = async () => {
        void cropEditor.setSource(null);
        layoutPreview();
        updateImageLabel();
        const current = ++previewRequest;
        favoriteAnimation?.cancel();
        updateBrowseLabel();
        randomButton.disabled = type.value === "无" || type.value === "上传";
        controls.hidden = !kinds[type.value] || !preview.hasAttribute("src");
        if (type.value === "无" || !imageId) {
          controls.hidden = true;
          dimensions.textContent = "";
          preview.removeAttribute("src");
          preview.style.visibility = "hidden";
          layoutPreview();
          status.style.display = type.value === "无" ? "none" : "grid";
          status.textContent = "拖入图像，或点击上方按钮选择";
          return;
        }
        status.style.display = preview.hasAttribute("src") ? "none" : "grid";
        status.textContent = "正在加载图像…";
        try {
          let info;
          if (kinds[type.value] && !node.properties.ghilSelections[type.value] && imageId !== defaults[type.value]) {
            imageId = defaults[type.value];
          }
          if (kinds[type.value]) {
            const rows = await getCatalog(kinds[type.value]);
            if (current !== previewRequest) return;
            if (!rows.some(row => row.id === imageId)) {
              const category = node.properties.ghilCategories[type.value];
              if (category && category !== "__favorites__" && !rows.some(row => row[randomCategoryField(kinds[type.value])] === category)) node.properties.ghilCategories[type.value] = "";
              const saved = node.properties.ghilSelections[type.value];
              imageId = rows.some(row => row.id === saved) ? saved : rows.find(row => row.id === defaults[type.value])?.id || rows[0]?.id || "";
              node.properties.ghilSelections[type.value] = imageId;
            }
            updateBrowseLabel(rows);
            const kind = kinds[type.value];
            const row = rows.find(row => row.id === imageId);
            if (!row) throw new Error(`请在${type.value}图库中选择图像：${imageId}`);
            const relative = row[kind === "hair" || kind === "portrait" ? "full" : "原图"];
            info = {
              name: row.title || row.姿势名称 || imageId,
              url: `/ghil/${kind}/assets/` + relative.split("/").map(encodeURIComponent).join("/") + (row.custom ? "?v=" + row.version : "")
            };
          }
          updateImageLabel();
          if (!info) {
            const query = new URLSearchParams({ type: type.value, image: imageId });
            const response = await api.fetchApi(`/ghil/selection?${query}`);
            info = await response.json();
            if (current !== previewRequest) return;
            if (!response.ok) throw new Error(info.error);
          }
          let url = info.url;
          if (type.value === "上传") {
            const match = String(imageId).match(/ \[(input|output|temp)\]$/);
            const path = match ? imageId.slice(0, match.index) : imageId;
            const normalized = path.replaceAll("\\", "/");
            const slash = normalized.lastIndexOf("/");
            url = `/view?${new URLSearchParams({ filename: normalized.slice(slash + 1), subfolder: normalized.slice(0, Math.max(0, slash)), type: match?.[1] || "input" })}`;
          }
          const next = new Image();
          next.draggable = false;
          next.alt = info.name;
          next.src = api.apiURL(url);
          try { await next.decode(); }
          catch (error) {
            if (current !== previewRequest) return;
            const kind = kinds[type.value];
            if (!kind || !imageId.startsWith("__custom__/")) throw error;
            catalogs.delete(kind);
            const rows = await getCatalog(kind);
            if (current !== previewRequest) return;
            if (rows.some(row => row.id === imageId)) throw error;
            await update();
            return;
          }
          if (current !== previewRequest) return;
          next.style.cssText = preview.style.cssText;
          next.style.visibility = "visible";
          next.dataset.kind = kinds[type.value] || "";
          next.dataset.imageId = imageId;
          preview.replaceWith(next);
          preview = next;
          await cropEditor.setSource(next);
          if (current !== previewRequest) return;
          status.style.display = "none";
          dimensions.textContent = `${preview.naturalWidth} × ${preview.naturalHeight}`;
          layoutPreview();
          controls.hidden = !kinds[type.value];
        } catch (error) { if (current === previewRequest) showError(error); }
      };
      const favorite = async () => {
        const kind = preview.dataset.kind, id = preview.dataset.imageId;
        try {
          await setFavorite(kind, id, true);
          if (!controllers.has(node) || preview.dataset.kind !== kind || preview.dataset.imageId !== id) return;
          favoriteAnimation?.cancel();
          favoriteAnimation = favoriteNotice.animate([{ opacity: 1 }, { opacity: 0 }], { delay: 2000, duration: 350, fill: "backwards", easing: "ease-out" });
          const rows = await getCatalog(kind);
          if (kind === kinds[type.value]) updateBrowseLabel(rows);
        } catch (error) { showError(error); }
      };
      const upload = async file => {
        if (!imageFile(file)) return;
        void cropEditor.setSource(null);
        layoutPreview();
        const current = ++uploadRequest;
        selectionRequest++;
        ++previewRequest;
        status.style.display = "grid"; status.textContent = "正在上传图像…";
        try {
          const body = new FormData();
          body.append("image", file);
          body.append("type", "input");
          body.append("subfolder", "GHIL");
          const response = await api.fetchApi("/upload/image", { method: "POST", body });
          if (!response.ok) throw new Error(`上传失败：HTTP ${response.status}`);
          const result = await response.json();
          if (current !== uploadRequest) return;
          resetCropForSelection();
          node.properties.ghilSelections[type.value] = imageId;
          type.value = "上传"; previousType = "上传";
          imageId = (result.subfolder ? result.subfolder + "/" : "") + result.name;
          node.properties.ghilSelections["上传"] = imageId;
          randomHistoryKey = "";
          resetRandomHistory(imageId);
          suspendRandomForManualSelection();
          close(); changed(); void update();
        } catch (error) { if (current === uploadRequest) showError(error); }
      };
      const previewName = () => {
        const value = String(imageId || "图像").replaceAll("\\", "/").split("/").pop();
        const name = value.replace(/ \[(input|output|temp)\]$/, "") || "图像";
        return /\.[a-z0-9]{1,5}$/i.test(name) ? name : `${name}.png`;
      };
      const copyPreview = async () => {
        try {
          if (!window.ClipboardItem || !navigator.clipboard?.write) throw new Error("当前浏览器不支持复制图像");
          const canvas = document.createElement("canvas");
          canvas.width = preview.naturalWidth;
          canvas.height = preview.naturalHeight;
          canvas.getContext("2d").drawImage(preview, 0, 0);
          const png = new Promise((resolve, reject) => {
            canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("图像转换失败，请重试")), "image/png");
          });
          await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
        } catch (error) { showError(error); }
      };
      const savePreview = () => {
        try {
          const link = document.createElement("a");
          link.href = preview.currentSrc || preview.src;
          link.download = preview.src.startsWith("data:image/png") ? previewName().replace(/\.[^.]+$/, ".png") : previewName();
          link.click();
        } catch (error) { showError(error); }
      };
      cropEditor = attachCrop({
        root, box, widget: cropWidget,
        ownsEvent: event => nodeAtEvent(event) === node,
        zoomCanvas: event => app.canvas.processMouseWheel(event),
        getIdentity: () => ({ type: type.value, image: imageId }),
        getPreview: () => preview,
        setDimensions: (width, height) => { dimensions.textContent = `${width} × ${height}`; },
        replacePreview: next => {
          if (next === preview) return;
          next.style.cssText = preview.style.cssText;
          preview.replaceWith(next); preview = next;
          dimensions.textContent = `${preview.naturalWidth} × ${preview.naturalHeight}`;
        },
        layout: layoutPreview, changed, manualSelection: suspendRandomForManualSelection, showError
      });
      const prepareCrop = () => cropEditor.confirmForQueue();
      api.addEventListener("promptQueueing", prepareCrop);
      let keyQueue = Promise.resolve();
      controllers.set(node, {
        upload,
        clearCrop: () => cropEditor.clear(),
        hover: event => {
          root.classList.toggle("ghil-node-hover", Boolean(event));
          const bounds = box.getBoundingClientRect();
          root.classList.toggle("ghil-hover", Boolean(event && event.clientX >= bounds.left && event.clientX < bounds.right && event.clientY >= bounds.top && event.clientY < bounds.bottom));
        },
        canFavorite: () => Boolean(kinds[type.value]) && !dialog && !cropEditor.editing && preview.hasAttribute("src") && preview.dataset.kind === kinds[type.value] && preview.dataset.imageId === imageId,
        favorite,
        canNavigate: () => Boolean(kinds[type.value]) && !dialog,
        key: key => {
          const keyType = type.value;
          keyQueue = keyQueue.then(() => {
            if (!controllers.has(node) || dialog || type.value !== keyType) return;
            const direction = { ArrowLeft: "previous", ArrowRight: "next", ArrowUp: "up", ArrowDown: "down" }[key];
            return navigate(direction);
          });
        }
      });
      picker.addEventListener("change", () => { void upload(picker.files[0]); picker.value = ""; });
      const receive = event => {
        if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
        const data = event.data;
        if (data?.type === "ghil-favorites-updated") {
          receiveFavorites(data.kind, data.ids);
          const kind = kinds[type.value];
          void getCatalog(kind).then(rows => { if (controllers.has(node) && kinds[type.value] === kind) updateBrowseLabel(rows); }).catch(showError);
          return;
        }
        if (data?.type === "ghil-categories-updated") { catalogs.delete(kinds[type.value]); randomSettings.delete(kinds[type.value]); }
        if (data?.type === "ghil-ready") {
          catalogs.delete(kinds[type.value]);
          randomSettings.delete(kinds[type.value]);
          void update();
          frame.contentWindow.postMessage({ type: "ghil-current", id: imageId, category: node.properties.ghilCategories[type.value] === "__favorites__" ? "" : node.properties.ghilCategories[type.value] || "", favorites: node.properties.ghilCategories[type.value] === "__favorites__", section: node.properties.ghilSections[type.value] || "all" }, location.origin);
        }
        if (data?.type !== "ghil-select" || typeof data.id !== "string") return;
        selectionRequest++;
        uploadRequest++;
        resetCropForSelection();
        imageId = data.id;
        if (typeof data.category === "string") node.properties.ghilCategories[type.value] = data.favorites ? "__favorites__" : data.category;
        if (typeof data.section === "string") node.properties.ghilSections[type.value] = data.section || "all";
        node.properties.ghilSelections[type.value] = data.id;
        randomHistoryKey = "";
        resetRandomHistory(data.id);
        suspendRandomForManualSelection();
        changed(); close(); void update();
      };
      const browse = node.addWidget("button", "去服装图库选择 · 全部", null, () => {
        if (type.value === "无") return;
        if (type.value === "上传") { picker.click(); return; }
        if (dialog) return;
        dialog = document.createElement("dialog");
        dialog.style.cssText = "width:96vw;height:94vh;max-width:1900px;max-height:96vh;padding:0;border:1px solid #bac2ce;border-radius:12px;background:#f5f7fb;";
        const header = document.createElement("div");
        header.style.cssText = "position:relative;height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 18px;background:#e9efea;color:#23334c;font:14px sans-serif;";
        const title = document.createElement("strong");
        title.textContent = `GooHai · ${type.value}图库`;
        const done = document.createElement("button");
        done.textContent = "关闭"; done.onclick = close;
        header.append(title);
        if (type.value === "服装") {
          const links = document.createElement("nav");
          links.style.cssText = "position:absolute;display:flex;align-items:center;gap:24px;white-space:nowrap;";
          for (const [label, url] of [["原始图库", "https://ai-costume-gallery.pages.dev/"], ["版权 · 致谢", api.apiURL("/ghil/costume/README.md")]]) {
            const link = document.createElement("a");
            link.textContent = label;
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener";
            link.style.cssText = "color:inherit;text-decoration:none;";
            if (label === "版权 · 致谢") {
              link.removeAttribute("target");
              link.onclick = async event => {
                event.preventDefault();
                const { openReadme } = await import(api.apiURL("/ghil/costume/ui/readme.mjs"));
                if (dialog) openReadme(dialog, url);
              };
            }
            links.append(link);
          }
          header.append(links);
          galleryObserver = new ResizeObserver(() => {
            const grid = frame?.contentDocument?.getElementById("grid");
            if (!grid) return;
            links.style.right = `${header.getBoundingClientRect().right - frame.getBoundingClientRect().left - grid.getBoundingClientRect().right}px`;
          });
        }
        header.append(done);
        frame = document.createElement("iframe");
        frame.title = `${type.value}图库`;
        const category = node.properties.ghilCategories[type.value] || "";
        const query = new URLSearchParams({ category: category === "__favorites__" ? "" : category, favorites: String(category === "__favorites__") });
        frame.src = api.apiURL(`/ghil/${kinds[type.value]}/gallery?${query}`);
        frame.style.cssText = "width:100%;height:calc(100% - 44px);border:0;display:block;";
        frame.addEventListener("load", () => {
          frame.contentWindow.addEventListener("keydown", clearCropShortcut, true);
          if (galleryObserver && frame) {
            galleryObserver.observe(frame);
            galleryObserver.observe(frame.contentDocument.documentElement);
          }
        });
        dialog.append(header, frame);
        dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
        window.addEventListener("message", receive);
        document.body.append(dialog); dialog.showModal();
      }, { serialize: false });
      const browseButton = document.createElement("button");
      const randomButton = document.createElement("button");
      randomButton.type = "button";
      randomButton.className = "ghil-manual-random";
      actionRow.append(browseButton);
      box.append(randomButton);
      browse.hidden = true;
      browseButton.textContent = browse.name;
      randomButton.textContent = "随机";
      browseButton.onclick = () => browse.callback?.();
      randomButton.addEventListener("pointerdown", event => { if (event.button === 0) event.stopPropagation(); });
      randomButton.onclick = event => {
        event.stopPropagation();
        if (kinds[type.value]) void navigate("random");
      };
      for (const button of [browseButton, randomButton]) {
        button.addEventListener("wheel", event => {
          event.preventDefault();
          event.stopPropagation();
          app.canvas.processMouseWheel(event);
        }, { passive: false });
      }
      const typeCallback = type.callback;
      type.callback = function () {
        resetCropForSelection();
        typeCallback?.apply(this, arguments);
        uploadRequest++;
        selectionRequest++;
        node.properties.ghilSelections[previousType] = imageId;
        imageId = node.properties.ghilSelections[type.value] ?? defaults[type.value];
        randomHistoryKey = "";
        resetRandomHistory(imageId);
        previousType = type.value;
        close(); changed(); void update();
      };
      const imageCallback = image.callback;
      image.callback = function () {
        resetCropForSelection();
        imageCallback?.apply(this, arguments);
        if (image.value !== imageLabel) imageId = image.value;
        suspendRandomForManualSelection();
        uploadRequest++;
        selectionRequest++;
        node.properties.ghilSelections[type.value] = imageId;
        changed(); void update();
      };
      const randomCallback = randomize.callback;
      randomize.callback = function () {
        randomCallback?.apply(this, arguments);
        manualRandomPending = false;
        changed();
      };
      randomButton.disabled = type.value === "无" || type.value === "上传";
      // LiteGraph tests widget bounds before resize corners; leave the 15 px corners outside this widget.
      const browserWidget = node.addDOMWidget("ghil_browser", "ghil_browser", root, { serialize: false, hideOnZoom: false, margin: 16, getMinHeight: () => 330, getMaxHeight: () => undefined });
      const getWidgetOnPos = node.getWidgetOnPos;
      node.getWidgetOnPos = function () {
        const widget = getWidgetOnPos.apply(this, arguments);
        return widget === browserWidget ? undefined : widget;
      };
      const menu = node.getExtraMenuOptions;
      node.getExtraMenuOptions = function (canvas, options) {
        menu?.apply(this, arguments);
        if (!Array.isArray(options) || !preview.hasAttribute("src")) return;
        options.unshift(
          { content: "复制图像", callback: () => void copyPreview() },
          { content: "保存图像", callback: () => void savePreview() },
        );
        return [];
      };
      const randomSerialize = randomize.serializeValue;
      randomize.serializeValue = async function () {
        syncRandomCategories();
        if (!kinds[type.value] || manualRandomPending) return false;
        return randomSerialize ? randomSerialize.call(this) : randomize.value;
      };
      if (randomCategories) randomCategories.serializeValue = () => { syncRandomCategories(); return randomCategories.value || "[]"; };
      browserWidget.afterQueued = () => {
        if (!manualRandomPending) return;
        randomize.value = true;
        manualRandomPending = false;
        changed();
      };
      const executed = node.onExecuted;
      node.onExecuted = function (message) {
        executed?.apply(this, arguments);
        const result = message.ghil_selection?.[0];
        if (!result || result.type !== type.value) return;
        selectionRequest++;
        uploadRequest++;
        select(result.id);
      };
      const configured = node.onConfigure;
      node.onConfigure = function () {
        configured?.apply(this, arguments);
        imageId = image.value;
        const values = arguments[0]?.widgets_values;
        if (Array.isArray(values) && typeof values[1] === "string") {
          type.value = values[0];
          randomize.value = false;
          imageId = values[1];
        }
        if (node.title === "Goohai 图像库") node.title = "Goohai 加载图库";
        node.properties.ghilSelections ??= {};
        node.properties.ghilCategories ??= {};
        node.properties.ghilSections ??= {};
        if (kinds[type.value] && !node.properties.ghilSelections[type.value] && imageId === defaults["发型"] && type.value !== "发型") {
          imageId = defaults[type.value];
        }
        previousType = type.value;
        root.dataset.ghilNodeId = node.id;
        void update();
      };
      const removed = node.onRemoved;
      node.onRemoved = function () {
        api.removeEventListener("promptQueueing", prepareCrop);
        cropEditor.dispose();
        previewObserver.disconnect();
        favoriteAnimation?.cancel();
        uploadRequest++; previewRequest++; selectionRequest++; close(); controllers.delete(node);
        widgetNodes.delete(root);
        if (hoveredNode === node) hoveredNode = null;
        if (activeNode === node) activeNode = null;
        removed?.apply(this, arguments);
      };
      node.onDragOver = function () { return true; };
      const drop = node.onDragDrop;
      node.onDragDrop = function (event) {
        const file = [...(event.dataTransfer?.files || [])].find(imageFile);
        if (!file) return drop?.apply(this, arguments) ?? false;
        void upload(file); return true;
      };
      node.setSize([310, 650]);
      void update();
    };
  },
});

import { loadFavorites, setFavorite } from '../../ui/favorites.js';

(async function () {
  "use strict";
  let records = window.PORTRAIT_DATA?.records || [];
  const portrait = location.pathname.split("/").at(-2) === "portrait";
  const typeName = portrait ? "人像" : "发型", field = portrait ? "section" : "hair";
  const builtinLabels = portrait ? { "": "全部人像", face: "正脸参考", styling: "造型参考" } : { "": "全部发型", "ショート": "短发", "ミディアム": "中发", "セミロング": "中长发", "ロング": "长发" };
  let labels = { ...builtinLabels };
  records.forEach(item => { if (item[field] && !Object.hasOwn(labels, item[field])) labels[item[field]] = item[field]; });
  const $ = id => document.getElementById(id), escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let favorites = new Set();
  const initial = new URLSearchParams(location.search);
  const state = { hair: initial.get("category") || "", subcategory: "", q: "", favorites: initial.get("favorites") === "true" }; let filtered = [], shown = 0, viewerList = [], viewerIndex = -1;
  const randomKey = `ghil-${portrait ? "portrait" : "hair"}-random`;
  let autoRandom = false, orderKey = null, order = new Map();
  let randomExcluded = new Set();
  try { autoRandom = localStorage.getItem(randomKey) === "true"; } catch {}
  $("random-toggle").checked = autoRandom;
  const pageSize = () => Math.max(1, getComputedStyle($("grid")).gridTemplateColumns.split(" ").filter(Boolean).length) * 10;
  const post = id => { if (window.parent !== window) window.parent.postMessage({ type: "ghil-select", id, category: state.hair, favorites: state.favorites, section: "all" }, location.origin); };
  function renderControls() { const counts = Object.keys(labels).map(hair => [hair, records.filter(item => !hair || item[field] === hair).length]); $("hair-filters").innerHTML = counts.map(([hair, count]) => `<button type="button" class="hair-chip" data-hair="${escape(hair)}" aria-pressed="${state.hair === hair}">${escape(labels[hair])} <small>${count}</small></button>`).join(""); $("favorite-count").textContent = favorites.size; $("favorite-filter").setAttribute("aria-pressed", String(state.favorites)); }
  async function loadSettings() {
    const response = await fetch("random-categories");
    const settings = await response.json();
    if (!response.ok) throw new Error(settings.error);
    randomExcluded = new Set(settings.excluded);
  }
  async function openRandomSettings() {
    try {
      const response = await fetch("catalog");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rows = await response.json();
      favorites = await loadFavorites(portrait ? "portrait" : "hair", rows);
      await loadSettings();
      const url = (path, row) => "assets/" + path.split("/").map(encodeURIComponent).join("/") + (row.custom ? "?v=" + row.version : "");
      records = rows.map(row => ({ ...row, full: url(row.full, row), thumb: url(row.thumb, row), preview: url(row.preview || row.thumb, row) }));
      labels = { ...builtinLabels };
      records.forEach(item => { if (item[field] && !Object.hasOwn(labels, item[field])) labels[item[field]] = item[field]; });
      orderKey = null; render();
    } catch (error) { alert(`无法读取随机分类设置：${error.message}`); return; }
    const options = $("random-options"), categories = [...new Set(records.map(item => item[field]).filter(Boolean))];
    options.innerHTML = categories.map(category => `<label class="ghil-random-option"><input type="checkbox" value="${escape(category)}"${randomExcluded.has(category) ? "" : " checked"}><span>${escape(labels[category])}</span></label>`).join("");
    $("random-dialog").returnValue = "cancel"; $("random-dialog").showModal();
  }
  $("random-settings").addEventListener("click", openRandomSettings);
  $("random-dialog").querySelector("form").addEventListener("submit", async event => {
    if (event.submitter?.value !== "default") return;
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const excluded = [...$("random-options").querySelectorAll("input:not(:checked)")].map(input => input.value);
      const response = await fetch("random-categories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ excluded }) });
      const settings = await response.json();
      if (!response.ok) throw new Error(settings.error);
      randomExcluded = new Set(settings.excluded);
      orderKey = null; render(); $("random-dialog").close();
      window.parent.postMessage({ type: "ghil-categories-updated" }, location.origin);
    } catch (error) { alert(`无法保存随机分类设置：${error.message}`); }
    finally { button.disabled = false; }
  });
  function card(item) { const liked = favorites.has(item.id); return `<article class="portrait-card" data-id="${escape(item.id)}"><div class="card-image"><img src="${escape(item.thumb)}" alt="${escape(item.title || item.hair_zh || item.id)}" loading="eager" decoding="async">${portrait ? `<span class="card-type">${escape(item.section_zh)}</span>` : ""}<div class="ghil-actions"><button type="button" data-use="${escape(item.id)}">使用</button><button type="button" class="card-favorite" data-favorite="${escape(item.id)}" aria-pressed="${liked}"><svg class="ghil-heart-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4 4.55 12.9a5.22 5.22 0 0 1 7.45-7.32 5.22 5.22 0 0 1 7.45 7.32L12 20.4Z"/></svg></button></div></div><div class="card-body"><div class="card-heading"><h3>${escape(item.title || item.name_zh || item.id)}</h3></div><div class="card-meta">${item.custom ? `自定义 · ${escape(item[field])}` : `${escape(item.hair_zh || "")} · <code>${escape(item.id)}</code>`}</div></div></article>`; }
  function appendPage() {
    const next = Math.min(shown + pageSize(), filtered.length);
    $("grid").insertAdjacentHTML("beforeend", filtered.slice(shown, next).map(card).join(""));
    shown = next;
    $("sentinel").hidden = shown >= filtered.length;
    $("end-note").hidden = !filtered.length || shown < filtered.length;
  }
  function render(shuffle = false) {
    if (state.hair && !Object.hasOwn(labels, state.hair)) state.hair = "";
    const subcategories = [...new Set(records.filter(item => state.hair && item.custom && item[field] === state.hair).flatMap(item => item.subcategories || (item.subcategory ? [item.subcategory] : [])))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    if (!subcategories.includes(state.subcategory)) state.subcategory = "";
    $("subcategory").hidden = !subcategories.length;
    $("subcategory").innerHTML = '<option value="">全部</option>' + subcategories.map(name => `<option value="${escape(name)}"${state.subcategory === name ? " selected" : ""}>${escape(name)}</option>`).join("");
    filtered = records.filter(item => (!state.hair || item[field] === state.hair) && (!state.subcategory || item.custom && item.subcategory === state.subcategory) && (!state.favorites || favorites.has(item.id)) && (!state.q || String(item.search || "").toLowerCase().includes(state.q.toLowerCase())));
    $("grid").classList.toggle("landscape", Boolean(state.hair) && !state.favorites && filtered.length > 0 && filtered.every(item => item.custom) && filtered.filter(item => item.w > item.h).length > filtered.length / 2);
    const key = JSON.stringify(state);
    if (!state.hair && !state.favorites && (autoRandom || shuffle || key === orderKey && order.size > 0)) filtered = filtered.filter(item => !randomExcluded.has(item[field]));
    if (key !== orderKey || shuffle) {
      orderKey = key;
      order.clear();
      if (autoRandom || shuffle) {
        for (let i = filtered.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [filtered[i], filtered[j]] = [filtered[j], filtered[i]];
        }
        filtered.forEach((item, index) => order.set(item.id, index));
      }
    }
    if (order.size) filtered.sort((a, b) => (order.get(a.id) ?? Infinity) - (order.get(b.id) ?? Infinity));
    shown = 0; $("grid").innerHTML = ""; appendPage(); $("result-count").textContent = `共 ${filtered.length} 张${typeName}参考`; $("empty").hidden = filtered.length > 0; renderControls();
  }
  $("random-toggle").addEventListener("change", event => {
    autoRandom = event.target.checked;
    try { localStorage.setItem(randomKey, String(autoRandom)); } catch {}
    orderKey = null;
    render();
  });
  $("shuffle").addEventListener("click", () => render(true));
  $("subcategory").addEventListener("change", event => { state.subcategory = event.target.value; render(); });
  async function toggleFavorite(id) {
    try { favorites = await setFavorite(portrait ? "portrait" : "hair", id); }
    catch (error) { alert(`无法保存收藏：${error.message}`); return; }
    if ($("viewer").open) syncViewerFavorite();
    if (state.favorites) { render(); return; }
    document.querySelectorAll("[data-favorite]").forEach(button => button.setAttribute("aria-pressed", String(favorites.has(button.dataset.favorite))));
    renderControls();
  }
  function syncViewerFavorite() { const item = viewerList[viewerIndex]; if (!item) return; $("viewer-favorite").innerHTML = `<svg class="ghil-heart-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4 4.55 12.9a5.22 5.22 0 0 1 7.45-7.32 5.22 5.22 0 0 1 7.45 7.32L12 20.4Z"/></svg><span>收藏</span>`; $("viewer-favorite").setAttribute("aria-pressed", String(favorites.has(item.id))); $("viewer-favorite").setAttribute("aria-label", favorites.has(item.id) ? "取消收藏" : "收藏"); }
  function openViewer(list, index) { viewerList = list.slice(); viewerIndex = index; const item = list[index]; if (!item) return; $("viewer-image").src = item.full; $("viewer-image").alt = item.title || item.id; $("viewer-title").textContent = item.title || item.name_zh || item.id; $("viewer-id").textContent = item.id; syncViewerFavorite(); $("viewer").showModal(); }
  $("hair-filters").addEventListener("click", event => { const button = event.target.closest("[data-hair]"); if (button) { state.hair = button.dataset.hair; state.subcategory = ""; if (portrait) state.favorites = false; render(); } }); $("favorite-filter").addEventListener("click", () => { state.favorites = !state.favorites; if (portrait) state.hair = ""; render(); }); $("search").addEventListener("input", event => { state.q = event.target.value.trim(); render(); });
  new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting) && shown < filtered.length) appendPage();
  }).observe($("sentinel"));
  $("grid").addEventListener("click", event => { const use = event.target.closest("[data-use]"); if (use) return post(use.dataset.use); const favorite = event.target.closest("[data-favorite]"); if (favorite) return toggleFavorite(favorite.dataset.favorite); const item = event.target.closest("[data-id]"); if (item) openViewer(filtered, filtered.findIndex(row => row.id === item.dataset.id)); });
  $("viewer-close").addEventListener("click", () => $("viewer").close()); $("viewer-prev").addEventListener("click", () => openViewer(viewerList, (viewerIndex + viewerList.length - 1) % viewerList.length)); $("viewer-next").addEventListener("click", () => openViewer(viewerList, (viewerIndex + 1) % viewerList.length)); $("use-portrait").addEventListener("click", () => viewerList[viewerIndex] && post(viewerList[viewerIndex].id)); $("viewer-favorite").addEventListener("click", () => { const item = viewerList[viewerIndex]; if (item) void toggleFavorite(item.id); });
  window.addEventListener("message", event => { if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== "ghil-current") return; state.hair = event.data.category || ""; state.subcategory = ""; state.favorites = Boolean(event.data.favorites); render(); });
  document.title = `GooHai · ${typeName}图库`;
  $("hair-filters").setAttribute("aria-label", portrait ? "人像分类" : "发型长度");
  $("search").placeholder = `搜索${typeName}或 ID`;
  $("search").setAttribute("aria-label", `搜索${typeName}或 ID`);
  $("empty").textContent = `没有找到匹配的${typeName}`;
  $("end-note").textContent = `已显示全部${typeName}`;
  try { await Promise.all([loadSettings(), loadFavorites(portrait ? "portrait" : "hair", records).then(ids => { favorites = ids; })]); }
  catch (error) { $("result-count").textContent = `图库设置读取失败：${error.message}`; return; }
  render(); if (window.parent !== window) window.parent.postMessage({ type: "ghil-ready" }, location.origin);
})();

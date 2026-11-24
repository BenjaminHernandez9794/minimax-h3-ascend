'use strict';
import { loadFavorites, setFavorite } from '../../ui/favorites.js';
const $ = (id) => document.getElementById(id);
const initial = new URLSearchParams(location.search);
let records = [], filtered = [], category = initial.get('category') || '', subcategory = '', shown = 0, current = 0;
let viewerList = [];
let autoRandom = false, orderKey = null, order = new Map();
let randomExcluded = new Set();
try { autoRandom = localStorage.getItem('ghil-costume-random') === 'true'; } catch {}
$('random-toggle').checked = autoRandom;
const pageSize = () => Math.max(1, getComputedStyle($('grid')).gridTemplateColumns.split(' ').filter(Boolean).length) * 10;
let selectedId = '';
let favoritesOnly = initial.get('favorites') === 'true';
let favorites = new Set();
function select(id) {
  if (window.parent !== window) window.parent.postMessage({type: 'ghil-select', id, category, favorites: favoritesOnly}, location.origin);
}
async function toggleFavorite(id) {
  try { favorites = await setFavorite('costume', id); }
  catch (error) { alert(`无法保存收藏：${error.message}`); return; }
  if ($('viewer').open) syncViewerFavorite();
  if (favoritesOnly) { applyFilters(); return; }
  $('favorites').textContent = `收藏 ${favorites.size}`;
  document.querySelectorAll('[data-favorite]').forEach(button => {
    const liked = favorites.has(button.dataset.favorite);
    button.setAttribute('aria-pressed', String(liked));
    button.setAttribute('aria-label', liked ? '取消收藏' : '收藏');
  });
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function renderCategories() {
  const counts = new Map([['', records.length]]);
  records.forEach((r) => counts.set(r.分类, (counts.get(r.分类) || 0) + 1));
  $('categories').replaceChildren(...[...counts].map(([name, count]) => {
    const button = element('button', name || '全部');
    button.append(element('span', count.toLocaleString()));
    button.setAttribute('aria-pressed', String(category === name));
    button.addEventListener('click', () => { category = name; subcategory = ''; applyFilters(); });
    return button;
  }));
}
async function openRandomSettings() {
  try { await loadData(); applyFilters(); }
  catch (error) { alert(`无法读取随机分类设置：${error.message}`); return; }
  const categories = [...new Set(records.map(row => row.分类).filter(Boolean))];
  const options = $('random-options');
  options.replaceChildren(...categories.map(category => { const label = element('label', undefined, 'ghil-random-option'); const input = element('input'); input.type = 'checkbox'; input.value = category; input.checked = !randomExcluded.has(category); label.append(input, element('span', category)); return label; }));
  $('random-dialog').returnValue = 'cancel';
  $('random-dialog').showModal();
}
$('random-settings').addEventListener('click', openRandomSettings);
$('random-dialog').querySelector('form').addEventListener('submit', async event => {
  if (event.submitter?.value !== 'default') return;
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const excluded = [...$('random-options').querySelectorAll('input:not(:checked)')].map(input => input.value);
    const response = await fetch('random-categories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ excluded }) });
    const settings = await response.json();
    if (!response.ok) throw new Error(settings.error);
    randomExcluded = new Set(settings.excluded);
    orderKey = null; applyFilters(); $('random-dialog').close();
    window.parent.postMessage({ type: 'ghil-categories-updated' }, location.origin);
  } catch (error) { alert(`无法保存随机分类设置：${error.message}`); }
  finally { button.disabled = false; }
});
function applyFilters(shuffle = false) {
  if (category && !records.some(row => row.分类 === category)) category = '';
  const subcategories = [...new Set(records.filter(row => category && row.custom && row.分类 === category).flatMap(row => row.subcategories || (row.subcategory ? [row.subcategory] : [])))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  if (!subcategories.includes(subcategory)) subcategory = '';
  $('subcategory').hidden = !subcategories.length;
  $('subcategory').replaceChildren(...['', ...subcategories].map(name => { const option = element('option', name || '全部'); option.value = name; option.selected = name === subcategory; return option; }));
  const words = $('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  filtered = records.filter((r) => (!category || r.分类 === category) && (!subcategory || r.custom && r.subcategory === subcategory) && (!favoritesOnly || favorites.has(r.id)) && words.every((w) => r.检索.toLowerCase().includes(w)));
  $('grid').classList.toggle('landscape', Boolean(category) && !favoritesOnly && filtered.length > 0 && filtered.every(row => row.custom) && filtered.filter(row => row.w > row.h).length > filtered.length / 2);
  const key = JSON.stringify([category, subcategory, favoritesOnly, words]);
  if (!category && !favoritesOnly && (autoRandom || shuffle || key === orderKey && order.size > 0)) filtered = filtered.filter(row => !randomExcluded.has(row.分类));
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
  shown = 0;
  $('grid').replaceChildren();
  renderCategories();
  $('section-title').textContent = category || '全部服装';
  $('empty').hidden = filtered.length > 0;
  $('favorites').setAttribute('aria-pressed', String(favoritesOnly));
  $('favorites').textContent = `收藏 ${favorites.size}`;
  appendPage();
}
function appendPage() {
  const start = shown;
  const cards = filtered.slice(start, start + pageSize()).map((r, i) => {
    const button = element('article', undefined, 'card');
    button.tabIndex = 0;
    button.setAttribute('aria-label', `查看 ${r.id} ${r.分类}`);
    button.setAttribute('aria-current', String(r.id === selectedId));
    const img = element('img');
    img.src = r.缩略图; img.alt = `${r.分类} ${r.关键词.join('、')} ${r.id}`;
    img.loading = 'eager'; img.decoding = 'async'; img.width = 300; img.height = 450;
    img.addEventListener('error', () => { img.alt = `${r.id} 图片加载失败，请检查节点内的本地素材`; });
    const info = element('div', undefined, 'card-info');
    const heading = element('div', undefined, 'card-heading');
    heading.append(element('h3', r.title ?? r.id), element('span', r.custom ? `自定义 · ${r.分类}` : r.分类, 'card-cat'));
    info.append(heading);
    const picture = element('div', undefined, 'ghil-costume-image card-image');
    const actions = element('div', undefined, 'ghil-actions');
    const use = element('button', '使用');
    use.type = 'button';
    use.dataset.use = r.id;
    use.addEventListener('click', event => { event.stopPropagation(); select(r.id); });
    const favorite = element('button', undefined, 'ghil-heart');
    favorite.type = 'button'; favorite.dataset.favorite = r.id;
    favorite.innerHTML = '<svg class="ghil-heart-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4 4.55 12.9a5.22 5.22 0 0 1 7.45-7.32 5.22 5.22 0 0 1 7.45 7.32L12 20.4Z"/></svg>';
    favorite.setAttribute('aria-label', favorites.has(r.id) ? '取消收藏' : '收藏');
    favorite.setAttribute('aria-pressed', String(favorites.has(r.id)));
    favorite.addEventListener('click', event => { event.stopPropagation(); toggleFavorite(r.id); });
    actions.append(use, favorite); picture.append(img, actions);
    button.append(picture, info);
    button.addEventListener('click', () => { viewerList = filtered.slice(); current = start + i; showDetail(); $('viewer').showModal(); });
    button.addEventListener('keydown', event => {
      if (event.target === button && ['Enter', ' '].includes(event.key)) { event.preventDefault(); button.click(); }
    });
    return button;
  });
  $('grid').append(...cards); shown += cards.length;
  $('status').textContent = `共 ${filtered.length.toLocaleString()} 套 · 已显示 ${shown.toLocaleString()} 套`;
  $('sentinel').hidden = shown >= filtered.length;
}
function showDetail() {
  const r = viewerList[current];
  $('detail-title').textContent = r.title ?? r.id;
  $('detail-cat').textContent = r.分类;
  $('position').textContent = `${current + 1} / ${viewerList.length}`;
  $('tags').textContent = r.关键词.join(' · ');
  $('english').textContent = r.英文关键词;
  $('image-status').textContent = '正在加载预览图…';
  $('large').onload = () => { $('image-status').textContent = ''; };
  $('large').onerror = () => { $('image-status').textContent = '预览图加载失败，可尝试打开原图。'; };
  $('large').src = r.预览图;
  $('large').alt = `${r.id} ${r.关键词.join('、')}`;
  syncViewerFavorite();
  $('open-original').href = r.原图;
  $('prev').disabled = current === 0; $('next').disabled = current === viewerList.length - 1;
  $('copy').textContent = '复制 ID';
  $('use-costume').disabled = window.parent === window;
  $('use-costume').textContent = window.parent === window ? '请从 ComfyUI 节点打开以使用服装' : '使用此服装 → ComfyUI';
}
function syncViewerFavorite() {
  const liked = favorites.has(viewerList[current].id);
  $('viewer-favorite').textContent = `${liked ? '♥' : '♡'} 收藏`;
  $('viewer-favorite').setAttribute('aria-pressed', String(liked));
  $('viewer-favorite').setAttribute('aria-label', liked ? '取消收藏' : '收藏');
}
$('viewer-favorite').addEventListener('click', () => toggleFavorite(viewerList[current].id));
$('random-toggle').addEventListener('change', event => {
  autoRandom = event.target.checked;
  try { localStorage.setItem('ghil-costume-random', String(autoRandom)); } catch {}
  orderKey = null;
  applyFilters();
});
$('shuffle').addEventListener('click', () => applyFilters(true));
$('q').addEventListener('input', () => applyFilters());
$('subcategory').addEventListener('change', event => { subcategory = event.target.value; applyFilters(); });
$('favorites').addEventListener('click', () => { favoritesOnly = !favoritesOnly; applyFilters(); });
$('reset').addEventListener('click', () => { category = ''; subcategory = ''; favoritesOnly = false; $('q').value = ''; applyFilters(); });
new IntersectionObserver(entries => {
  if (entries.some(entry => entry.isIntersecting) && shown < filtered.length) appendPage();
}).observe($('sentinel'));
$('close').addEventListener('click', () => $('viewer').close());
$('prev').addEventListener('click', () => { if (current > 0) { current--; showDetail(); } });
$('next').addEventListener('click', () => { if (current < viewerList.length - 1) { current++; showDetail(); } });
$('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(viewerList[current].id); $('copy').textContent = '已复制'; }
  catch { $('copy').textContent = '复制失败，请手动复制上方 ID'; }
});

document.addEventListener('keydown', (e) => {
  if ($('viewer').open) {
    if (e.key === 'ArrowLeft') { e.preventDefault(); $('prev').click(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); $('next').click(); }
  } else if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
    e.preventDefault(); $('q').focus();
  }
});
for (const dialog of [$('viewer')]) dialog.addEventListener('click', (e) => {
  const box = dialog.getBoundingClientRect();
  if (e.target === dialog && (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom)) dialog.close();
});
async function loadData() {
    const [response, configResponse, ids] = await Promise.all([fetch('catalog'), fetch('random-categories'), loadFavorites('costume')]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const settings = await configResponse.json();
    if (!configResponse.ok) throw new Error(settings.error);
    randomExcluded = new Set(settings.excluded);
    records = await response.json();
    const valid = new Set(records.map(row => row.id));
    favorites = new Set([...ids].filter(id => valid.has(id)));
    const url = path => 'assets/' + path.split('/').map(encodeURIComponent).join('/');
    if (Array.isArray(records)) records = records.map((row) => {
      const version = row.custom ? '?v=' + row.version : '';
      return { ...row, 缩略图: url(row.缩略图) + version, 预览图: url(row.预览图) + version, 原图: url(row.原图) + version };
    });
    if (!Array.isArray(records) || !records.length) throw new Error('数据为空');
    orderKey = null;
}
async function init() {
  try {
    await loadData();
    applyFilters();
    if (window.parent !== window) window.parent.postMessage({ type: 'ghil-ready' }, location.origin);
  } catch (error) {
    $('status').textContent = '数据加载失败，请检查 models/GHIL/costume/data 和完整素材目录。';
    console.error('服装数据加载失败', error);
  }
}
init();

$('use-costume').addEventListener('click', () => {
  if (viewerList[current]) select(viewerList[current].id);
});
window.addEventListener('message', (event) => {
  if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== 'ghil-current') return;
  const id = event.data.id;
  if (typeof event.data.category === 'string') { category = event.data.category; subcategory = ''; }
  if (typeof event.data.favorites === 'boolean') favoritesOnly = event.data.favorites;
  if (typeof id === 'string' && records.some((row) => row.id === id)) { selectedId = id; applyFilters(); }
});

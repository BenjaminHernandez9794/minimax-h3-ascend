const storageKeys = { costume: "ghil-costume-favorites-v1", pose: "ghil-pose-favorites-v1", hair: "portrait-atlas-favorites-v2", portrait: "portrait-atlas-favorites-v1" };
const favorites = new Map(), loading = new Map(), pending = new Map();

export function favoriteIds(kind) {
  return favorites.get(kind) || new Set();
}

async function request(kind, changes) {
  const response = await fetch(`/ghil/${kind}/favorites`, changes ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes)
  } : undefined);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  const ids = new Set(data.ids);
  favorites.set(kind, ids);
  return ids;
}

export async function loadFavorites(kind, rows) {
  if (!loading.has(kind)) {
    loading.set(kind, (async () => {
      let legacy = [];
      try {
        const values = JSON.parse(localStorage.getItem(storageKeys[kind]) || "[]");
        if (Array.isArray(values)) legacy = values.filter(value => typeof value === "string" && value);
      } catch {}
      const ids = await request(kind, legacy.length ? { add: legacy } : undefined);
      try { localStorage.removeItem(storageKeys[kind]); } catch {}
      if (window.parent !== window) window.parent.postMessage({ type: "ghil-favorites-updated", kind, ids: [...ids] }, location.origin);
      return ids;
    })());
  }
  try {
    await loading.get(kind);
    if (rows) {
      const valid = new Set(rows.map(row => row.id));
      favorites.set(kind, new Set([...favoriteIds(kind)].filter(id => valid.has(id))));
    }
    return favoriteIds(kind);
  }
  catch (error) { loading.delete(kind); throw error; }
}

export function setFavorite(kind, id, liked) {
  const task = (pending.get(kind) || Promise.resolve()).catch(() => {}).then(async () => {
    await loadFavorites(kind);
    if (liked === undefined) liked = !favoriteIds(kind).has(id);
    const ids = await request(kind, { [liked ? "add" : "remove"]: [id] });
    if (window.parent !== window) window.parent.postMessage({ type: "ghil-favorites-updated", kind, ids: [...ids] }, location.origin);
    return ids;
  });
  pending.set(kind, task);
  return task;
}

export function receiveFavorites(kind, ids) {
  if (Object.hasOwn(storageKeys, kind) && Array.isArray(ids) && ids.every(id => typeof id === "string")) {
    favorites.set(kind, new Set(ids));
    loading.set(kind, Promise.resolve());
  }
}

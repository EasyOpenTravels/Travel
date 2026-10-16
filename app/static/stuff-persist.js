(function () {
  const DB = 'open-road-my-stuff-v2', VER = 1, STORES = ['journals', 'copies', 'cards'];
  function openDB() {
    return new Promise((resolve, reject) => {
      const r = indexedDB.open(DB, VER);
      r.onupgradeneeded = () => { for (const n of STORES) if (!r.result.objectStoreNames.contains(n)) r.result.createObjectStore(n, { keyPath: 'id' }); };
      r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
    });
  }
  const reqP = req => new Promise((resolve, reject) => { req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
  const txP = tx => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted')); });
  function normaliseJournal(row, ownerId) {
    return Object.assign({}, row, {
      coverColor: row.coverColor || row.cover_color || 'cream',
      createdAt: row.createdAt || row.created_at || new Date().toISOString(),
      updatedAt: row.updatedAt || row.updated_at || new Date().toISOString(),
      ownerId: String(row.ownerId || ownerId || ''),
      _serverUpdatedAt: row.updated_at || row._serverUpdatedAt || row.updatedAt || '',
      _localEditedAt: row._localEditedAt || ''
    });
  }
  async function seed(snapshot) {
    try {
      if (navigator.storage?.persist) await navigator.storage.persist();
      const db = await openDB();
      const ownerId = String(window.__OR_JOURNAL_CONTEXT__?.user_id || '');
      try {
        for (const name of STORES) {
          const tx = db.transaction(name, 'readwrite');
          const store = tx.objectStore(name);
          if (name === 'journals') {
            const existing = await reqP(store.getAll());
            const byId = new Map(existing.map(x => [String(x.id), x]));
            const serverRows = (snapshot?.journals || []).map(x => normaliseJournal(x, ownerId));
            const serverIds = new Set(serverRows.map(x => String(x.id)));
            // Keep newer offline edits, including edits to existing server entries.
            for (const old of existing) {
              const isLocal = typeof old.id === 'string' && old.id.startsWith('local-');
              const dirty = old._localEditedAt && String(old._localEditedAt) > String(old._serverUpdatedAt || '');
              if (isLocal || dirty) continue;
              if (!serverIds.has(String(old.id))) store.delete(old.id);
            }
            for (const row of serverRows) {
              const old = byId.get(String(row.id));
              const dirty = old?._localEditedAt && String(old._localEditedAt) > String(old._serverUpdatedAt || '');
              if (dirty) continue;
              store.put(row);
            }
          } else {
            const keys = await reqP(store.getAllKeys());
            for (const key of keys) if (!(typeof key === 'string' && key.startsWith('local-'))) store.delete(key);
            for (const row of (snapshot?.[name] || [])) store.put(row);
          }
          await txP(tx);
        }
      } finally { db.close(); }
      return true;
    } catch (_) { return false; }
  }
  window.OpenRoadStuffOffline = { seed };
  window.addEventListener('load', () => { if (window.__OR_STUFF_SNAPSHOT__) seed(window.__OR_STUFF_SNAPSHOT__); });
})();

/* My Story recovery layer: synchronous local backup, IndexedDB backup, server autosave. */
(function () {
  'use strict';
  const input = document.getElementById('j5Input');
  const form = document.getElementById('j5Form');
  const root = document.getElementById('journalV5');
  const ctx = window.__OR_JOURNAL_CONTEXT__ || {};
  const userId = String(ctx.user_id || root?.dataset.userId || 'guest');
  const titleSide = document.getElementById('j5TitleSide');
  const titleMain = document.getElementById('j5TitleMain');
  const titleField = document.getElementById('j5TitleField');
  const bodyField = document.getElementById('j5BodyField');
  const moodField = document.getElementById('j5MoodField');
  const state = document.getElementById('j5SaveState');
  const count = document.getElementById('j5Count');
  const legacyKey = 'openroad-journal-v5';
  const DB_NAME = 'open-road-journal-recovery-v1';
  const DB_VERSION = 1;
  let entryId = String(ctx.entry_id || root?.dataset.entryId || '').trim();
  let timer = null;
  let idbTimer = null;
  let revision = 0;
  let syncing = false;
  let syncAgain = false;
  let lastServerFingerprint = '';
  let restoreBanner = null;

  function slotId(id = entryId) { return `${userId}:${id || 'new'}`; }
  function slotKey(id = entryId) { return `openroad-journal-recovery-v2:${slotId(id)}`; }
  function todayTitle() {
    return new Date().toLocaleDateString(undefined, { day: '2-digit', month: 'long', year: 'numeric' });
  }
  function safeRead(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; }
  }
  function openRecoveryDB() {
    return new Promise((resolve, reject) => {
      if (!('indexedDB' in window)) return reject(new Error('IndexedDB unavailable'));
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains('drafts')) {
          request.result.createObjectStore('drafts', { keyPath: 'id' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('Could not open recovery storage'));
      request.onblocked = () => reject(new Error('Recovery storage upgrade blocked'));
    });
  }
  async function idbGet(id) {
    const db = await openRecoveryDB();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('drafts', 'readonly');
        const req = tx.objectStore('drafts').get(id);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error);
      });
    } finally { db.close(); }
  }
  async function idbPut(row) {
    const db = await openRecoveryDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction('drafts', 'readwrite');
        tx.objectStore('drafts').put(row);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error('Recovery write failed'));
        tx.onabort = () => reject(tx.error || new Error('Recovery write aborted'));
      });
    } finally { db.close(); }
  }
  async function idbDelete(id) {
    const db = await openRecoveryDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction('drafts', 'readwrite');
        tx.objectStore('drafts').delete(id);
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
      });
    } finally { db.close(); }
  }
  function currentSnapshot() {
    return {
      id: slotId(), userId, entryId: entryId || '',
      title: String(titleMain?.value ?? titleSide?.value ?? titleField?.value ?? '').trim(),
      body: String(input?.value ?? ''), mood: String(moodField?.value || 'morning'),
      tags: String(ctx.tags || ''), cover_color: String(ctx.cover_color || 'cream'),
      savedAt: new Date().toISOString(), syncedAt: '',
      origin: 'my-story-editor-v2'
    };
  }
  function fingerprint(x) { return `${String(x?.title || '').trim()}\u0000${String(x?.body || '')}`; }
  function setStatus(message) { if (state) state.textContent = message; }
  function paint() {
    if (!input || !count) return;
    const words = (input.value.trim().match(/\S+/g) || []).length;
    count.textContent = `${words} word${words === 1 ? '' : 's'}`;
  }
  function syncTitles(value) {
    const title = String(value || '').trim();
    if (titleField) titleField.value = title;
    if (titleMain && titleMain.value !== value) titleMain.value = value;
    if (titleSide && titleSide.value !== value) titleSide.value = value;
  }
  function persistNow() {
    if (!input || !form) return null;
    const data = currentSnapshot();
    data.id = slotId();
    // localStorage is synchronous: the latest keystrokes are backed up before navigation/close.
    try {
      localStorage.setItem(slotKey(), JSON.stringify(data));
      localStorage.setItem(legacyKey, JSON.stringify(data));
      localStorage.setItem('openroad-stuff-owner-id', userId);
      localStorage.setItem('openroad-journal-last-recovery', JSON.stringify({
        userId, entryId: entryId || '', title: data.title, savedAt: data.savedAt
      }));
    } catch (_) { /* IndexedDB and the server are independent fallback layers. */ }
    clearTimeout(idbTimer);
    idbTimer = setTimeout(() => idbPut(data).catch(() => setStatus('Device backup limited · keep this page open')), 120);
    revision += 1;
    return data;
  }
  function scheduleServerSync(delay = 1400) {
    clearTimeout(timer);
    timer = setTimeout(() => { void serverSync(); }, delay);
  }
  async function serverSync(force = false) {
    if (!input || !form) return;
    if (syncing) { syncAgain = true; return; }
    const data = currentSnapshot();
    if (!data.body.trim()) {
      setStatus('Saved on this device · write freely');
      return;
    }
    if (!navigator.onLine) { setStatus('Offline · backup saved on this device'); return; }
    syncing = true;
    try {
      const sendRevision = revision;
      const previousSlot = slotId();
      const previousKey = slotKey();
      setStatus('Saving to your private journal…');
      const response = await fetch('/my-stuff/journal/autosave', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ entry_id: entryId, title: data.title, body: data.body, mood: data.mood, tags: data.tags, cover_color: data.cover_color }),
        keepalive: !!force
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        if (response.status === 423) setStatus('Journal locked · device backup is safe');
        else setStatus('Device backup saved · server will retry');
        return;
      }
      if (result.entry_id) {
        entryId = String(result.entry_id);
        const hidden = form.querySelector('[name="entry_id"]');
        if (hidden) hidden.value = entryId;
        if (root) root.dataset.entryId = entryId;
      }
      data.entryId = entryId;
      data.id = slotId();
      data.syncedAt = result.updated_at || new Date().toISOString();
      if (previousSlot !== slotId()) {
        void idbDelete(previousSlot).catch(() => {});
        try { const oldDraft = safeRead(previousKey); if (oldDraft && fingerprint(oldDraft) === fingerprint(data)) localStorage.removeItem(previousKey); } catch (_) {}
      }
      data.title = result.title || data.title;
      lastServerFingerprint = fingerprint(data);
      try {
        localStorage.setItem(slotKey(), JSON.stringify(data));
        // Only retire the legacy one-slot backup once the server acknowledged the exact text.
        const legacy = safeRead(legacyKey);
        if (legacy && String(legacy.userId || userId) === userId && fingerprint(legacy) === fingerprint(data)) {
          localStorage.removeItem(legacyKey);
        }
      } catch (_) {}
      idbPut(data).catch(() => {});
      setStatus(sendRevision === revision ? 'Saved to journal + device' : 'Device safe · syncing latest words…');
      if (sendRevision !== revision || syncAgain) { syncAgain = false; void serverSync(); }
    } catch (_) {
      setStatus('Offline or connection interrupted · device backup saved');
    } finally {
      syncing = false;
      if (syncAgain) { syncAgain = false; void serverSync(); }
    }
  }
  function setupBackupRestore() {
    const trigger = document.getElementById('j5RestoreTrigger');
    const fileInput = document.getElementById('j5BackupFile');
    trigger?.addEventListener('click', event => { event.preventDefault(); fileInput?.click(); });
    fileInput?.addEventListener('change', async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      try {
        const backup = JSON.parse(await file.text());
        if (!backup || typeof backup !== 'object' || (!Array.isArray(backup.entries) && !Array.isArray(backup.recoveryDrafts) && !backup.legacyRecoveryCopy)) {
          throw new Error('This file does not look like a My Story backup.');
        }
        const response = await fetch('/my-stuff/journal/restore.json', {
          method: 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify(backup)
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.ok) throw new Error(result.error || 'Restore could not be completed.');
        alert(`Backup merged. Restored ${result.restored} page(s); skipped ${result.skipped} duplicate or invalid page(s).`);
        location.reload();
      } catch (error) {
        alert(`Backup restore failed: ${error?.message || 'unknown error'}. Your backup file has not been changed.`);
      } finally { fileInput.value = ''; }
    });
  }

  function recoverBanner(draft) {
    if (!input || !draft || restoreBanner) return;
    restoreBanner = document.createElement('div');
    restoreBanner.className = 'j5-recovery-banner';
    const text = document.createElement('span');
    text.textContent = 'A separate recovery copy was found on this device. Your current page has not been replaced.';
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Restore recovery copy';
    button.addEventListener('click', () => {
      input.value = String(draft.body || '');
      syncTitles(String(draft.title || todayTitle()));
      persistNow(); paint(); setStatus('Recovered copy saved on device · syncing…'); scheduleServerSync(150);
      restoreBanner.remove(); restoreBanner = null;
    });
    restoreBanner.append(text, button);
    const compose = document.querySelector('.j5-compose');
    if (compose) compose.prepend(restoreBanner);
  }
  async function restoreDraftIfNeeded() {
    if (!input) return;
    const serverBody = String(input.value || '');
    const serverData = { title: String(titleField?.value || ctx.title || ''), body: serverBody };
    const local = await idbGet(slotId()).catch(() => null);
    const localStorageDraft = safeRead(slotKey());
    const best = [local, localStorageDraft].filter(Boolean).sort((a, b) => String(b.savedAt || '').localeCompare(String(a.savedAt || '')))[0];
    const serverStamp = String(ctx.updated_at || '');
    if (best && fingerprint(best) !== fingerprint(serverData)) {
      const newer = !serverBody.trim() || !serverStamp || String(best.savedAt || '') > serverStamp;
      if (newer) {
        input.value = String(best.body || ''); syncTitles(String(best.title || todayTitle()));
        setStatus('Recovered local draft · checking server…');
        paint(); scheduleServerSync(350);
      } else recoverBanner(best);
    }
    // Migrate the old build's one-slot draft without deleting it before confirmation.
    const legacy = safeRead(legacyKey);
    if (legacy && String(legacy.userId || userId) === userId && (legacy.body || legacy.title)) {
      const differs = fingerprint(legacy) !== fingerprint({ title: titleField?.value || ctx.title || '', body: input.value || '' });
      if (differs) {
        if (!String(input.value || '').trim()) {
          input.value = String(legacy.body || ''); syncTitles(String(legacy.title || todayTitle()));
          setStatus('Recovered older draft · saving securely…'); paint(); persistNow(); scheduleServerSync(200);
        } else recoverBanner(legacy);
      }
    }
  }

  // When an offline copy was written in the offline workspace, upload it safely once
  // this same user's workspace is online. Owner checks happen again on the server.
  async function syncOfflineWorkspaceRows() {
    if (!navigator.onLine || !userId || userId === 'guest') return;
    let db;
    try {
      db = await new Promise((resolve, reject) => {
        const req = indexedDB.open('open-road-my-stuff-v2', 1);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      if (!db.objectStoreNames.contains('journals')) return;
      const rows = await new Promise((resolve, reject) => {
        const req = db.transaction('journals', 'readonly').objectStore('journals').getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
      });
      for (const row of rows) {
        if (String(row.ownerId || '') !== userId) continue;
        const isLocal = String(row.id).startsWith('local-');
        const dirty = row._localEditedAt && String(row._localEditedAt) > String(row._serverUpdatedAt || '');
        if (!isLocal && !dirty) continue;
        if (!String(row.body || '').trim()) continue;
        const numericEntryId = !isLocal && /^\d+$/.test(String(row.id)) ? String(row.id) : '';
        const response = await fetch('/my-stuff/journal/autosave', {
          method: 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ entry_id: numericEntryId, title: row.title || todayTitle(), body: row.body || '',
            mood: row.mood || 'morning', tags: row.tags || '', cover_color: row.coverColor || row.cover_color || 'cream' })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || !result.ok || !result.entry_id) continue;
        const newRow = Object.assign({}, row, {
          id: Number(result.entry_id), title: result.title || row.title,
          updatedAt: result.updated_at || new Date().toISOString(),
          updated_at: result.updated_at || new Date().toISOString(),
          _serverUpdatedAt: result.updated_at || new Date().toISOString(), _localEditedAt: '',
          entryId: Number(result.entry_id)
        });
        await new Promise((resolve, reject) => {
          const tx = db.transaction('journals', 'readwrite');
          if (String(row.id) !== String(newRow.id)) tx.objectStore('journals').delete(row.id);
          tx.objectStore('journals').put(newRow);
          tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
        });
      }
    } catch (_) { /* Keep the local copy if synchronization cannot be completed. */ }
    finally { try { db?.close(); } catch (_) {} }
  }

  if ('storage' in navigator && navigator.storage?.persist) navigator.storage.persist().catch(() => {});
  try { localStorage.setItem('openroad-stuff-owner-id', userId); } catch (_) {}
  setupBackupRestore();
  if (!input || !form) {
    // Re-key a draft created on the New page after the regular form save redirects to
    // the server-confirmed entry. This keeps the recovery copy attached to that entry.
    (async () => {
      try {
        const db = await openRecoveryDB();
        let drafts = [];
        try { drafts = await new Promise((resolve, reject) => { const req = db.transaction('drafts','readonly').objectStore('drafts').getAll(); req.onsuccess=()=>resolve(req.result||[]); req.onerror=()=>reject(req.error); }); }
        finally { db.close(); }
        const server = { title: String(ctx.title || ''), body: String(ctx.body || '') };
        for (const d of drafts) {
          if (String(d.userId || '') !== userId || fingerprint(d) !== fingerprint(server)) continue;
          if (!d.entryId && ctx.entry_id) {
            const oldId = d.id; d.entryId = String(ctx.entry_id); d.id = slotId(String(ctx.entry_id)); d.syncedAt = String(ctx.updated_at || new Date().toISOString());
            await idbPut(d); await idbDelete(oldId);
          }
        }
      } catch (_) {}
    })();
    // On the reader view, keep confirmed content but retire only a legacy backup that
    // exactly matches the server record. Per-entry IndexedDB backups remain recoverable.
    const server = { title: String(ctx.title || ''), body: String(ctx.body || '') };
    const legacy = safeRead(legacyKey);
    if (legacy && String(legacy.userId || userId) === userId && fingerprint(legacy) === fingerprint(server)) {
      try { localStorage.removeItem(legacyKey); } catch (_) {}
    }
    window.addEventListener('load', () => { window.setTimeout(() => void syncOfflineWorkspaceRows(), 600); });
    window.addEventListener('online', () => void syncOfflineWorkspaceRows());
    return;
  }

  if (!String(titleField?.value || '').trim()) syncTitles(todayTitle());
  if (titleSide && titleMain) {
    titleSide.addEventListener('input', () => { syncTitles(titleSide.value); persistNow(); scheduleServerSync(); });
    titleMain.addEventListener('input', () => { syncTitles(titleMain.value); persistNow(); scheduleServerSync(); });
  } else {
    titleMain?.addEventListener('input', () => { syncTitles(titleMain.value); persistNow(); scheduleServerSync(); });
  }
  input.addEventListener('input', () => { paint(); persistNow(); setStatus(navigator.onLine ? 'Saved on this device · syncing…' : 'Offline · backup saved on this device'); scheduleServerSync(); });
  document.getElementById('j5EmojiButton')?.addEventListener('click', () => {});
  window.j5Emoji = function (emoji) {
    const a = input.selectionStart, b = input.selectionEnd;
    input.setRangeText(emoji, a, b, 'end'); input.focus(); paint(); persistNow(); scheduleServerSync();
  };
  form.addEventListener('submit', async (event) => {
    if (form.dataset.recoverySubmitReady === '1') return;
    event.preventDefault();
    if (titleField && !titleField.value.trim()) syncTitles(todayTitle());
    if (bodyField) bodyField.value = input.value;
    persistNow();
    clearTimeout(timer);
    input.readOnly = true;
    if (titleMain) titleMain.readOnly = true;
    if (titleSide) titleSide.readOnly = true;
    if (navigator.onLine && input.value.trim()) {
      setStatus('Finishing your journal save…');
      // Avoid racing the background autosave and accidentally creating two pages.
      const waitUntil = Date.now() + 8000;
      while (syncing && Date.now() < waitUntil) await new Promise(resolve => setTimeout(resolve, 50));
      await serverSync(true);
    } else if (!navigator.onLine) setStatus('Device backup saved · server save will retry when online');
    // Keep the local recovery copy even after the form save. The server has to confirm
    // an exact match before an obsolete legacy backup can be retired.
    form.dataset.recoverySubmitReady = '1';
    form.submit();
  });
  window.addEventListener('pagehide', () => { persistNow(); if (navigator.onLine) void serverSync(true); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') { persistNow(); if (navigator.onLine) void serverSync(true); } });
  window.addEventListener('online', () => { setStatus('Back online · syncing recovery copy…'); scheduleServerSync(150); void syncOfflineWorkspaceRows(); });
  window.addEventListener('offline', () => setStatus('Offline · backup saved on this device'));
  void restoreDraftIfNeeded().finally(() => { paint(); });
  window.addEventListener('load', () => { window.setTimeout(() => void syncOfflineWorkspaceRows(), 600); });
})();

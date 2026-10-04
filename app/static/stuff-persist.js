(function(){
  const DB='open-road-my-stuff-v2', VER=1, STORES=['journals','copies','cards'];
  function openDB(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB,VER);r.onupgradeneeded=()=>{for(const n of STORES){if(!r.result.objectStoreNames.contains(n))r.result.createObjectStore(n,{keyPath:'id'})}};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
  const reqP=req=>new Promise((resolve,reject)=>{req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)});
  const txP=tx=>new Promise((resolve,reject)=>{tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('IndexedDB transaction aborted'))});
  async function seed(snapshot){try{if(navigator.storage?.persist)await navigator.storage.persist();const db=await openDB();for(const name of STORES){const tx=db.transaction(name,'readwrite');const store=tx.objectStore(name);const keys=await reqP(store.getAllKeys());for(const key of keys){if(!(typeof key==='string'&&key.startsWith('local-')))store.delete(key)}for(const row of (snapshot?.[name]||[]))store.put(row);await txP(tx)}db.close();return true}catch(e){return false}}
  window.OpenRoadStuffOffline={seed};
  window.addEventListener('load',()=>{if(window.__OR_STUFF_SNAPSHOT__)seed(window.__OR_STUFF_SNAPSHOT__)})
})();

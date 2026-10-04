OPEN ROAD — INSTALLABLE MINI-APPS + DURABLE OFFLINE UPDATE

This revision makes several Open Road doors independently installable as PWAs even when the main Open Road app is already installed. Each mini-app has its own manifest identity (id) and its own launch page:
- My Stuff
- My Story
- My Cards
- My Saves
- Find Me Anything
- Jobs
- Invoices & Receipts
- Ticketing

The website now exposes one root service worker instead of overlapping scoped service workers. The worker keeps public shells available offline and routes My Stuff offline requests into the local offline workspace. My Stuff data is also synchronized into browser IndexedDB and requests persistent browser storage when supported. Local offline drafts are preserved while server snapshots refresh.

Find Me Anything now ranks local/country-relevant results first (Kenya sources: Jumia, PigiaMe, Kilimall and Jiji), then international sources. Cached discovery remains usable when a live connector is slow or unavailable. Jobs show Open Road community posts first and collect external job leads into the Open Road UI before offering source links underneath.

Privacy/access analytics continue to record account phone when the visitor is signed in, plus a generated device/browser identifier. Coordinates are recorded only after the browser location permission is actively granted.

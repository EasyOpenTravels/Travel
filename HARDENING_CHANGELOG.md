# Easy Travels / OTravel hardening changelog — 16 October 2026

## Journal reliability

- Immediate localStorage draft capture while typing, on visibility changes, and before leaving the page.
- Independent IndexedDB recovery copy, with the browser asked to keep storage persistent where supported.
- Server autosave while online, with retries on reconnection and no private journal response caching.
- The Save page action waits for the background save to settle and keeps the local backup; old one-slot backups are retired only after a matching server acknowledgement.
- Recovery of legacy drafts and synchronisation of offline journal edits.
- Private JSON backup and merge-restore endpoints; the offline journal can download its local backup including unsynced recovery drafts.
- Service-worker cache version bumped so the new recovery code reaches clients.

## Validation performed

Python syntax compilation and Node JavaScript syntax checks passed for the changed files. A full Flask request/integration test could not be run in the editing environment because Flask is not installed there and package downloads were unavailable. Render will install dependencies from `requirements.txt` during deployment.

## Important limitation

Browser storage is a recovery layer, not a substitute for durable server storage. The default server database is SQLite at `instance/adventures.sqlite3` and must be placed on persistent storage for production use; see `DEPLOYMENT_EASY_TRAVELS.md`.

OPEN ROAD ADVENTURES — STABILITY / BACKUP / SYSTEM ERRORS FIX

This build fixes a class of failures where the shared visitor analytics hook could throw a database error before a sidebar destination was rendered. Analytics is now best-effort and self-healing, so a missing/old access_logs table cannot break normal pages.

Database safety
- The bundled database was normalized to the current schema and integrity-checked.
- The canonical schema now contains the system error log and current billing/My Stuff/access tables.
- Restores accept the new Open Road ZIP backup and legacy .sqlite3/.db/.sqlite backups.
- New backups use SQLite's online backup API rather than copying a possibly-live WAL database.
- New ZIP backups contain database.sqlite3, manifest.json, and the uploads folder when present.
- Every restore is integrity-checked and upgraded before activation.
- A persistent pre-restore SQLite safety snapshot is kept in instance/backups/ (latest five retained).

System errors
- Admin now has a System errors page.
- Unhandled server exceptions, 404s, browser JavaScript errors, failed connector operations, payment-boundary failures, and important caught application exceptions are recorded.
- Technical details include time, route, method, error type, message, traceback/context, user ID when available, visitor ID, IP, and browser string.
- The error page lets the admin mark records resolved and clear resolved records.
- If the database itself cannot accept an error record, the recorder falls back to instance/system-errors.log without breaking the request.

Restore file selection now accepts .zip, .sqlite3, .db and .sqlite.

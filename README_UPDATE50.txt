Version 50
- Robust live SQLite backups use the SQLite online backup API, not file copying.
- Backup includes integrity-checked database, manifest, and uploads.
- Restore validates schema/integrity and makes an automatic pre-restore SQLite safety copy.
- Service worker never caches /sw.js; one-time client reset clears stale PWA caches on build 50.
- Client error records include source, line, and column where supplied.

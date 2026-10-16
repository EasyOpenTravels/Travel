# Easy Travels / OTravel deployment notes

## Recommended address

Use `travel.trorinovationstech.co.ke` for the travel service. The Discovery Hub currently links the service to `otravel-bleg.onrender.com`.

## Cloudflare + Render custom domain

1. In the Render dashboard, open the existing OTravel web service (`otravel-bleg`) and add `travel.trorinovationstech.co.ke` under **Settings → Custom Domains**.
2. In Cloudflare DNS, add a `CNAME` record:
   - **Name:** `travel`
   - **Target:** `otravel-bleg.onrender.com`
   - **Proxy status:** `DNS only` (grey cloud) while Render verifies the domain and issues HTTPS.
3. Return to Render and verify the custom domain. Once its certificate is active, the Cloudflare record may be changed to Proxied if desired.
4. Do not create an `A` record for `travel`, and remove any conflicting `AAAA` record for that hostname.

## Journal recovery changes

The My Story editor now has layered recovery:

- Immediate localStorage draft writes on typing and page-hide/visibility changes.
- A separate IndexedDB recovery copy.
- Server-side autosave while online, tied to the current private workspace.
- Recovery from the online editor into the offline My Stuff journal.
- Offline editor draft saves without requiring the user to press Save memory.
- Offline-created or edited stories are synchronized when a matching workspace is online again.
- A private JSON download of all server-saved journal entries at **Download journal backup**.

## Changing to the new subdomain

Browser storage belongs to the exact origin (hostname + scheme). It does not automatically move from `otravel-bleg.onrender.com` to `travel.trorinovationstech.co.ke`. Before switching, download **Download journal backup** and, while in the offline journal, **Download local backup**. After opening the new subdomain, choose **Restore from backup** and select the downloaded JSON file. Restore merges pages and skips exact duplicates; it does not replace existing pages.

## Important: production database durability

This project uses SQLite and defaults to `instance/adventures.sqlite3`. Render web services have an ephemeral filesystem by default; on Render Free, local SQLite changes can be lost when the service spins down, restarts, or redeploys. Browser-side recovery cannot prevent a server database from being erased. For production journal data, use a persistent database. Options are a paid Render web service with a persistent disk mounted at `/var/data` and `DATABASE_PATH=/var/data/adventures.sqlite3`, or migrate the application to a managed PostgreSQL database. A Free Render web service cannot attach a persistent disk.

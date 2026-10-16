# Open Road Adventures

Mobile-first adventure booking portal for Kenyan road trips, retreats and experiences.

## Render
Build command:
`pip install -r requirements.txt`

Start command:
`gunicorn app:app`

Set only these owner credentials in Render:
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Optional:
- `BRAND_NAME`
- `ADMIN_PATH`

The owner entrance defaults to `/promise212324`.

Public visitors can browse without an account. An Adventure ID is requested only when someone is ready to unlock booking/payment details.

## Easy Travels journal durability update

See [`DEPLOYMENT_EASY_TRAVELS.md`](DEPLOYMENT_EASY_TRAVELS.md) for the recommended `travel.trorinovationstech.co.ke` custom domain, Cloudflare/Render DNS steps, journal recovery behavior, backup/restore steps, and the required production database durability configuration. Browser-local storage protects recovery drafts but does not replace a persistent server database.

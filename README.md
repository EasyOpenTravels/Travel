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

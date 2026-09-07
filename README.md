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


## Event Ticketing (self-serve)
Event Ticketing is intentionally separate from ordinary Travel Tickets. A normal travel ticket belongs to a `booking -> trip`; an event ticket belongs to an organizer-owned `event_ticket_events` record.

The flow is:
1. A user opens **Event Ticketing** and chooses **Host an event ticket** or **Find an event ticket**.
2. A host creates an event, price, payment instructions, optional cover image, and a separate 4–8 digit **Scanner PIN**.
3. Guests pay the event holder directly, paste the transaction/reference code, and the system creates a signed ticket record immediately.
4. The ticket remains **locked** until the event host or Open Road admin approves the payment.
5. Once approved, the attendee can choose among three ticket designs and download a PDF containing the same signed QR.
6. The event host opens **Scan event QR**, enters the Scanner PIN once for that event, and can scan tickets from the event scanner page.
7. A successful scan changes the ticket from `valid` to `used` in a transaction, so the same QR cannot be reused.

The QR is not trusted because of the PDF image. It is verified server-side against the platform HMAC signature and ticket state, so changing the visible name/code/design in a downloaded file does not make an altered QR valid.

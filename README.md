# Travel / Event Ticketing / Group Retreats

This build includes three distinct experiences:

- **Travel tickets** remain the normal travel booking flow.
- **Event Ticketing** lets event owners create Regular/VIP/VVIP tickets, approve payment submissions, generate secure QR tickets, create VIP/VVIP joint passes, and use a separate staff scanner.
- **Group Retreats** lets a leader propose a group plan for 5+ people, suggest a destination/activity/date/price, receive system-admin approval, add members or let members join by Group ID, approve payments, issue individual QR passes and a joint receipt.

Completed event and group records are automatically removed after a 30-day grace period once their dates are past. System admin can also delete group plans directly.

System admin backups are exported as a ZIP containing the SQLite database and uploaded media, and the same ZIP can be restored.

## Automated payment boundary

Payments are deliberately separated from tickets/bookings. The application creates a payment intent and, when configured, starts an M-Pesa STK request. Only the provider callback is allowed to mark a payment paid; the ticket/booking layer consumes that confirmed result. Provider credentials are environment secrets. The platform Till and ticketing fee percentage are stored through the protected admin settings page.

For a production Till checkout, set `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_PASSKEY`, `MPESA_BUSINESS_SHORTCODE` (use the merchant shortcode required by the provisioned Daraja product), `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline`, and a strong `MPESA_CALLBACK_TOKEN`. Automated checkout will remain disabled until the complete secret set is present. Register the resulting callback endpoint shown by the deployment with the payment provider. Never commit these secrets to GitHub.

The payment adapter follows Safaricom Daraja's documented M-Pesa integration model. Business Buy Goods and Customer To Business APIs are available in Daraja 3.0. Till/STK behavior depends on the merchant configuration provisioned for the account, so the credentials and shortcode/till relationship must match the live account.

"""Payment boundary for the platform.

The ticket/booking system never talks to M-Pesa directly.  This module is the
payment boundary: it creates a payment intent, calls the configured provider,
and consumes the provider callback before a product is marked paid.
"""
import base64, hashlib, json, os, re, secrets
from datetime import datetime, timezone
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from flask import current_app, request, url_for

from .db import get_db
from .security import now, decrypt_secret


def _setting(key, default=''):
    row = get_db().execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default

def _secret(key, env_key=None, default=''):
    stored = _setting(key, '')
    if stored:
        plain = decrypt_secret(stored)
        if plain:
            return plain
    return os.environ.get(env_key or key, default)


def _normalise_phone(value):
    value = re.sub(r'\D+', '', str(value or ''))
    if value.startswith('0') and len(value) == 10:
        value = '254' + value[1:]
    elif value.startswith('7') and len(value) == 9:
        value = '254' + value
    elif value.startswith('254') and len(value) == 12:
        pass
    else:
        raise ValueError('Enter a valid Kenyan M-Pesa number.')
    if not re.fullmatch(r'2547\d{8}', value):
        raise ValueError('Enter a valid Kenyan M-Pesa number.')
    return value


def _mpesa_base():
    return os.environ.get('MPESA_API_BASE', 'https://api.safaricom.co.ke').rstrip('/')


def mpesa_configured():
    return bool(_secret('mpesa_consumer_key','MPESA_CONSUMER_KEY') and _secret('mpesa_consumer_secret','MPESA_CONSUMER_SECRET') and _secret('mpesa_passkey','MPESA_PASSKEY') and _secret('mpesa_callback_token','MPESA_CALLBACK_TOKEN') and _setting('payment_till'))


def payment_callback_url():
    token = _secret('mpesa_callback_token','MPESA_CALLBACK_TOKEN').strip()
    if not token:
        # Production should set MPESA_CALLBACK_TOKEN so the registered callback is stable.
        token = current_app.config.get('MPESA_CALLBACK_TOKEN', '')
    path = f'/payments/mpesa/callback/{token}' if token else '/payments/mpesa/callback'
    return url_for('public.mpesa_callback', token=token, _external=True) if token else url_for('public.mpesa_callback_open', _external=True)


def _post_json(url, payload, headers=None, timeout=20):
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(url, data=data, headers={'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body or '{}')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Payment provider HTTP {exc.code}: {body[:500]}') from exc
    except URLError as exc:
        raise RuntimeError(f'Payment provider connection failed: {exc.reason}') from exc


def _mpesa_access_token():
    key = _secret('mpesa_consumer_key','MPESA_CONSUMER_KEY')
    secret = _secret('mpesa_consumer_secret','MPESA_CONSUMER_SECRET')
    if not key or not secret:
        raise RuntimeError('M-Pesa API credentials are not configured on the server.')
    raw = base64.b64encode(f'{key}:{secret}'.encode()).decode()
    req = urlrequest.Request(
        f'{_mpesa_base()}/oauth/v1/generate?grant_type=client_credentials',
        headers={'Authorization': f'Basic {raw}', 'Accept': 'application/json'},
        method='GET',
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8') or '{}')
    except (HTTPError, URLError) as exc:
        raise RuntimeError('Could not authenticate with the M-Pesa API.') from exc
    token = payload.get('access_token')
    if not token:
        raise RuntimeError('M-Pesa did not return an access token.')
    return token


def _timestamp():
    return datetime.now(timezone.utc).astimezone().strftime('%Y%m%d%H%M%S')


def _stk_push(phone, amount, reference, description):
    till = _setting('payment_till', '')
    shortcode = _setting('payment_business_shortcode', '').strip() or os.environ.get('MPESA_BUSINESS_SHORTCODE', '').strip() or till
    if not till:
        raise RuntimeError('No platform M-Pesa Till has been configured.')
    passkey = _secret('mpesa_passkey','MPESA_PASSKEY')
    ts = _timestamp()
    password = base64.b64encode(f'{shortcode}{passkey}{ts}'.encode()).decode()
    callback = payment_callback_url()
    payload = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': ts,
        'TransactionType': os.environ.get('MPESA_TRANSACTION_TYPE', 'CustomerBuyGoodsOnline'),
        'Amount': int(amount),
        'PartyA': phone,
        'PartyB': till,
        'PhoneNumber': phone,
        'CallBackURL': callback,
        'AccountReference': reference[:12],
        'TransactionDesc': description[:13] or 'Payment',
    }
    token = _mpesa_access_token()
    response = _post_json(
        f'{_mpesa_base()}/mpesa/stkpush/v1/processrequest',
        payload,
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
    )
    if str(response.get('ResponseCode', '0')) not in {'0', '00'} and not response.get('CheckoutRequestID'):
        raise RuntimeError(response.get('ResponseDescription') or response.get('errorMessage') or 'M-Pesa rejected the payment request.')
    return response


def create_payment_intent(*, kind, target_id, amount, phone, event_id=None, metadata=None, fee_percent=0):
    amount = int(amount)
    if amount <= 0:
        raise ValueError('Payment amount must be greater than zero.')
    phone = _normalise_phone(phone)
    reference = 'PAY-' + secrets.token_urlsafe(18).replace('-', '').replace('_', '').upper()[:22]
    db = get_db()
    fee_percent = max(0.0, min(100.0, float(fee_percent or 0)))
    fee = int(round(amount * fee_percent / 100.0))
    net = amount - fee
    cur = db.execute(
        """INSERT INTO payment_intents
        (reference,kind,target_id,event_id,phone,amount,currency,provider,status,fee_percent,platform_fee,net_amount,metadata_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (reference, kind, int(target_id), event_id, phone, amount, 'KES', 'mpesa', 'created', fee_percent, fee, net, json.dumps(metadata or {}, separators=(',', ':')), now(), now())
    )
    db.commit()
    return db.execute('SELECT * FROM payment_intents WHERE id=?', (cur.lastrowid,)).fetchone()


def start_payment(intent):
    if not mpesa_configured():
        raise RuntimeError('Automated M-Pesa checkout is not configured yet. Add the Daraja credentials to the server secrets and set the platform Till.')
    db = get_db()
    try:
        response = _stk_push(intent['phone'], intent['amount'], intent['reference'], f'{intent["kind"]} {intent["reference"]}')
        merchant_id = response.get('MerchantRequestID', '')
        checkout_id = response.get('CheckoutRequestID', '')
        db.execute(
            "UPDATE payment_intents SET status='pending',merchant_request_id=?,checkout_request_id=?,provider_response_json=?,updated_at=? WHERE id=?",
            (merchant_id, checkout_id, json.dumps(response, separators=(',', ':')), now(), intent['id'])
        )
        db.commit()
        return db.execute('SELECT * FROM payment_intents WHERE id=?', (intent['id'],)).fetchone()
    except Exception as exc:
        db.execute("UPDATE payment_intents SET status='failed',result_desc=?,updated_at=? WHERE id=?", (str(exc)[:500], now(), intent['id']))
        db.commit()
        raise


def _callback_values(payload):
    # STK callback shape.
    stk = (((payload or {}).get('Body') or {}).get('stkCallback') or {})
    if stk:
        items = {}
        for item in (stk.get('CallbackMetadata') or {}).get('Item') or []:
            if item.get('Name'):
                items[item['Name']] = item.get('Value')
        return {
            'merchant_request_id': stk.get('MerchantRequestID', ''),
            'checkout_request_id': stk.get('CheckoutRequestID', ''),
            'result_code': str(stk.get('ResultCode', '')),
            'result_desc': stk.get('ResultDesc', ''),
            'provider_transaction_id': items.get('MpesaReceiptNumber', ''),
            'amount': items.get('Amount'),
            'phone': items.get('PhoneNumber', ''),
            'raw': payload,
        }
    # C2B confirmation-style callback.
    return {
        'merchant_request_id': '',
        'checkout_request_id': '',
        'result_code': '0',
        'result_desc': 'C2B confirmation',
        'provider_transaction_id': payload.get('TransID', ''),
        'amount': payload.get('TransAmount'),
        'phone': payload.get('MSISDN', ''),
        'bill_ref': payload.get('BillRefNumber', ''),
        'raw': payload,
    }


def _mark_paid(intent, values):
    db = get_db()
    # Reconcile only on the immutable transaction identifiers/amount.
    expected_amount = int(intent['amount'])
    received_amount = int(float(values.get('amount') or 0))
    if received_amount != expected_amount:
        db.execute("UPDATE payment_intents SET status='failed',result_code='AMOUNT_MISMATCH',result_desc=?,updated_at=? WHERE id=? AND status!='paid'", (f'Expected KES {expected_amount}, received KES {received_amount}.', now(), intent['id']))
        db.commit()
        return False
    provider_tx = str(values.get('provider_transaction_id') or '').strip()
    if provider_tx:
        duplicate = db.execute('SELECT id FROM payment_intents WHERE provider_transaction_id=? AND id<>?', (provider_tx, intent['id'])).fetchone()
        if duplicate:
            return False
    # Mark the payment before issuing the product, inside one DB transaction.
    db.execute('BEGIN IMMEDIATE')
    try:
        current = db.execute('SELECT * FROM payment_intents WHERE id=?', (intent['id'],)).fetchone()
        if current['status'] == 'paid':
            db.commit(); return True
        db.execute(
            """UPDATE payment_intents SET status='paid',provider_transaction_id=?,result_code=?,result_desc=?,paid_at=?,updated_at=? WHERE id=? AND status!='paid'""",
            (provider_tx or None, str(values.get('result_code') or '0'), str(values.get('result_desc') or '')[:500], now(), now(), intent['id'])
        )
        if intent['kind'] == 'event_ticket':
            db.execute("UPDATE event_tickets SET payment_status='verified',approval_status='approved',approved_at=? WHERE id=? AND approval_status IN ('pending','reversed')", (now(), intent['target_id']))
        elif intent['kind'] == 'trip_booking':
            db.execute("UPDATE bookings SET payment_status='paid',paid_at=? WHERE id=?", (now(), intent['target_id']))
        elif intent['kind'] == 'group_member':
            db.execute("UPDATE group_members SET payment_status='approved' WHERE id=?", (intent['target_id'],))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def handle_mpesa_callback(payload):
    values = _callback_values(payload)
    db = get_db()
    intent = None
    if values.get('checkout_request_id'):
        intent = db.execute('SELECT * FROM payment_intents WHERE checkout_request_id=?', (values['checkout_request_id'],)).fetchone()
    if not intent and values.get('merchant_request_id'):
        intent = db.execute('SELECT * FROM payment_intents WHERE merchant_request_id=?', (values['merchant_request_id'],)).fetchone()
    if not intent and values.get('bill_ref'):
        ref = str(values['bill_ref']).strip().upper()
        intent = db.execute('SELECT * FROM payment_intents WHERE reference=? OR reference LIKE ?', (ref, ref + '%')).fetchone()
    if not intent:
        return {'ok': False, 'matched': False}
    code = str(values.get('result_code') or '')
    if code not in {'0', '00'}:
        db.execute("UPDATE payment_intents SET status='failed',result_code=?,result_desc=?,provider_response_json=?,updated_at=? WHERE id=? AND status!='paid'", (code, str(values.get('result_desc') or '')[:500], json.dumps(values.get('raw') or {}, separators=(',', ':')), now(), intent['id']))
        db.commit()
        return {'ok': True, 'matched': True, 'paid': False}
    paid = _mark_paid(intent, values)
    return {'ok': paid, 'matched': True, 'paid': paid}

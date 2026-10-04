import io
import qrcode

def make_qr_bytes(data):
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(data); qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    out = io.BytesIO(); image.save(out, format='PNG'); return out.getvalue()

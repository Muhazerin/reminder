"""Web Push (RFC 8030) helpers. VAPID keys are generated once and stored in
DATA_DIR/vapid.pem; the public key is served to the PWA so it can subscribe."""
import base64
import json
import logging
import os

from . import db

log = logging.getLogger("push")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _import_serialization():
    from cryptography.hazmat.primitives import serialization
    return serialization


def load_or_create_vapid():
    """Returns (private_key_pem: str, public_key_b64url: str)."""
    os.makedirs(db.DATA_DIR, exist_ok=True)
    path = os.path.join(db.DATA_DIR, "vapid.pem")
    if not os.path.exists(path):
        from cryptography.hazmat.primitives.asymmetric import ec

        pk = ec.generate_private_key(ec.SECP256R1())
        ser = _import_serialization()
        pem = pk.private_bytes(
            ser.Encoding.PEM,
            ser.PrivateFormat.PKCS8,
            ser.NoEncryption(),
        )
        with open(path, "wb") as f:
            f.write(pem)
        log.info("generated new VAPID keys at %s", path)
    with open(path, "rb") as f:
        pem = f.read()
    ser = _import_serialization()
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ser.load_pem_private_key(pem, password=None)
    pub = key.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
    return pem.decode(), _b64url(pub)


def public_key_b64() -> str:
    _, pub = load_or_create_vapid()
    return pub


def _subject() -> str:
    return os.environ.get("VAPID_MAILTO", "mailto:admin@example.com")


def send_all(devices: list, payload: dict):
    """Send payload to every device. Dead subscriptions (404/410) are dropped."""
    if not devices:
        return
    priv_pem, _ = load_or_create_vapid()
    import pywebpush

    for dev in devices:
        sub = {
            "endpoint": dev["endpoint"],
            "keys": {"p256dh": dev["p256dh"], "auth": dev["auth_secret"]},
        }
        try:
            pywebpush.WebPusher(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=priv_pem,
                vapid_claims={"sub": _subject()},
            ).send()
        except pywebpush.WebPushException as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code in (404, 410):
                db.remove_device(dev["endpoint"])
                log.info("removed dead subscription")
            else:
                log.warning("push failed: %s", e)
        except Exception:
            log.exception("push send error")

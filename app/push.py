"""Web Push (RFC 8030) helpers. VAPID keys are generated once and stored in
DATA_DIR/vapid.pem; the public key is served to the PWA so it can subscribe.

Vocabulary: see docs/glossary.md — a *device* holds a push *subscription*
(endpoint + encryption keys, field names follow the browser's PushSubscription
wire format and are kept as-is)."""
import base64
import json
import logging
import os

from . import db

log = logging.getLogger("push")


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding — the format VAPID keys travel in."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _import_serialization():
    """Import cryptography's serialization module lazily (kept out of import time)."""
    from cryptography.hazmat.primitives import serialization
    return serialization


def load_or_create_vapid():
    """Returns (private_key_pem: str, public_key_b64url: str)."""
    os.makedirs(db.DATA_DIR, exist_ok=True)
    path = os.path.join(db.DATA_DIR, "vapid.pem")
    ser = _import_serialization()
    if not os.path.exists(path):
        from cryptography.hazmat.primitives.asymmetric import ec

        pk = ec.generate_private_key(ec.SECP256R1())
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
    key = ser.load_pem_private_key(pem, password=None)
    pub = key.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
    return pem.decode(), _b64url(pub)


def vapid_public_key() -> str:
    """The public half of the VAPID keypair, URL-safe base64 (served to the PWA)."""
    _, pub = load_or_create_vapid()
    return pub


def _subject() -> str:
    """The VAPID "sub" claim: a contact address the push service can reach you at."""
    return os.environ.get("VAPID_MAILTO", "mailto:admin@example.com")


def notify_devices(devices: list, notification: dict):
    """Send a notification to every device. Dead subscriptions (404/410 from the
    push service) are pruned automatically."""
    if not devices:
        return
    priv_pem, _ = load_or_create_vapid()
    import pywebpush

    for device in devices:
        sub = {
            "endpoint": device["endpoint"],
            "keys": {"p256dh": device["p256dh"], "auth": device["auth_secret"]},
        }
        try:
            pywebpush.WebPusher(
                subscription_info=sub,
                data=json.dumps(notification),
                vapid_private_key=priv_pem,
                vapid_claims={"sub": _subject()},
            ).send()
        except pywebpush.WebPushException as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code in (404, 410):
                db.delete_device(device["endpoint"])
                log.info("removed dead subscription")
            else:
                log.warning("push failed: %s", e)
        except Exception:
            log.exception("push send error")

import base64
import hashlib
import hmac
import os
import time

import jwt

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, h = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")


def make_token(user_id, secret, ttl):
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + ttl}, secret, algorithm="HS256")


def read_token(token, secret):
    """Return user id or None."""
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return data["sub"]
    except jwt.PyJWTError:
        return None

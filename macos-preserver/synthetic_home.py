"""Build-time-only inert PlayCover fixture. Never bundled in the app."""
import base64
import json
from pathlib import Path
import plistlib
import sqlite3
import time

BUNDLE = "game.qualiarts.idolypride"
APP = "1:543065248020:ios:babf05d967621a37ab3201"


def create(home: Path):
    """Require a new, dedicated synthetic HOME; never inspect the real HOME."""
    home.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = home / "Library/Containers/io.playcover.PlayCover"
    settings, database = root / "App Settings", root / "PlayChain"
    settings.mkdir(parents=True)
    database.mkdir()
    (settings / (BUNDLE + ".plist")).write_bytes(plistlib.dumps({"playChain": True}))
    now = int(time.time())
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    token = ".".join((enc({"alg": "RS256", "typ": "JWT", "kid": "synthetic-only"}),
        enc({"sub": "SYNTHETIC_INERT_USER", "aud": "solis-firebase",
             "iss": "https://securetoken.google.com/solis-firebase", "iat": now - 100,
             "exp": now + 3500, "auth_time": now - 101}),
        base64.urlsafe_b64encode(b"synthetic-not-a-signature-12345678").decode().rstrip("=")))
    objects = ["$null"]
    def add(value):
        objects.append(value)
        return plistlib.UID(len(objects) - 1)
    def cls(name):
        return add({"$classname": name, "$classes": [name, "NSObject"]})
    user_class, service_class, date_class = cls("FIRUser"), cls("FIRSecureTokenService"), cls("NSDate")
    service = add({"$class": service_class, "accessToken": add(token),
        "refreshToken": add("SYNTHETIC_INERT_REFRESH_DO_NOT_USE"),
        "APIKey": add("SYNTHETIC_INERT_API_KEY"),
        "accessTokenExpirationDate": add({"$class": date_class, "NS.time": float(now + 3500 - 978307200)})})
    user = add({"$class": user_class, "userID": add("SYNTHETIC_INERT_USER"),
        "firebaseAppID": add(APP), "APIKey": add("SYNTHETIC_INERT_API_KEY"),
        "tokenService": service, "tenantID": plistlib.UID(0)})
    raw = plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
        "$objects": objects, "$top": {"root": user}}, fmt=plistlib.FMT_BINARY)
    with sqlite3.connect(database / (BUNDLE + ".db")) as db:
        db.execute('CREATE TABLE genp (agrp TEXT, acct TEXT, svce TEXT, v_Data BLOB)')
        db.execute('INSERT INTO genp VALUES (?, ?, ?, ?)', ("synthetic-only",
            "firebase_auth_1___FIRAPP_DEFAULT_firebase_user", "firebase_auth_" + APP, raw))
    return home

import logging
import os

import valkey
from flask import Flask, Response, abort

VALKEY_URL = os.environ.get("VALKEY_URL", "valkey://localhost:6379")

api = Flask(__name__)
valkey_pool = valkey.ConnectionPool.from_url(VALKEY_URL)


def get_valkey_client():
    return valkey.Valkey(connection_pool=valkey_pool)


def sanitize(s):
    return s.strip().lower()


@api.route("/.well-known/openpgpkey/hu/<wkd_hash>", methods=["GET"])
@api.route("/.well-known/openpgpkey/<domain>/hu/<wkd_hash>", methods=["GET"])
def serve_wkd_key(wkd_hash, domain=None):
    if domain is None:
        try:
            domain = os.environ["VALKEY_URL"]
        excpet KeyError:
            abort(404)
    try:
        db = get_valkey_client()
        key_bytes = db.get(f"wkd:{sanitize(domain)}:hu:{sanitize(wkd_hash)}")
        if not key_bytes:
            abort(404)
        return Response(
            key_bytes,
            mimetype="application/octet-stream",
        )
    except valkey.exceptions.ConnectionError as e:
        api.logger.error(f"Connection failed to valkey server: {e}")
        abort(503)


if __name__ == "__main__":
    api.run(host="127.0.0.1", port=8000, debug=True)
else:
    gunicorn_logger = logging.getLogger("gunicorn.error")
    api.logger.handlers = gunicorn_logger.handlers
    api.logger.setLevel(gunicorn_logger.level)

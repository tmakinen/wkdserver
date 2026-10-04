import logging
import os

import valkey
from flask import Flask, Response, abort, send_file

VALKEY_URL = os.environ.get("VALKEY_URL", "valkey://localhost:6379")
DEFAULT_HTML_CONTENT = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Web Key Directory</title>
    <style>
        body { font-family: monospace; max-width: 650px; margin: 40px auto; padding: 20px; line-height: 1.5; color: #333; }
        pre { background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }
        .status { color: #2e7d32; }
    </style>
</head>
<body>
    <h2>Web Key Directory (WKD)</h2>
    <p>Status: <span class="status">Online</span></p>
    <p>This service distributes public OpenPGP keys for this domain directly to email clients.</p>

    <p>To manually locate and import a key via the command line, use:</p>
    <pre>gpg --auto-key-locate wkd --locate-keys user@example.com</pre>
</body>
</html>
"""


api = Flask(__name__)
valkey_pool = valkey.ConnectionPool.from_url(VALKEY_URL)


def get_valkey_client():
    return valkey.Valkey(connection_pool=valkey_pool)


def sanitize(s):
    return s.strip().lower()


@api.route("/", methods=["GET"])
def serve_index():
    html = os.environ.get("CUSTOM_HTML", None)
    if html is None:
        return Response(DEFAULT_HTML_CONTENT, mimetype="text/html")
    elif not os.path.exists(html):
        api.logger.error(f"Cannot find custom landing page {html}")
        abort(500)
    else:
        return send_file(html)


@api.route("/.well-known/openpgpkey/hu/<wkd_hash>", methods=["GET"])
@api.route("/.well-known/openpgpkey/<domain>/hu/<wkd_hash>", methods=["GET"])
def serve_wkd_key(wkd_hash, domain=None):
    if domain is None:
        try:
            domain = os.environ["VALKEY_URL"]
        except KeyError:
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

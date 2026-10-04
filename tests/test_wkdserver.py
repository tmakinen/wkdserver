import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"


def load_module(monkeypatch, *, default_domain=None, custom_html=None):
    fake_valkey = types.ModuleType("valkey")
    fake_valkey.exceptions = types.SimpleNamespace(ConnectionError=RuntimeError)

    class FakeConnectionPool:
        @staticmethod
        def from_url(value):
            return {"value": value}

    class FakeValkey:
        store = {}

        def __init__(self, connection_pool=None):
            self.connection_pool = connection_pool

        def get(self, key):
            return type(self).store.get(key)

    fake_valkey.ConnectionPool = FakeConnectionPool
    fake_valkey.Valkey = FakeValkey

    monkeypatch.setitem(sys.modules, "valkey", fake_valkey)
    monkeypatch.delenv("VALKEY_URL", raising=False)

    if custom_html is None:
        monkeypatch.delenv("CUSTOM_HTML", raising=False)
    else:
        monkeypatch.setenv("CUSTOM_HTML", custom_html)

    if default_domain is None:
        monkeypatch.delenv("DEFAULT_DOMAIN", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_DOMAIN", default_domain)

    sys.modules.pop("wkdserver", None)
    spec = importlib.util.spec_from_file_location("wkdserver", WEB_DIR / "wkdserver.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wkdserver"] = module
    spec.loader.exec_module(module)
    return module


def test_serve_index_renders_default_html(monkeypatch):
    module = load_module(monkeypatch)
    response = module.api.test_client().get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Web Key Directory" in response.get_data(as_text=True)


def test_serve_index_returns_500_for_missing_custom_html(monkeypatch):
    module = load_module(monkeypatch, custom_html=str(WEB_DIR / "missing.html"))
    response = module.api.test_client().get("/")

    assert response.status_code == 500


def test_serve_wkd_key_returns_key_for_advanced_route(monkeypatch):
    module = load_module(monkeypatch)
    module.valkey.Valkey.store = {"wkd:example.com:hu:abcd": b"secret-key"}
    response = module.api.test_client().get("/.well-known/openpgpkey/example.com/hu/abcd")

    assert response.status_code == 200
    assert response.mimetype == "application/octet-stream"
    assert response.data == b"secret-key"


def test_serve_wkd_key_uses_default_domain_for_direct_route(monkeypatch):
    module = load_module(monkeypatch, default_domain="example.com")
    module.valkey.Valkey.store = {"wkd:example.com:hu:abcd": b"fallback-key"}
    response = module.api.test_client().get("/.well-known/openpgpkey/hu/abcd")

    assert response.status_code == 200
    assert response.mimetype == "application/octet-stream"
    assert response.data == b"fallback-key"

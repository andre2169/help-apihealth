from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from app.core.config import settings
from app.services.messaging.evolution import EvolutionDeliveryError, send_text_message


@pytest.fixture
def provider(monkeypatch):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.command, self.path, self.headers.get("apikey")))
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"key":{"id":"redirected"}}')

        def do_POST(self):
            calls.append((self.command, self.path, self.headers.get("apikey")))
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(self.server.status)
            if self.server.status != 200:
                self.send_header("Location", "/credential-capture")
            self.end_headers()
            self.wfile.write(b'{"key":{"id":"accepted"}}')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.status = 200
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "EVOLUTION_API_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "EVOLUTION_API_KEY", "test-only-provider-key")
    monkeypatch.setattr(settings, "EVOLUTION_INSTANCE", "test instance")
    monkeypatch.setattr(settings, "EVOLUTION_WEBHOOK_SECRET", "test-only-webhook-key")
    try:
        yield server, calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_provider_redirects_never_forward_api_key_or_recipient_data(provider, status):
    server, calls = provider
    server.status = status
    with pytest.raises(EvolutionDeliveryError, match=f"^provider_http_{status}$"):
        send_text_message(number="5571999998888", text="Test only")
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/message/sendText/test%20instance"


def test_provider_still_accepts_success_without_redirect(provider):
    _, calls = provider
    assert send_text_message(number="5571999998888", text="Test only") == "accepted"
    assert len(calls) == 1

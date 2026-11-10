"""Scene images: https only to public addresses (every hop, every connection), local files only from allowed folders.

All offline: lookups are stubbed and the only socket used is a listener on 127.0.0.1.
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_explainer_plugin import FakeVoice, _board, _tools, needs_ffmpeg  # noqa: E402

images = sys.modules["explainer_plugin_under_test.images"]
SlideError = sys.modules["explainer_plugin_under_test.slides"].SlideError


def _resolves_to(monkeypatch, mapping):
    def fake(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in mapping[host]]

    monkeypatch.setattr(images.socket, "getaddrinfo", fake)


@pytest.fixture
def no_connections(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(images.socket, "create_connection", refuse)


@pytest.mark.parametrize("address, public", [
    ("93.184.216.34", True), ("2606:4700:4700::1111", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False),
    ("::1", False), ("fe80::1", False), ("fc00::1", False), ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False),
])
def test_only_globally_routable_addresses_count_as_public(address, public):
    assert images.is_public(address) is public


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/a.png", "https://169.254.169.254/latest/meta-data/", "https://[::1]/a.png",
    "https://10.0.0.8:8443/a.png", "https://[fe80::1%25eth0]/a.png",
])
def test_private_literal_hosts_are_refused_before_connecting(url, no_connections):
    with pytest.raises(SlideError, match="non-public address"):
        images.load_image(url)


def test_a_name_that_resolves_to_a_private_address_is_refused(monkeypatch, no_connections):
    _resolves_to(monkeypatch, {"images.example.com": ["93.184.216.34", "192.168.0.10"]})
    with pytest.raises(SlideError, match="192.168.0.10"):
        images.load_image("https://images.example.com/cat.png")


def test_the_connected_peer_is_checked_so_dns_rebinding_cannot_reach_localhost():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        with pytest.raises(SlideError, match="non-public address"):
            images._connect_public(listener.getsockname(), timeout=5)
    finally:
        listener.close()


@pytest.mark.parametrize("target, message", [
    ("http://169.254.169.254/latest/meta-data/", "only https"),
    ("http://example.com/a.png", "only https"),
    ("https://127.0.0.1/a.png", "non-public address"),
    ("https://metadata.internal/a.png", "non-public address"),
    ("file:///etc/passwd", "only https"),
])
def test_every_redirect_hop_is_checked(monkeypatch, target, message, no_connections):
    _resolves_to(monkeypatch, {"metadata.internal": ["169.254.169.254"], "cdn.example.com": ["93.184.216.34"]})
    request = urllib.request.Request("https://cdn.example.com/a.png")
    with pytest.raises(SlideError, match=message):
        images._SafeRedirect().redirect_request(request, None, 302, "Found", {}, target)


def test_a_redirect_to_another_public_https_host_is_followed(monkeypatch):
    _resolves_to(monkeypatch, {"cdn2.example.com": ["93.184.216.35"]})
    request = urllib.request.Request("https://cdn.example.com/a.png")
    follow = images._SafeRedirect().redirect_request(request, None, 302, "Found", {}, "https://cdn2.example.com/b.png")
    assert follow.full_url == "https://cdn2.example.com/b.png"


def test_the_opener_checks_every_hop_and_ignores_proxy_settings(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    handlers = images._opener().handlers
    assert not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies for h in handlers)
    assert any(isinstance(h, images._PublicHTTPSHandler) for h in handlers)
    redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert redirects and all(isinstance(h, images._SafeRedirect) for h in redirects)
    https = [h for h in handlers if isinstance(h, urllib.request.HTTPSHandler)]
    assert https and all(isinstance(h, images._PublicHTTPSHandler) for h in https)


@pytest.mark.parametrize("source", ["http://example.com/a.png", "file:///etc/passwd", "ftp://x/a.png",
                                    "data:image/png;base64,AAAA"])
def test_other_url_schemes_are_refused(source, no_connections):
    with pytest.raises(SlideError, match="only https"):
        images.load_image(source)


def test_local_images_must_live_in_an_allowed_folder(tmp_path):
    from PIL import Image
    allowed, other = tmp_path / "allowed", tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    Image.new("RGB", (40, 30), "red").save(allowed / "pic.png")
    Image.new("RGB", (40, 30), "red").save(other / "secret.png")
    assert images.load_image(str(allowed / "pic.png"), [allowed]).size == (40, 30)
    assert images.load_image("pic.png", [allowed]).size == (40, 30)  # relative to the first root
    for escape in (str(other / "secret.png"), "../other/secret.png"):
        with pytest.raises(SlideError, match="outside the allowed folders"):
            images.load_image(escape, [allowed])
    with pytest.raises(SlideError, match="not allowed"):
        images.load_image(str(allowed / "pic.png"), [])


@needs_ffmpeg
def test_render_reads_local_images_only_from_allowed_folders(tmp_path):
    from PIL import Image
    elsewhere = tmp_path / "Pictures"
    elsewhere.mkdir()
    Image.new("RGB", (64, 48), "blue").save(elsewhere / "diagram.png")
    board = _board()
    board["scenes"][0]["image"] = str(elsewhere / "diagram.png")
    data = tmp_path / "data"
    refused = json.loads(_tools(data, FakeVoice()).render(board))
    assert refused["success"] and "outside the allowed folders" in refused["warnings"][0]
    allowed = json.loads(_tools(data, FakeVoice(), image_dirs=[str(elsewhere)]).render(board))
    assert allowed["success"] and "warnings" not in allowed

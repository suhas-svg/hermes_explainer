"""Load scene images safely: https URLs only to public addresses, local files only from allowed folders."""

from __future__ import annotations

import http.client
import io
import ipaddress
import socket
import ssl
import urllib.request
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlsplit

from .slides import SlideError, _pil

MAX_IMAGE_BYTES = 8 * 1024 * 1024
TIMEOUT = 20


def is_public(address: str) -> bool:
    """True for globally routable unicast addresses; False for loopback, RFC1918/ULA, link-local, CGNAT, etc."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _check_host(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise SlideError("only https:// image URLs are allowed")
    literal = unquote(parts.hostname)
    try:
        ipaddress.ip_address(literal.split("%", 1)[0])
    except ValueError:
        pass  # a name: check every address it resolves to
    else:
        if not is_public(literal):
            raise SlideError(f"refusing to fetch an image from a non-public address ({literal})")
        return
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SlideError(f"cannot resolve image host {parts.hostname}: {exc}") from exc
    for info in infos:
        if not is_public(info[4][0]):
            raise SlideError(f"refusing to fetch an image from {parts.hostname}: "
                             f"it resolves to a non-public address ({info[4][0]})")


def _connect_public(address, *args, **kwargs) -> socket.socket:
    """socket.create_connection that refuses a non-public peer before any TLS or HTTP bytes are sent.

    Checking the connected socket (not just an earlier lookup) also defeats DNS rebinding.
    """
    sock = socket.create_connection(address, *args, **kwargs)
    peer = sock.getpeername()[0]
    if not is_public(peer):
        sock.close()
        raise SlideError(f"refusing to fetch an image from a non-public address ({peer})")
    return sock


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must stay on https and point at a public address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # No proxies: the address checks must see the real destination.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _PublicHTTPSHandler(context=ssl.create_default_context()), _SafeRedirect())


def fetch(url: str) -> bytes:
    _check_host(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Explainer-Studio/1.0"})
    with _opener().open(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise SlideError(f"image larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return data


def local_path(source: str, roots: Sequence[Path]) -> Path:
    """Resolve a local image path; it must sit inside one of ``roots`` (relative paths resolve against the first)."""
    if not roots:
        raise SlideError("local images are not allowed here")
    resolved_roots = [Path(r).expanduser().resolve() for r in roots]
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = resolved_roots[0] / path
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in resolved_roots):
        raise SlideError(f"image {path} is outside the allowed folders "
                         f"({', '.join(str(r) for r in resolved_roots)}); copy it there or add its folder to image_dirs")
    if not path.is_file():
        raise SlideError(f"image not found: {path}")
    return path


def load_image(source: str, roots: Sequence[Path] = ()):
    """Open a scene image as EXIF-rotated RGB: an https URL on a public host, or a file inside ``roots``."""
    Image, _, _, ImageOps = _pil()
    scheme = urlsplit(source).scheme.lower()
    if scheme == "https":
        image = Image.open(io.BytesIO(fetch(source)))
    elif "://" in source or scheme in {"http", "file", "data", "ftp"}:
        raise SlideError("only https:// image URLs are allowed")
    else:
        image = Image.open(local_path(source, roots))
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB")

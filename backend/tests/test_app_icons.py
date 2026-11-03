"""The supplied Options artwork must be wired to opaque, correctly sized app icons."""

import json
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


class HeadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = {}

    def handle_starttag(self, tag, attrs):
        if tag == "link":
            values = dict(attrs)
            self.links[values["rel"]] = values


def png_info(name):
    data = (FRONTEND / "public" / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    width, height, depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, depth, color_type


def test_apple_and_browser_icons_use_the_new_versioned_artwork():
    head = HeadLinks()
    head.feed((FRONTEND / "index.html").read_text())
    assert head.links["apple-touch-icon"]["href"] == "/apple-touch-icon-parlay-v2.png"
    assert head.links["apple-touch-icon"]["sizes"] == "180x180"
    assert head.links["icon"]["href"] == "/favicon-parlay-v2.png"
    assert "parlay-icon-v2" in head.links["manifest"]["href"]
    assert urlsplit(head.links["manifest"]["href"]).path == "/manifest.webmanifest"


def test_export_sizes_and_opaque_source_are_preserved():
    expected = {
        "parlay-icon-source.png": 1254,
        "apple-touch-icon-parlay-v2.png": 180,
        "parlay-icon-192-v2.png": 192,
        "parlay-icon-512-v2.png": 512,
        "favicon-parlay-v2.png": 32,
    }
    for name, size in expected.items():
        width, height, depth, color_type = png_info(name)
        assert (width, height) == (size, size)
        assert depth == 8
        assert color_type in {0, 2}  # iOS exports have no transparency


def test_manifest_and_in_app_brand_use_matching_new_assets():
    manifest = json.loads((FRONTEND / "public" / "manifest.webmanifest").read_text())
    assert manifest["name"] == "Parlay"
    assert manifest["display"] == "standalone"
    assert {icon["src"] for icon in manifest["icons"]} == {
        "/parlay-icon-192-v2.png", "/parlay-icon-512-v2.png"
    }
    for icon in manifest["icons"]:
        width, height, _, _ = png_info(icon["src"].lstrip("/"))
        assert icon["sizes"] == f"{width}x{height}"
    assert any("maskable" in icon["purpose"].split() for icon in manifest["icons"])
    shell = (FRONTEND / "src" / "components" / "AppShell.tsx").read_text()
    assert 'src="/parlay-icon-192-v2.png"' in shell

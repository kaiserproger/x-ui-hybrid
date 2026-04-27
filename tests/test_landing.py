"""Property-style tests for the decoy landing generator."""

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

import landing  # noqa: E402  (path injected by conftest)


# ---- helpers ----------------------------------------------------------------

class _MinimalHTMLChecker(HTMLParser):
    """Smoke-test that the generated HTML opens/closes its tags reasonably."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []
    def handle_starttag(self, tag, _attrs):
        if tag in {"meta", "link", "br", "img", "input", "hr"}:
            return
        self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack:
            self.errors.append(f"closing {tag!r} with empty stack")
            return
        # Allow non-strict ordering for inline blocks; only check a tag exists in stack.
        if tag in self.stack:
            # Pop until we find it.
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.errors.append(f"closing {tag!r} not in stack {self.stack!r}")


def _gen(tmp_path: Path, *, seed: str, **kwargs) -> Path:
    out = tmp_path / f"site-{seed}"
    meta = tmp_path / f"meta-{seed}.json"
    args = ["--domain", f"ex{seed}.test", "--out", str(out),
            "--meta-file", str(meta), "--seed", seed]
    for k, v in kwargs.items():
        args.append(f"--{k.replace('_','-')}")
        if v is not None:
            args.append(str(v))
    rc = subprocess.run([sys.executable, "landing.py", *args],
                        cwd=Path(__file__).resolve().parent.parent,
                        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    return meta


# ---- tests ------------------------------------------------------------------

def test_outputs_present(tmp_path):
    meta = _gen(tmp_path, seed="1", no_network=None)
    out = meta.parent / "site-1"
    assert (out / "index.html").is_file()
    assert (out / "404.html").is_file()
    assert (out / "favicon.svg").is_file()
    assert (out / "robots.txt").is_file()
    # Meta file is OUTSIDE the webroot — important.
    assert meta.is_file()
    assert not (out / "_meta.json").exists()


def test_meta_shape(tmp_path):
    meta = _gen(tmp_path, seed="42", no_network=None)
    data = json.loads(meta.read_text())
    assert {"domain", "geo", "persona", "visual", "seed"} <= data.keys()
    p = data["persona"]
    for k in ("archetype", "trade", "name", "city", "country", "founded", "tagline"):
        assert k in p, k
    assert data["visual"]["layout"] in landing.LAYOUTS
    assert data["visual"]["palette"] in {pp["name"] for pp in landing.PALETTES}
    assert isinstance(p["founded"], int)


def test_html_basically_well_formed(tmp_path):
    meta = _gen(tmp_path, seed="7", no_network=None)
    html = (meta.parent / "site-7" / "index.html").read_text()
    assert html.startswith("<!doctype html>")
    chk = _MinimalHTMLChecker()
    chk.feed(html)
    assert not chk.errors, chk.errors


def test_email_link_uses_domain(tmp_path):
    meta = _gen(tmp_path, seed="email", no_network=None)
    html = (meta.parent / "site-email" / "index.html").read_text()
    # The page links to mailto:hello@<domain>
    assert "mailto:hello@exemail.test" in html


def test_country_override_honored(tmp_path):
    meta = _gen(tmp_path, seed="o1", country="JP", city="Kanazawa")
    data = json.loads(meta.read_text())
    assert data["geo"]["country"] == "JP"
    assert data["persona"]["city"] == "Kanazawa"
    assert data["persona"]["country"] == "JP"


def test_layout_force(tmp_path):
    for layout in landing.LAYOUTS:
        meta = _gen(tmp_path, seed=f"L-{layout}", no_network=None, layout=layout)
        data = json.loads(meta.read_text())
        assert data["visual"]["layout"] == layout


def test_dark_layout_uses_dark_palette(tmp_path):
    meta = _gen(tmp_path, seed="dark", no_network=None, layout="studio_dark")
    data = json.loads(meta.read_text())
    assert data["visual"]["palette"] in landing.DARK_PALETTES


def test_personas_vary_across_seeds(tmp_path):
    seen_archetypes = set()
    seen_layouts = set()
    seen_countries = set()
    for i in range(40):
        meta = _gen(tmp_path, seed=f"v{i}", no_network=None)
        data = json.loads(meta.read_text())
        seen_archetypes.add(data["persona"]["archetype"])
        seen_layouts.add(data["visual"]["layout"])
        seen_countries.add(data["geo"]["country"])
    # We expect *plenty* of variety from 40 random seeds.
    assert len(seen_archetypes) >= 10, seen_archetypes
    assert len(seen_layouts) == len(landing.LAYOUTS), seen_layouts
    assert len(seen_countries) >= 8, seen_countries


def test_seed_is_deterministic(tmp_path):
    a = _gen(tmp_path, seed="same", no_network=None)
    b_root = tmp_path / "second"
    b_root.mkdir()
    rc = subprocess.run(
        [sys.executable, "landing.py",
         "--domain", "exsame.test", "--out", str(b_root / "out"),
         "--meta-file", str(b_root / "meta.json"),
         "--seed", "same", "--no-network"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    da = json.loads(a.read_text())
    db = json.loads((b_root / "meta.json").read_text())
    # Seed determines persona + visual choices regardless of geo lookup.
    assert da["persona"]["name"]    == db["persona"]["name"]
    assert da["visual"]["layout"]   == db["visual"]["layout"]
    assert da["visual"]["palette"]  == db["visual"]["palette"]


def test_no_template_placeholder_leaks(tmp_path):
    """Make sure a {city} or {lead} ever leaks into the rendered page."""
    for seed in ("p1", "p2", "p3"):
        meta = _gen(tmp_path, seed=seed, no_network=None)
        html = (meta.parent / f"site-{seed}" / "index.html").read_text()
        assert not re.search(r"\{[a-z_]+\}", html), \
            f"placeholder leaked: {re.search(r'{[a-z_]+}', html).group(0)}"

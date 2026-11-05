# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Build slide decks from Markdown: slides/NN-name.md -> NN-name.html (and index.html).

The decks (NN-name.html) are generated and git-ignored; the index.html files are tracked.

    uv run --with markdown-it-py --with mdit-py-plugins --with pygments --with pyyaml \
        python tools/build.py [slides/NN-name.md ...]

With no arguments it builds every deck set: the decks in slides/ and those in one-day/slides/.
A deck is written next to the slides/ folder that holds its source and loads the shared
assets/ through a relative path.

The syntax is documented in slides/README.md. The generated HTML uses the classes
in assets/deck.css and the engine in assets/deck.js, so the layout and the other
tools (check_layout.py, export_pdf.py) are unchanged.
"""

from __future__ import annotations

import html
import os
import pathlib
import re
import shlex
import sys

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.attrs import attrs_block_plugin, attrs_plugin
from mdit_py_plugins.container import container_plugin
from pygments import highlight
from pygments.formatter import Formatter
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Generic, Keyword, Literal, Name, Number, Operator, String

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLIDES = ROOT / "slides"
# Every folder whose slides/ holds decks. Each has its own index.html; all share ROOT / "assets".
DECK_ROOTS = [ROOT, ROOT / "one-day"]
ASSETS = ROOT / "assets"

# ---------------------------------------------------------------------------
# attribute strings: {.cls key="value" key=value #id}
# ---------------------------------------------------------------------------
ATTR_TAIL = re.compile(r"\s*\{([^{}]*)\}\s*$")


def parse_attrs(spec: str) -> tuple[list[str], dict[str, str]]:
    """Parse '.a .b key="v w" k=v' into (classes, attrs)."""
    classes: list[str] = []
    attrs: dict[str, str] = {}
    for tok in shlex.split(spec):
        if tok.startswith("."):
            classes.append(tok[1:])
        elif "=" in tok:
            k, v = tok.split("=", 1)
            attrs[k] = v
        elif tok:
            classes.append(tok)
    return classes, attrs


def split_attrs(text: str) -> tuple[str, list[str], dict[str, str]]:
    m = ATTR_TAIL.search(text)
    if not m:
        return text, [], {}
    cls, at = parse_attrs(m.group(1))
    return text[: m.start()], cls, at


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------------------
# code highlighting: Pygments tokens -> the deck's c/k/s/n/p classes
# ---------------------------------------------------------------------------
TOKEN_CLASS = [
    (Comment, "c"),
    (Generic.Heading, "p"),
    (Generic.Subheading, "p"),
    (Literal.Scalar.Plain, None),
    (String, "s"),
    (Number, "n"),
    (Literal, "n"),
    (Keyword, "k"),
    (Operator.Word, "k"),
    (Name.Function, "p"),
    (Name.Class, "p"),
    (Name.Decorator, "p"),
]


class DeckFormatter(Formatter):
    """Emit one line per source line, highlighting lines in hl_lines with .h."""

    def __init__(self, hl_lines=(), **kw):
        super().__init__(**kw)
        self.hl = set(hl_lines)

    def format(self, tokensource, outfile):
        # merge adjacent tokens of the same class, then split into lines
        merged: list[list] = []
        for ttype, value in tokensource:
            cls = next((c for t, c in TOKEN_CLASS if ttype in t), None)
            if merged and merged[-1][0] == cls:
                merged[-1][1] += value
            else:
                merged.append([cls, value])
        lines, cur = [], []
        for cls, value in merged:
            parts = value.split("\n")
            for i, part in enumerate(parts):
                if i:
                    lines.append("".join(cur))
                    cur = []
                if part:
                    e = esc(part)
                    cur.append(f'<span class="{cls}">{e}</span>' if cls else e)
        if cur:
            lines.append("".join(cur))
        while lines and lines[-1] == "":
            lines.pop()
        out = []
        for n, line in enumerate(lines, 1):
            out.append(f'<span class="h">{line}</span>' if n in self.hl else line)
        outfile.write("\n".join(out))


PLACEHOLDER = re.compile(r"&lt;([A-Za-z][\w-]*)&gt;")


def tint_placeholders(code_html: str) -> str:
    # <you>, <team_name>, <agent> … in code become prompt-colored (not inside comments)
    parts = re.split(r'(<span class="c">.*?</span>)', code_html)
    return "".join(p if p.startswith('<span class="c">') else
                   PLACEHOLDER.sub(r'<span class="p">&lt;\1&gt;</span>', p) for p in parts)


def parse_lines(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        if a.strip():
            out += list(range(int(a), int(b or a) + 1))
    return out


def render_code(code: str, info: str) -> str:
    lang, _, rest = info.strip().partition(" ")
    cls, at = parse_attrs(rest.strip().strip("{}")) if rest.strip() else ([], {})
    hl = parse_lines(at.get("hl", ""))
    code = code.rstrip("\n")
    if lang in ("", "text", "plain"):
        body = "\n".join(
            f'<span class="h">{esc(l)}</span>' if n in hl else esc(l)
            for n, l in enumerate(code.split("\n"), 1)
        )
    else:
        try:
            lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=True)
        except Exception:
            lexer = get_lexer_by_name("text")
        body = highlight(code, lexer, DeckFormatter(hl_lines=hl))
    body = tint_placeholders(body)
    style = f' style="{esc(at["style"])}"' if "style" in at else ""
    klass = f' class="{" ".join(cls)}"' if cls else ""
    return f"<pre{klass}{style}>{body}</pre>\n"


# ---------------------------------------------------------------------------
# markdown-it setup
# ---------------------------------------------------------------------------
CONTAINERS = ["cols", "grid", "card", "callout", "steps", "takeaways", "agenda",
              "flow", "kpis", "div", "col", "notes", "center", "dg", "row"]


def container_open(name):
    def render(self, tokens, idx, options, env):
        tok = tokens[idx]
        if tok.nesting != 1:
            return "</div>\n"
        args = tok.info.strip()[len(name):].strip()
        return f'<div data-mdc="{name}" data-args="{esc(args)}">\n'
    return render


def make_md() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable("table")
    md.use(attrs_block_plugin).use(attrs_plugin)
    for name in CONTAINERS:
        md.use(container_plugin, name=name, render=container_open(name))
    md.add_render_rule("fence", lambda self, tokens, idx, options, env:
                       render_code(tokens[idx].content, tokens[idx].info))
    return md


MD = make_md()

# ---------------------------------------------------------------------------
# post-processing of rendered HTML: containers, heading attrs, defaults
# ---------------------------------------------------------------------------
HEAD_ATTR = re.compile(r"<h([1-6])([^>]*)>(.*?)\s*\{([^{}]*)\}</h\1>", re.S)


def heading_attrs(h: str) -> str:
    def sub(m):
        lvl, existing, text, spec = m.groups()
        cls, at = parse_attrs(spec)
        a = existing
        if cls:
            a += f' class="{" ".join(cls)}"'
        for k, v in at.items():
            a += f' {k}="{esc(v)}"'
        return f"<h{lvl}{a}>{text}</h{lvl}>"
    return HEAD_ATTR.sub(sub, h)


ROW_HL = re.compile(r"<tr>((?:(?!</tr>).)*?)\s*\{\.hl\}(</td>\s*</tr>)", re.S)


TABLE_WIDTHS = re.compile(r'<table([^>]*?) widths="([^"]*)"([^>]*)>(.*?)</tr>', re.S)


def table_widths(h: str) -> str:
    """widths="230px||330px" on a table sets the header cells' widths."""
    def sub(m):
        before, spec, after, head = m.groups()
        ws = spec.split("|")
        cells = iter(ws)

        def th(mm):
            w = next(cells, "")
            return f'<th style="width:{w}">' if w else "<th>"
        return f"<table{before}{after}>" + re.sub(r"<th>", th, head) + "</tr>"
    return TABLE_WIDTHS.sub(sub, h)


def defaults(h: str) -> str:
    h = table_widths(h)
    # tables are .t, lists are .b unless they carry classes already
    h = re.sub(r"<table>", '<table class="t">', h)
    h = re.sub(r'<table class="(?![^"]*\bt\b)', '<table class="t ', h)
    h = re.sub(r"<(ul|ol)>", r'<\1 class="b">', h)
    h = re.sub(r'<(ul|ol) class="(?![^"]*\bb\b)', r'<\1 class="b ', h)
    h = re.sub(r'<(ul|ol)( start="\d+")>', r'<\1 class="b"\2>', h)
    h = ROW_HL.sub(r'<tr class="hl">\1\2', h)
    return h


def find_container(h: str, start: int = 0):
    """Find the next data-mdc div and its matching close; return (s, e, name, args, inner)."""
    m = re.compile(r'<div data-mdc="([^"]+)" data-args="([^"]*)">\n').search(h, start)
    if not m:
        return None
    depth, i = 1, m.end()
    tag = re.compile(r"<div\b|</div>")
    while depth:
        t = tag.search(h, i)
        if not t:
            raise ValueError("unbalanced container")
        depth += 1 if t.group(0) == "<div" else -1
        i = t.end()
    return m.start(), i, m.group(1), html.unescape(m.group(2)), h[m.end(): i - len("</div>")]


def split_on(inner: str, level: int) -> list[str]:
    """Split HTML at <hN> boundaries (keeping the heading with its part)."""
    parts = re.split(rf"(?=<h{level}[ >])", inner)
    return [p for p in parts if p.strip()]


def split_columns(inner: str) -> list[str]:
    return [p for p in re.split(r"<p>\|\|\|</p>\n?", inner)]


def wrap_col(part: str) -> str:
    """Wrap a column in .col, except a lone table/pre, which stays a direct grid
    child so the grid stretches it to the row height (as the hand-written decks did)."""
    s = part.strip()
    if s.startswith('<div class="col">') and s.endswith("</div>") and s.count('<div class="col">') == 1:
        return part
    for tag in ("table", "pre"):
        if s.startswith(f"<{tag}") and s.endswith(f"</{tag}>") and s.count(f"<{tag}") == 1:
            return part
    return f'<div class="col">\n{part}</div>\n'



def kv_and_classes(args: str):
    cls, at = parse_attrs(args) if args else ([], {})
    return cls, at


def render_container(name: str, args: str, inner: str) -> str:
    inner = expand(inner)
    cls, at = kv_and_classes(args)
    style = at.pop("style", "")
    st = f' style="{esc(style)}"' if style else ""

    if name == "cols":
        tmpl = " ".join(c for c in cls if not c.startswith("gap")) or "1fr 1fr"
        gap = at.get("gap", "30px")
        cols = "".join(wrap_col(c) for c in split_columns(inner))
        return f'<div class="grid" style="grid-template-columns: {tmpl}; gap:{gap};{style}">\n{cols}</div>\n'
    if name == "grid":
        n = next((c for c in cls if c.isdigit()), "2")
        klass = " ".join(["grid", f"g{n}"] + [c for c in cls if not c.isdigit()])
        parts = split_columns(inner)
        body = inner if len(parts) == 1 else "".join(wrap_col(c) for c in parts)
        gap = f' style="gap:{at["gap"]};{style}"' if "gap" in at else st
        return f'<div class="{klass}"{gap}>\n{body}</div>\n'
    if name == "card":
        tag = f'<span class="tag">{esc(at["tag"])}</span>' if "tag" in at else ""
        return f'<div class="{" ".join(["card"] + cls)}"{st}>{tag}\n{inner}</div>\n'
    if name == "callout":
        return f'<div class="{" ".join(["callout"] + cls)}"{st}>\n{strip_p(inner)}</div>\n'
    if name == "steps":
        steps = "".join(f'<div class="step"><div>{p}</div></div>\n' for p in split_on(inner, 4))
        return f'<div class="steps"{st}>\n{steps}</div>\n'
    if name == "takeaways":
        out = []
        for n, p in enumerate(split_on(inner, 3), 1):
            out.append(f'<div class="tk"><span class="n">{n}</span><div>{p}</div></div>\n')
        return f'<div class="takeaways"{st}>\n{"".join(out)}</div>\n'
    if name == "agenda":
        rows = []
        for li in re.findall(r"<li>(.*?)</li>", inner, re.S):
            li, lcls, _ = split_attrs(li.strip())
            f = [x.strip() for x in li.split("|")]
            f += [""] * (3 - len(f))
            de = f'<div class="de">{f[2]}</div>' if f[2] else ""
            rc = " ".join(["agenda-row"] + lcls)
            rows.append(f'<div class="{rc}"><span class="tm">{f[0]}</span><div><div class="ti">{f[1]}</div>{de}</div></div>\n')
        return "".join(rows)
    if name == "flow":
        items = []
        for li in re.findall(r"<li>(.*?)</li>", inner, re.S):
            li = li.strip()
            li, lcls, lat = split_attrs(li)
            if li.startswith("-&gt;") or li.startswith("&lt;-"):
                left = li.startswith("&lt;-")
                label = li[5:].strip()
                w = lat.get("w", "44")
                lab = f"<span>{label}</span>" if label else ""
                items.append(f'<div class="arrow-h{" left" if left else ""}" style="width:{w}px">{lab}</div>')
            else:
                m = re.match(r"\[([^\]]*)\]\s*(.*)", li, re.S)
                color, rest = (m.group(1), m.group(2)) if m else ("gray", li)
                ccls, cat = parse_attrs(color)
                flex = cat.get("flex", "1")
                pieces = [x.strip() for x in re.split(r"(?<!\\)\|", rest)]
                pieces = [x.replace("\\|", "|") for x in pieces]
                b = pieces[0]

                def piece(x):
                    # default small; '=' plain span; '~' mono span
                    if x.startswith("="):
                        return f"<span>{x[1:].strip()}</span>"
                    if x.startswith("~"):
                        return f'<span class="mono">{x[1:].strip()}</span>'
                    return f'<span class="small">{x}</span>'
                spans = "".join(piece(x) for x in pieces[1:])
                items.append(f'<div class="box {" ".join(ccls + lcls)}" style="flex:{flex}">{b}{spans}</div>')
        gap = at.get("gap", "0")
        return f'<div class="row" style="align-items:stretch; gap:{gap};{style}">\n' + "\n".join(items) + "\n</div>\n"
    if name == "kpis":
        return f'<div class="kpi"{st}>\n{inner}</div>\n'
    if name == "notes":
        return f'<aside class="notes">{strip_p(inner)}</aside>\n'
    # div / col / center / dg / row / anything else: plain div with classes
    base = [] if name == "div" else [name]
    return f'<div class="{" ".join(base + cls)}"{st}>\n{inner}</div>\n'


def strip_p(inner: str) -> str:
    """A single-paragraph body loses its <p> (callouts, notes)."""
    s = inner.strip()
    if s.count("<p>") == 1 and s.startswith("<p>") and s.endswith("</p>"):
        return s[3:-4]
    return inner


def expand(h: str) -> str:
    out, i = [], 0
    while True:
        f = find_container(h, i)
        if not f:
            out.append(h[i:])
            return "".join(out)
        s, e, name, args, inner = f
        out.append(h[i:s])
        out.append(render_container(name, args, inner))
        i = e


def isolate_column_breaks(text: str) -> str:
    """Make every '|||' line (outside code fences) a paragraph of its own."""
    out, fence = [], None
    for line in text.split("\n"):
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            fence = None if fence and line.strip().startswith(fence) else (fence or m.group(1))
        if fence is None and line.strip() == "|||":
            out += ["", "|||", ""]
        else:
            out.append(line)
    return "\n".join(out)


def render_md(text: str) -> str:
    h = MD.render(isolate_column_breaks(text))
    h = expand(h)
    h = heading_attrs(h)
    return defaults(h)


def inline(text: str) -> str:
    return MD.renderInline(text)


# ---------------------------------------------------------------------------
# slides
# ---------------------------------------------------------------------------
def logos(assets_prefix: str) -> str:
    return (f'<div class="logos"><img src="{assets_prefix}/INL-logo.png" alt="INL">'
            f'<img src="{assets_prefix}/genesis_logo.png" alt="Genesis"></div>')


def prom(assets_prefix: str) -> str:
    return (f'<img src="{assets_prefix}/prometheus_logo.png" alt="Prometheus" '
            'style="width:560px; margin-left:-18px">')


def split_slides(body: str) -> list[str]:
    slides, cur, fence = [], [], None
    for line in body.split("\n"):
        m = re.match(r"^(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif line.startswith(fence):
                fence = None
        if fence is None and line.strip() == "---":
            slides.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    slides.append("\n".join(cur))
    return [s.strip("\n") for s in slides if s.strip()]


NOTE = re.compile(r"^Note:\s*(.*?)(?=\n\s*\n|\Z)", re.S | re.M)


def take_notes(src: str) -> tuple[str, str]:
    notes = [m.group(1).strip() for m in NOTE.finditer(src)]
    src = NOTE.sub("", src)
    html_notes = "".join(f'\n  <aside class="notes">{inline(n)}</aside>' for n in notes)
    return src, html_notes


def section_open(classes: list[str], at: dict[str, str]) -> str:
    flags = [k for k in ("nofit", "nofoot") if k in at or k in classes]
    classes = list(dict.fromkeys(c for c in classes if c not in ("nofit", "nofoot")))
    a = f'<section class="{" ".join(["slide"] + classes)}"'
    for k in flags:
        a += f" data-{k}"
    if "style" in at:
        a += f' style="{esc(at["style"])}"'
    return a + ">"


def build_slide(src: str, mode: list[str], assets_prefix: str) -> tuple[str, list[str]]:
    """Return (html, new_mode). mode is the inherited ['appendix'] / ['bonus'] / [].

    assets_prefix is the URL prefix of the shared assets/ folder, relative to the deck.
    """
    src, notes = take_notes(src)
    lines = src.split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), 0)
    head = lines[first]
    rest = "\n".join(lines[first + 1:])

    if head.startswith("# "):
        text, cls, at = split_attrs(head[2:])
        if "title" in cls:
            pills = "".join(
                f'<span class="pill{" acc" if i == 0 else ""}">{inline(p.strip())}</span>'
                for i, p in enumerate(at.get("pills", "").split("|")) if p.strip())
            sub = render_md(rest).strip()
            sub = re.sub(r"^<p>(.*)</p>$", r'<p class="sub">\1</p>', sub, flags=re.S)
            kicker = f'<div class="kicker">{inline(at["kicker"])}</div>' if "kicker" in at else ""
            body = (f"  {logos(assets_prefix)}\n  {prom(assets_prefix)}\n  {kicker}\n  <h1>{inline(text)}</h1>\n  {sub}\n"
                    f'  <div class="meta">{pills}</div>')
            return f"{section_open(['title'] + mode, at)}\n{body}{notes}\n</section>", mode
        # section / interstitial page; may switch the mode for the following slides
        new_mode = mode
        if "appendix" in cls:
            new_mode = ["appendix"]
        elif "bonus" in cls:
            new_mode = ["bonus"]
        elif "main" in cls:
            new_mode = []
        kind = [c for c in cls if c not in ("section", "appendix", "bonus", "main")]
        num = f'<div class="num">{inline(at.get("num", ""))}</div>\n  ' if "num" in at else ""
        lede = render_md(rest).strip()
        lede = re.sub(r"^<p>(.*)</p>$", r'<p class="lede">\1</p>', lede, flags=re.S)
        body = f"  {num}<h2>{inline(text)}</h2>\n  {lede}"
        return f"{section_open(['section'] + kind + new_mode, at)}\n{body}{notes}\n</section>", new_mode

    if not head.startswith("## "):
        raise ValueError(f"slide must start with '# ' or '## ': {head!r}")
    text, cls, at = split_attrs(head[3:])
    eyebrow = f'<div class="eyebrow">{inline(at["eyebrow"])}</div>' if "eyebrow" in at else ""
    lede = ""
    rest_lines = rest.split("\n")
    # an optional lede: '> text' lines right after the heading
    j = 0
    while j < len(rest_lines) and not rest_lines[j].strip():
        j += 1
    lede_lines = []
    while j < len(rest_lines) and rest_lines[j].startswith(">"):
        lede_lines.append(rest_lines[j][1:].strip())
        j += 1
    if lede_lines:
        lede = f'<p class="lede">{inline(" ".join(lede_lines))}</p>'
        rest = "\n".join(rest_lines[j:])
    content_cls = " ".join(["content"] + at.get("content", "").split())
    cstyle = f' style="{esc(at["content-style"])}"' if "content-style" in at else ""
    h2 = f"<h2>{inline(text)}</h2>" if text.strip() else ""
    body = render_md(rest)
    out = (f"{section_open(cls + mode, at)}\n"
           f'  <div class="head">{eyebrow}{h2}{lede}</div>\n'
           f'  <div class="{content_cls}"{cstyle}>\n{body}  </div>{notes}\n</section>')
    return out, mode


# ---------------------------------------------------------------------------
# deck page
# ---------------------------------------------------------------------------
HEAD = """<!doctype html>
<!-- generated from {src}: edit that file and run tools/build.py -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="{assets}/deck.css">{style}
</head>
<body data-sec="{sec}" data-title="{footer}"{attrs}>
<div id="viewport"><div id="stage">

"""
TAIL = """

</div></div>
<script src="{assets}/deck.js"></script>
</body>
</html>
"""


def load_deck(path: pathlib.Path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    meta, body = (yaml.safe_load(m.group(1)) or {}, m.group(2)) if m else ({}, text)
    return meta, body


def accent_style(accent: str) -> tuple[str, str]:
    if accent.startswith("#"):
        css = (f"\n<style>body {{ --acc: {accent}; --acc-ink: color-mix(in srgb, {accent} 80%, black);"
               f" --acc-soft: color-mix(in srgb, {accent} 10%, white); }}</style>")
        return "custom", css
    return accent, ""


def deck_root(path: pathlib.Path) -> pathlib.Path:
    """The folder that holds the slides/ folder containing ``path``; decks are written there."""
    return path.resolve().parent.parent


def build(path: pathlib.Path) -> pathlib.Path:
    root = deck_root(path)
    # "assets" for the decks in ROOT, "../assets" for those one folder down
    assets_prefix = pathlib.PurePosixPath(os.path.relpath(ASSETS, root)).as_posix()
    meta, body = load_deck(path)
    sec, style = accent_style(str(meta.get("accent", "welcome")))
    if meta.get("css"):
        style += f"\n<style>\n{meta['css']}\n</style>"
    out, mode = [], []
    for src in split_slides(body):
        h, mode = build_slide(src, mode, assets_prefix)
        out.append(h)
    src = root.relative_to(ROOT) / "slides" / path.name
    # Decks outside ROOT get a footer link back to their own index and load the logo from ../assets.
    attrs = "" if root == ROOT else f' data-logo="{assets_prefix}/prometheus_logo.png" data-index="index.html"'
    page = HEAD.format(src=src.as_posix(), title=esc(str(meta.get("title", path.stem))),
                       style=style, sec=esc(sec), footer=esc(str(meta.get("footer", ""))),
                       assets=assets_prefix, attrs=attrs)
    page += "\n\n".join(out) + TAIL.format(assets=assets_prefix)
    target = root / (path.stem + ".html")
    target.write_text(page)
    return target


def counts(html_text: str) -> str:
    cls = re.findall(r'<section class="slide([^"]*)"', html_text)
    appx = sum("appendix" in c for c in cls)
    bonus = sum("bonus" in c for c in cls)
    talk = len(cls) - appx - bonus
    if not appx and not bonus:
        return f"{talk} slides"
    parts = [f"{talk} talk"] + ([f"{bonus} bonus"] if bonus else []) + (["appendix"] if appx else [])
    return " · ".join(parts)


def build_index(root: pathlib.Path = ROOT) -> None:
    """Rewrite the deck entries between the decks:start/decks:end markers in root/index.html."""
    idx = root / "index.html"
    if not idx.exists():
        return
    rows = []
    for md in sorted((root / "slides").glob("[0-9]*.md")):
        meta, _ = load_deck(md)
        e = meta.get("index")
        if not e:
            continue
        deck = root / (md.stem + ".html")
        n = counts(deck.read_text()) if deck.exists() else ""
        rows.append(f'  <a class="deck" href="{md.stem}.html" style="--c: {e.get("color", "var(--navy)")}">'
                    f'<span class="tm">{e.get("time", "")}</span><div><h3>{e.get("heading", md.stem)}</h3>'
                    f'<p>{e.get("blurb", "")}</p></div><span class="n">{n}</span></a>')
    text = idx.read_text()
    m = re.search(r"(<!-- decks:start[^>]*-->\n)(.*?)(\n\s*<!-- decks:end -->)", text, re.S)
    if not m:
        return
    idx.write_text(text[: m.end(1)] + "\n".join(rows) + text[m.start(3):])
    print(f"{idx.relative_to(ROOT)}: {len(rows)} decks")


def main(argv):
    paths = [pathlib.Path(a) for a in argv] or [
        md for r in DECK_ROOTS for md in sorted((r / "slides").glob("[0-9]*.md"))]
    for p in paths:
        t = build(p)
        n = len(re.findall(r'<section class="slide', t.read_text()))
        print(f"{p} -> {t.relative_to(ROOT)} ({n} slides)")
    # Refresh the index of every deck set that has one (an explicit path still updates its own set).
    for r in DECK_ROOTS:
        build_index(r)


if __name__ == "__main__":
    main(sys.argv[1:])

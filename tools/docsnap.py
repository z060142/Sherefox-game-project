#!/usr/bin/env python
"""Convert Claude Docs "prose" XML views (saved MCP read results) into one Markdown file.

Usage (standard library only):
    python -I -X utf8 tools/docsnap.py --name <tab name> --out <file.md> [--date YYYY-MM-DD] page1.json [page2.json ...]

Each page file is a saved `read(... payload={"kind":"view"...})` result: either the raw JSON
object {"data": {"xml": ...}}, the same inside a batch ack {"acks":[{"data":...}]}, or the
tool-result wrapper [{type,text}, ...] around either.
Pages are stitched in the order given: the blocks of a later page replace the blocks of the
earlier pages starting at the first block id they share (or continue after a `<gap from=...>`).
The text is kept verbatim; the only escaping done is `|` inside table cells.
"""
import argparse
import datetime
import json
import re
import sys
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------- loading / stitching

def load_page(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        cands = [x["text"] for x in raw if isinstance(x, dict) and x.get("text", "").lstrip().startswith("{")]
        if not cands:
            raise SystemExit("no JSON payload in %s" % path)
        raw = json.loads(cands[0])
    if "acks" in raw:  # batch(read ...) wrapper
        raw = raw["acks"][0]
    data = raw["data"] if "data" in raw else raw
    root = ET.fromstring(data["xml"])
    return data, root


def normalise_ids(root):
    """Ids are written with a sticky prefix ('.123' reuses the last 'prefix.' seen). Make all absolute."""
    prefix = ""
    for el in root.iter():
        for key in ("id", "from", "parent"):
            v = el.get(key)
            if v is None:
                continue
            if v.startswith("."):
                el.set(key, prefix + v)
            elif "." in v and key == "id":
                prefix = v.split(".", 1)[0]
            elif "." in v:
                pass


def stitch(paths):
    master = []          # top-level block elements in document order
    pending = set()      # gap `from` ids seen but not yet filled
    revs = set()
    last_complete = None
    for n, path in enumerate(paths):
        data, root = load_page(path)
        normalise_ids(root)
        revs.add(str(data.get("rev")))
        last_complete = data.get("complete", True)
        blocks = [c for c in root if c.tag != "gap"]
        if not blocks:
            continue
        first = blocks[0].get("id")
        ids = [b.get("id") for b in master]
        if first in ids:
            del master[ids.index(first):]
        elif n > 0 and first not in pending:
            raise SystemExit("page %s starts at %s which neither overlaps nor continues a gap" % (path, first))
        for c in root:
            if c.tag == "gap" and c.get("from"):
                pending.add(c.get("from"))
        master.extend(blocks)
    if len(revs) != 1:
        raise SystemExit("pages come from different revisions: %s" % sorted(revs))
    if last_complete is False:
        raise SystemExit("last page is not complete")
    top_ids = [b.get("id") for b in master]
    if len(top_ids) != len(set(top_ids)):
        raise SystemExit("duplicate top-level block ids after stitching")
    holder = ET.Element("doc")
    holder.extend(master)
    leftover = [g.attrib for g in holder.iter("gap")]
    if leftover:
        raise SystemExit("unresolved gaps remain: %s" % leftover[:5])
    return holder, revs.pop()


# ---------------------------------------------------------------- inline rendering

class Stats:
    def __init__(self):
        self.empty_paragraphs = 0
        self.embeds = 0
        self.media = 0
        self.mentions = 0
        self.dates = 0
        self.unknown = {}
        self.tables = 0
        self.headings = 0
        self.check_items = 0

    def unk(self, tag):
        self.unknown[tag] = self.unknown.get(tag, 0) + 1


def segs_of(el, fmt, st, out):
    """Flatten inline content into [(text, fmt_tuple)] ; atomic items have fmt None."""
    if el.text:
        out.append((el.text, fmt))
    for ch in el:
        t = ch.tag
        if t in ("bold", "italic", "code"):
            segs_of(ch, tuple(sorted(set(fmt) | {t})), st, out)
        elif t == "text":
            segs_of(ch, fmt, st, out)
        elif t == "date":
            st.dates += 1
            out.append((ch.get("value", ""), fmt))
        elif t == "mention":
            st.mentions += 1
            out.append((ch.get("name") or ch.get("label") or "", fmt))
        elif t == "media":
            st.media += 1
            blob = ch.get("blob", "")
            if blob.startswith("blob/"):
                blob = blob[len("blob/"):]
            out.append(("![%s](blob:%s)" % (ch.get("alt", ""), blob), None))
        else:
            st.unk(t)
        if ch.tail:
            out.append((ch.tail, fmt))
    return out


def wrap(text, fmt):
    if not fmt or not text:
        return text
    m = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S)
    lead, core, trail = m.groups()
    if not core:
        return text
    if "code" in fmt:
        core = "`" + core + "`"
    if "italic" in fmt:
        core = "*" + core + "*"
    if "bold" in fmt:
        core = "**" + core + "**"
    return lead + core + trail


def inline(el, st):
    segs = segs_of(el, (), st, [])
    merged = []
    for text, fmt in segs:
        if not text:
            continue
        if merged and merged[-1][1] == fmt and fmt is not None:
            merged[-1] = (merged[-1][0] + text, fmt)
        else:
            merged.append((text, fmt))
    return "".join(t if f is None else wrap(t, f) for t, f in merged)


# ---------------------------------------------------------------- block rendering

def render_paragraph(p, st):
    return inline(p, st)


def cell_text(cell, st):
    parts = []
    for ch in cell:
        if ch.tag == "paragraph":
            parts.append(inline(ch, st))
        else:
            st.unk("cell/" + ch.tag)
    s = "<br>".join(parts)
    s = s.replace("\r", "").replace("\n", "<br>").replace("|", "\\|")
    return s


def render_table(tbl, st):
    st.tables += 1
    rows = tbl.findall("row")
    grid, hdr_flags, aligns = [], [], []
    for r in rows:
        cells = r.findall("cell")
        grid.append([cell_text(c, st) for c in cells])
        hdr_flags.append(bool(cells) and all(c.get("header") == "true" for c in cells))
        aligns.append([c.get("align", "left") for c in cells])
    ncol = max((len(g) for g in grid), default=0)
    if ncol == 0:
        return ""
    lines = []
    if hdr_flags and hdr_flags[0]:
        header, body, al = grid[0], grid[1:], aligns[0]
    else:
        header, body, al = [""] * ncol, grid, (aligns[0] if aligns else [])
    pad = lambda g: g + [""] * (ncol - len(g))
    al = al + ["left"] * (ncol - len(al))
    lines.append("| " + " | ".join(pad(header)) + " |")
    lines.append("|" + "|".join(" :---: " if a == "center" else " --- " for a in al) + "|")
    for g in body:
        lines.append("| " + " | ".join(pad(g)) + " |")
    return "\n".join(lines)


def render_list(lst, depth, st):
    kind = lst.get("kind", "bullet")
    start = int(lst.get("start", "1")) if kind == "ordered" else 1
    lines = []
    pad = "  " * depth
    for i, item in enumerate(lst.findall("listItem")):
        if kind == "ordered":
            marker = "%d." % (start + i)
        elif kind == "check":
            marker = "- [ ]"
            st.check_items += 1
        else:
            marker = "-"
        first = True
        for ch in item:
            if ch.tag == "paragraph":
                txt = inline(ch, st).replace("\n", "\n" + pad + "  ")
                if first:
                    lines.append("%s%s %s" % (pad, marker, txt))
                    first = False
                else:
                    lines.append("%s  %s" % (pad, txt))
            elif ch.tag == "list":
                if first:
                    lines.append("%s%s" % (pad, marker))
                    first = False
                lines.extend(render_list(ch, depth + 1, st))
            else:
                st.unk("listItem/" + ch.tag)
        if first:
            lines.append("%s%s" % (pad, marker))
    return lines


def render_codeblock(cb, st):
    text = "".join(cb.itertext())
    fence = "```"
    while fence in text:
        fence += "`"
    return "%s%s\n%s\n%s" % (fence, cb.get("language", ""), text, fence)


def render_blocks(doc, st):
    out = []
    for b in doc:
        t = b.tag
        if t == "paragraph":
            txt = render_paragraph(b, st)
            h = b.get("heading")
            if h:
                st.headings += 1
                out.append("#" * int(h) + " " + txt.replace("\n", " "))
            elif txt.strip() == "":
                st.empty_paragraphs += 1
            else:
                out.append(txt)
        elif t == "list":
            out.append("\n".join(render_list(b, 0, st)))
        elif t == "table":
            out.append(render_table(b, st))
        elif t == "codeBlock":
            out.append(render_codeblock(b, st))
        elif t == "embed":
            st.embeds += 1
            out.append("[embed: %s](embed:%s)" % (b.get("caption", ""), b.get("ref", "")))
        else:
            st.unk(t)
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------- self check

def md_counts(md):
    heads = tables = 0
    fence = None
    for line in md.split("\n"):
        m = re.match(r"^(`{3,})", line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif line.startswith(fence):
                fence = None
            continue
        if fence:
            continue
        if re.match(r"^#{1,6} ", line):
            heads += 1
        if re.match(r"^\|( :?-{3}:? \|)+$", line):
            tables += 1
    return heads, tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("pages", nargs="+")
    a = ap.parse_args()

    doc, rev = stitch(a.pages)
    xml_tables = len(list(doc.iter("table")))
    xml_heads = sum(1 for p in doc.iter("paragraph") if p.get("heading"))
    st = Stats()
    body = render_blocks(doc, st)
    head = "<!-- snapshot of Claude Docs tab %s, rev %s, taken %s -->\n\n" % (a.name, rev, a.date)
    md = head + body
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    mh, mt = md_counts(md)
    print("%s rev=%s bytes=%d" % (a.out, rev, len(md.encode("utf-8"))))
    print("  headings xml=%d md=%d | tables xml=%d md=%d" % (xml_heads, mh, xml_tables, mt))
    print("  empty_paragraphs_skipped=%d embeds=%d media=%d mentions=%d dates=%d check_items=%d unknown=%s"
          % (st.empty_paragraphs, st.embeds, st.media, st.mentions, st.dates, st.check_items, st.unknown))
    if xml_heads != mh or xml_tables != mt:
        print("  WARNING: count mismatch", file=sys.stderr)


if __name__ == "__main__":
    main()

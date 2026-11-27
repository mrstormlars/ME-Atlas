"""Writes the fictional test PDFs next to this file (``uv run python tests/fixtures/unpaywall/make_pdfs.py``).

Hand-built minimal PDFs, no dependency. Every title and sentence is invented; no real paper text. The ligature
character U+FB01 is written with a font whose encoding maps code 1 to the glyph ``fi`` and whose ToUnicode CMap maps
it to U+FB01, as many real PDFs do.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent

TO_UNICODE = (
    b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
    b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
    b"1 begincodespacerange <00> <FF> endcodespacerange\n"
    b"1 beginbfchar <01> <FB01> endbfchar\n"
    b"endcmap CMapName currentdict /CMap defineresource pop end end\n"
)


def _hex(text: str) -> str:
    return "".join(f"{ord(c):02X}" for c in text)


def _line_ops(x: float, y: float, text: str) -> str:
    """One text line; the ligature U+FB01 is shown with font F2 (code 1), everything else with F1."""
    ops = [f"BT 1 0 0 1 {x} {y} Tm"]
    run, run_font = "", "F1"
    for char in text + "\0":
        font = "F2" if char == "ﬁ" else "F1"
        if char == "\0" or font != run_font:
            if run:
                ops.append(f"/{run_font} 11 Tf <{run}> Tj")
            run, run_font = "", font
        if char != "\0":
            run += "01" if font == "F2" else f"{ord(char):02X}"
    ops.append("ET")
    return " ".join(ops)


def build(pages: list[list[tuple[float, float, str]]], *, draw_only: bool = False) -> bytes:
    """A PDF with one page per list of (x, y, text) lines. ``draw_only`` draws a box instead of text (a scan)."""
    objects: list[bytes] = []
    n = len(pages)
    page_ids = [6 + 2 * i for i in range(n)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /FirstChar 1 /LastChar 1 /Widths [500] "
        b"/Encoding << /Type /Encoding /Differences [1 /fi] >> /ToUnicode 5 0 R >>"
    )
    objects.append(b"<< /Length %d >>\nstream\n" % len(TO_UNICODE) + TO_UNICODE + b"endstream")
    for i, lines in enumerate(pages):
        content_id = page_ids[i] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode()
        )
        ops = "50 700 400 40 re f" if draw_only else "\n".join(_line_ops(x, y, t) for x, y, t in lines)
        stream = ops.encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def stack(x: float, y: float, lines: list[str], step: float = 14) -> list[tuple[float, float, str]]:
    return [(x, y - i * step, text) for i, text in enumerate(lines)]


MAIN_TITLE_LINES = ["Fictional study of open copies", "in a made-up cohort"]

MAIN = [
    stack(
        50,
        760,
        [
            *MAIN_TITLE_LINES,
            "",
            "Methods",
            "Participants were diagnosed according to the Fu-",
            "kuda criteria in a made-up clinic. Each person had a median follow-",
            "up of two fictional years. The ﬁnal sample was a ﬁctional ﬁlter of ten invented people.",
            "The study was run by the Fictional Fatigue Group in Exampleville.",
        ],
    ),
    stack(
        50,
        760,
        [
            "Results",
            "Nothing real was measured in this invented paper at all.",
            "References",
            "Doe J. The Fictional Reference Criteria were applied only in a made-up list. Exampleville 1999.",
        ],
    ),
]
# The reference heading lies in the second half of the text: page 2 is short, page 1 holds most of it.

TWO_COLUMN = [
    [
        *stack(50, 780, ["Fictional two column study of open copies"]),
        *stack(
            50,
            740,
            [
                "Left column text begins here and talks",
                "about an invented background of some",
                "invented illness in an invented town and",
                "continues for several lines of filler text",
                "so that the layout has a real column.",
            ],
        ),
        *stack(
            320,
            740,
            [
                "Right column text states that cases met the",
                "Canadian Consensus Criteria in a made-up",
                "clinic and were counted by invented staff",
                "during the fictional study period.",
            ],
        ),
    ]
]

OTHER_TITLE = [
    stack(
        50,
        760,
        [
            "Fictional unrelated paper about something else",
            "",
            "This invented page has a different title and no relation to the cached record at all, "
            "so the identity check must refuse it.",
        ],
    )
]

SCAN = [[]]


def main() -> None:
    files = {
        "fictional_main.pdf": build(MAIN),
        "fictional_two_column.pdf": build(TWO_COLUMN),
        "fictional_other_title.pdf": build(OTHER_TITLE),
        "fictional_scan.pdf": build(SCAN, draw_only=True),
    }
    for name, data in files.items():
        (HERE / name).write_bytes(data)
        print(name, len(data))


if __name__ == "__main__":
    main()

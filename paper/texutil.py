"""Small helpers shared by the tests and the metadata export: read the paper's macros,
expand them, and turn the abstract and title into plain text."""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEX = HERE / "reconforge.tex"
NUMBERS = HERE / "generated" / "numbers.tex"


def macros(numbers: Path = NUMBERS) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}", numbers.read_text()):
        out[m.group(1)] = m.group(2)
    return out


def plain(s: str, mac: dict[str, str]) -> str:
    """Expand \\name{} macros and strip the few TeX constructs the abstract and title use."""

    def sub(m: re.Match) -> str:
        return mac[m.group(1)] + (m.group(2) or "")

    # \name{} followed by a space or punctuation: the empty braces end the macro name
    s = re.sub(r"\\([A-Za-z]+)\{\}()", sub, s)
    s = s.replace("$-$", "-").replace("\\%", "%").replace("{,}", ",")
    s = s.replace("$R_w$", "R_w").replace("\\\\", " ").replace("~", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def abstract(mac: dict[str, str] | None = None, tex: Path = TEX) -> str:
    mac = mac or macros()
    body = tex.read_text().split("\\begin{abstract}", 1)[1].split("\\end{abstract}", 1)[0]
    return plain(body, mac)


def title(tex: Path = TEX) -> str:
    raw = tex.read_text().split("\\title{", 1)[1].split("}\n", 1)[0]
    return re.sub(r"\s+", " ", raw.replace("\\\\", " ")).strip()

from __future__ import annotations
import re
from pathlib import Path


SUPPORTED_EXTS = (".pdf", ".md", ".txt", ".tex")


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_text_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_latex(source: str) -> str:
    """Convert a LaTeX document into readable plain text.

    Keeps the content inside braces for common formatting commands and drops
    preamble, comments, and bare control sequences. Not a full parser — just
    enough to feed a resume into an LLM prompt without pollution.
    """
    text = source

    # Drop everything before \begin{document} if present
    m = re.search(r"\\begin\{document\}", text)
    if m:
        text = text[m.end():]
    # Drop \end{document} tail
    text = re.sub(r"\\end\{document\}.*", "", text, flags=re.DOTALL)

    # Remove comments (lines starting with % and inline % ... to end of line)
    text = re.sub(r"(?<!\\)%.*", "", text)

    # Keep argument of \textbf{...}, \textit{...}, \emph{...}, \section{...}, \subsection{...}, \href{..}{text}
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:textbf|textit|emph|underline|section\*?|subsection\*?|subsubsection\*?|chapter\*?|paragraph|title|author|textsc|textrm)\s*\{([^{}]*)\}", r"\1", text)

    # Common resume-template macros like \resumeItem{...}, \resumeSubheading{a}{b}{c}{d}
    text = re.sub(r"\\resumeSubheading\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1 — \2 — \3 — \4", text)
    text = re.sub(r"\\resumeProjectHeading\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1 — \2", text)
    text = re.sub(r"\\(?:resumeItem|resumeSubItem|item)\s*\{([^{}]*)\}", r"- \1", text)

    # Bullet \item (no argument)
    text = re.sub(r"\\item\b", "-", text)

    # Replace environment delimiters with blank lines
    text = re.sub(r"\\begin\{[^}]+\}", "", text)
    text = re.sub(r"\\end\{[^}]+\}", "", text)

    # Remove remaining control sequences with braced args: \foo{arg} -> arg
    for _ in range(3):
        text, n = re.subn(r"\\[a-zA-Z]+\*?\s*\{([^{}]*)\}", r"\1", text)
        if n == 0:
            break

    # Remove bare control sequences like \hfill, \\, \newline, \vspace*
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
    text = text.replace("\\\\", "\n")

    # Clean leftover braces, tildes, ampersands
    text = text.replace("~", " ").replace("&", " ")
    text = re.sub(r"[{}]", "", text)

    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def load_document(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _read_pdf(p)
    if ext == ".tex":
        return _strip_latex(_read_text_file(p))
    if ext in (".md", ".txt", ""):
        return _read_text_file(p)
    raise ValueError(f"Unsupported file type: {ext}")


def pick_first(folder: str | Path) -> Path | None:
    p = Path(folder)
    if not p.exists():
        return None
    for f in sorted(p.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
            return f
    return None


def load_resume(path: str | None = None, folder: str = "resumes") -> tuple[str, str]:
    """Returns (text, source_path)."""
    chosen = Path(path) if path else pick_first(folder)
    if chosen is None:
        raise FileNotFoundError(f"No resume file supplied and none found in {folder}/")
    return load_document(chosen), str(chosen)


def load_job_description(path: str | None = None, folder: str = "job_descriptions") -> tuple[str, str]:
    chosen = Path(path) if path else pick_first(folder)
    if chosen is None:
        raise FileNotFoundError(f"No JD file supplied and none found in {folder}/")
    return load_document(chosen), str(chosen)


def extract_candidate_name(resume_text: str) -> str:
    """Best-effort: first non-empty line, cleaned."""
    for line in resume_text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and len(line) < 80:
            return line
    return "Candidate"


def extract_job_title(jd_text: str) -> str:
    for line in jd_text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and len(line) < 120:
            return line
    return "Role"

import argparse
import os
import sys
from pathlib import Path
from google import genai

from core.loader import (
    load_resume,
    load_job_description,
    extract_candidate_name,
    extract_job_title,
)
from core.state import InterviewState
from core.conversation import InterviewLoop
from agents.recruiter_agent import RecruiterAgent
from agents.candidate_agent import CandidateAgent
from rubric.evaluation import evaluate, write_report


DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader — no external dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def build_client() -> genai.Client:
    _load_dotenv(Path(__file__).parent / ".env")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY not found. Add it to a .env file in the project root:\n"
            "  GEMINI_API_KEY=your_key_here",
            file=sys.stderr,
        )
        sys.exit(1)
    return genai.Client(api_key=api_key)


def _print_eval(ev):
    sep = "─" * 60
    print(sep)
    print("  EVALUATION BREAKDOWN")
    print(sep)
    print(f"  Technical Depth:    {ev.technical_depth:.3f}  (weight 35%)")
    print(f"  Communication:      {ev.communication:.3f}  (weight 20%)")
    print(f"  Problem Solving:    {ev.problem_solving:.3f}  (weight 20%)")
    print(f"  Fit (resume↔JD):    {ev.fit:.3f}  (weight 15%)")
    print(f"  Behavioral:         {ev.behavioral:.3f}  (weight 10%)")
    print(sep)
    print(f"  COMPOSITE:          {ev.total:.3f}  →  {ev.verdict.upper()}")
    print(sep)


def main():
    parser = argparse.ArgumentParser(description="Two-Agent Technical Interview Simulation (Gemini)")
    parser.add_argument("--resume", default=None, help="Path to resume (.pdf, .md, .txt). Defaults to first file in resumes/")
    parser.add_argument("--jd", default=None, help="Path to job description. Defaults to first file in job_descriptions/")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-turns", type=int, default=40, help="Max exchanges (~1 hour ≈ 40 turns)")
    parser.add_argument("--out-dir", default="interviews", help="Where to write the report")
    args = parser.parse_args()

    resume_text, resume_path = load_resume(args.resume)
    jd_text, jd_path = load_job_description(args.jd)
    candidate_name = extract_candidate_name(resume_text)
    job_title = extract_job_title(jd_text)

    print(f"\n{'═' * 60}")
    print(f"  INTERVIEW: {candidate_name}")
    print(f"  ROLE:      {job_title}")
    print(f"  MODEL:     {args.model}")
    print(f"{'═' * 60}")

    client = build_client()
    recruiter = RecruiterAgent(client, args.model, jd_text, resume_text)
    candidate = CandidateAgent(client, args.model, resume_text, jd_text)
    state = InterviewState()

    loop = InterviewLoop(
        recruiter=recruiter,
        candidate=candidate,
        state=state,
        max_turns=args.max_turns,
        verbose=True,
    )

    opening = (
        f"Hi {candidate_name.split()[0] if candidate_name else 'there'}, thanks for making the time today. "
        f"We're interviewing for the {job_title} role. "
        "To start, could you walk me through your background and what drew you to this role?"
    )
    state = loop.run(opening)

    print("\n")
    ev = evaluate(state, resume_text, jd_text, client, args.model)
    _print_eval(ev)

    report_path = write_report(
        state=state,
        evaluation=ev,
        candidate_name=candidate_name,
        job_title=job_title,
        resume_text=resume_text,
        jd_text=jd_text,
        resume_path=resume_path,
        jd_path=jd_path,
        out_dir=args.out_dir,
    )
    print(f"\n  Report written to: {report_path}\n")


if __name__ == "__main__":
    main()

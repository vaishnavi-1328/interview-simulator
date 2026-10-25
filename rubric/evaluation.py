from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types

from core.state import InterviewState
from agents.recruiter_agent import RUBRIC_SECTIONS


WEIGHTS = {
    "technical_depth": 0.35,
    "communication": 0.20,
    "problem_solving": 0.20,
    "fit": 0.15,
    "behavioral": 0.10,
}


@dataclass
class EvaluationBreakdown:
    technical_depth: float = 0.0
    communication: float = 0.0
    problem_solving: float = 0.0
    fit: float = 0.0
    behavioral: float = 0.0
    total: float = 0.0
    verdict: str = "lean_no"
    rationales: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)


JUDGE_SYSTEM = """You are an impartial hiring panel evaluator. Score the candidate on 5 dimensions, each 0.0–1.0, strictly from the transcript below. For each dimension, write ONE short sentence of rationale grounded in specific moments.

Return ONLY valid JSON with exactly this shape:
{
  "technical_depth":  {"score": 0.0, "rationale": "..."},
  "communication":    {"score": 0.0, "rationale": "..."},
  "problem_solving":  {"score": 0.0, "rationale": "..."},
  "fit":              {"score": 0.0, "rationale": "..."},
  "behavioral":       {"score": 0.0, "rationale": "..."}
}

Scoring guide:
- technical_depth: correctness and depth of technical answers; penalize vagueness, hand-waving, fabricated specifics.
- communication: clarity, structure, conciseness; penalize rambling or incoherence.
- problem_solving: approach to open-ended / design questions; look for trade-off thinking.
- fit: consistency between stated claims and resume + alignment with the JD requirements.
- behavioral: STAR-shaped answers, examples of ownership/collaboration/conflict handling.
"""


def _verdict_for(total: float) -> str:
    if total >= 0.80:
        return "strong_hire"
    if total >= 0.65:
        return "hire"
    if total >= 0.50:
        return "lean_no"
    return "no_hire"


def _coverage(state: InterviewState) -> dict:
    seen = {s: 0 for s in RUBRIC_SECTIONS}
    for a in state.assessment_log:
        if a.topic in seen:
            seen[a.topic] += 1
    return seen


def evaluate(
    state: InterviewState,
    resume_text: str,
    jd_text: str,
    client: genai.Client,
    model: str,
) -> EvaluationBreakdown:
    transcript_lines = []
    for msg in state.full_trajectory:
        role = "Recruiter" if msg["role"] == "recruiter" else "Candidate"
        transcript_lines.append(f"{role}: {msg['content']}")
    transcript = "\n\n".join(transcript_lines)

    user_prompt = (
        f"## Job Description\n{jd_text.strip()}\n\n"
        f"## Resume\n{resume_text.strip()}\n\n"
        f"## Interview Transcript\n{transcript}\n\n"
        "Return the JSON object described."
    )

    try:
        resp = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=JUDGE_SYSTEM,
                max_output_tokens=900,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        raw = resp.text or "{}"
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start:end + 1]) if start != -1 and end != -1 else {}
    except Exception as e:
        parsed = {}
        print(f"[warn] LLM judge failed: {e}")

    def _score(name: str) -> tuple[float, str]:
        entry = parsed.get(name, {}) if isinstance(parsed, dict) else {}
        try:
            s = float(entry.get("score", 0.0))
        except (TypeError, ValueError):
            s = 0.0
        s = max(0.0, min(1.0, s))
        return s, str(entry.get("rationale", "")).strip()

    td, td_r = _score("technical_depth")
    co, co_r = _score("communication")
    ps, ps_r = _score("problem_solving")
    ft, ft_r = _score("fit")
    bh, bh_r = _score("behavioral")

    total = (
        td * WEIGHTS["technical_depth"]
        + co * WEIGHTS["communication"]
        + ps * WEIGHTS["problem_solving"]
        + ft * WEIGHTS["fit"]
        + bh * WEIGHTS["behavioral"]
    )

    return EvaluationBreakdown(
        technical_depth=td,
        communication=co,
        problem_solving=ps,
        fit=ft,
        behavioral=bh,
        total=total,
        verdict=_verdict_for(total),
        rationales={
            "technical_depth": td_r,
            "communication": co_r,
            "problem_solving": ps_r,
            "fit": ft_r,
            "behavioral": bh_r,
        },
        coverage=_coverage(state),
    )


def write_report(
    state: InterviewState,
    evaluation: EvaluationBreakdown,
    candidate_name: str,
    job_title: str,
    resume_text: str,
    jd_text: str,
    resume_path: str,
    jd_path: str,
    out_dir: str = "interviews",
) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "_" for c in candidate_name.lower())[:40] or "candidate"
    path = Path(out_dir) / f"interview_{ts}_{slug}.md"

    lines = []
    lines.append(f"# Technical Interview — {candidate_name}")
    lines.append("")
    lines.append(f"**Date:** {ts}  ·  **Role:** {job_title}  ·  **Turns:** {state.turn_count}  ·  **Ended:** {state.termination_reason}")
    lines.append("")
    lines.append(f"- Resume: `{resume_path}`")
    lines.append(f"- Job description: `{jd_path}`")
    lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for msg in state.full_trajectory:
        role = "Recruiter" if msg["role"] == "recruiter" else "Candidate"
        lines.append(f"**{role}:** {msg['content']}")
        lines.append("")

    lines.append("## Recruiter's Running Assessment Log")
    lines.append("")
    if state.assessment_log:
        lines.append("| Turn | Topic | Score | Note |")
        lines.append("|---|---|---|---|")
        for a in state.assessment_log:
            note = a.note.replace("|", "\\|")
            lines.append(f"| {a.turn} | {a.topic} | {a.score:.2f} | {note} |")
    else:
        lines.append("_No assessments recorded._")
    lines.append("")

    lines.append("## Rubric Coverage")
    lines.append("")
    for topic, count in evaluation.coverage.items():
        marker = "✓" if count > 0 else "✗"
        lines.append(f"- {marker} **{topic}** — {count} assessment(s)")
    lines.append("")

    lines.append("## Final Evaluation")
    lines.append("")
    lines.append(f"- **Technical depth** (35%): {evaluation.technical_depth:.2f} — {evaluation.rationales.get('technical_depth', '')}")
    lines.append(f"- **Communication** (20%):   {evaluation.communication:.2f} — {evaluation.rationales.get('communication', '')}")
    lines.append(f"- **Problem solving** (20%): {evaluation.problem_solving:.2f} — {evaluation.rationales.get('problem_solving', '')}")
    lines.append(f"- **Fit (resume ↔ JD)** (15%): {evaluation.fit:.2f} — {evaluation.rationales.get('fit', '')}")
    lines.append(f"- **Behavioral** (10%):      {evaluation.behavioral:.2f} — {evaluation.rationales.get('behavioral', '')}")
    lines.append("")
    lines.append(f"### Composite: **{evaluation.total:.2f}** → Verdict: **{evaluation.verdict.upper()}**")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)

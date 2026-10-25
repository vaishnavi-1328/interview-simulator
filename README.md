# Two-Agent Technical Interview Simulation

A sibling project to `task-1`. Two LLM agents conduct a simulated ~1-hour technical interview end-to-end: a **technical recruiter** asks questions and probes follow-ups; a **candidate** answers from their resume. The full transcript and a rubric-based evaluation are written to a Markdown report.

## How it works

1. Drop a resume into `resumes/` (`.tex`, `.pdf`, `.md`, or `.txt`)
2. Drop a job description into `job_descriptions/` (same formats)
3. Run `python run_interview.py`

The recruiter must cover six rubric sections (intro, resume deep-dive, technical depth, system design / problem solving, behavioral, candidate questions). After every candidate answer the recruiter calls `record_assessment` to log a scored note. The interview ends when the recruiter emits `[END_INTERVIEW]` or `--max-turns` is reached (default 40 ≈ 1 hour).

A final LLM-judged evaluation scores the candidate on five dimensions (technical depth 35%, communication 20%, problem solving 20%, fit 15%, behavioral 10%) and renders a verdict: `strong_hire | hire | lean_no | no_hire`.

## Install

```
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Gemini API key:

```
GEMINI_API_KEY=your_key_here
```

Default model is `gemini-2.5-flash`. Override with `--model gemini-2.5-pro` for stronger reasoning.

## Run

```
python run_interview.py \
  --resume resumes/your_resume.tex \
  --jd job_descriptions/your_jd.md \
  --max-turns 40
```

With no flags it picks the first file in each folder.

## Output

The report lands at `interviews/interview_<timestamp>_<candidate>.md` with the transcript, assessment log, coverage checklist, and verdict.

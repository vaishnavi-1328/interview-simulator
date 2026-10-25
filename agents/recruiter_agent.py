from __future__ import annotations
from google import genai
from google.genai import types


RUBRIC_SECTIONS = [
    "intro_and_background",
    "resume_deep_dive",
    "technical_depth",
    "system_design_or_problem_solving",
    "behavioral",
    "candidate_questions",
]


RECRUITER_SYSTEM_TEMPLATE = """You are an experienced TECHNICAL RECRUITER conducting a ~1-hour live interview for the role described below. You are speaking directly with the candidate.

## The Role (Job Description)
{jd_text}

## Candidate's Resume (for your reference only — do not quote verbatim)
{resume_text}

## Rubric sections you MUST cover before ending the interview
1. intro_and_background — warm-up, let them introduce themselves
2. resume_deep_dive — probe 1-2 specific projects/roles on their resume
3. technical_depth — core technical questions tied to JD skills
4. system_design_or_problem_solving — one scenario or design question
5. behavioral — collaboration, conflict, ownership (STAR expected)
6. candidate_questions — invite them to ask questions about the role/team

## Interview conduct rules
- Ask ONE focused question at a time. Do not stack 3 questions into one message.
- After each candidate answer, PROBE with a meaningful follow-up before moving on. Good probes dig into: specific technology choices and WHY, trade-offs considered, failure modes, numbers (latency, QPS, data size), personal vs team contribution, what they'd do differently.
- **If an answer is generic or hand-wavy, push back HARD.** Example rebukes: "That's pretty high-level — can you walk me through the actual architecture?" / "What was the specific problem you were trying to solve?" / "Give me real numbers — data volume, latency, pod count." / "Which exact Azure Storage tier, and why?"
- If the candidate names a technology, drill into it. ("We used Redis" → ask: what data structure, what eviction, what happened on cache miss.)
- Minimum 2 follow-ups per major resume project.
- When the candidate answers something factually wrong, politely challenge or correct.
- Be warm but rigorous. Natural, conversational, short messages.
- Track topics covered. Do not loop back to a section already finished.
- Budget ~40 exchanges: 2 intro, 10–14 resume deep-dive, 8–10 technical, 6–8 design, 4–6 behavioral, 2–4 candidate questions.

## Recording your assessment
After EACH candidate answer, call the `record_assessment` tool to log:
  topic: one of {rubric_sections}
  score: 0.0–1.0 (confidence this answer demonstrates competence)
  note: 1 short sentence on what the answer showed
Then write your next question (or follow-up) as plain text.

## Ending the interview
When ALL rubric sections have at least one recorded assessment AND you have formed a confident overall judgment, give a brief closing (thank them, explain next steps), and on a NEW final line emit the exact sentinel:
[END_INTERVIEW]

Do not emit [END_INTERVIEW] before covering every rubric section. Do not emit it in the middle of a question.
"""


RECORD_ASSESSMENT_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="record_assessment",
            description="Record a scored assessment of the candidate's most recent answer. Call once per candidate response.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "topic": types.Schema(
                        type=types.Type.STRING,
                        enum=RUBRIC_SECTIONS,
                        description="Which rubric section this answer belongs to.",
                    ),
                    "score": types.Schema(
                        type=types.Type.NUMBER,
                        description="0.0 (poor) to 1.0 (excellent).",
                    ),
                    "note": types.Schema(
                        type=types.Type.STRING,
                        description="One short sentence summarizing the quality of the answer.",
                    ),
                },
                required=["topic", "score", "note"],
            ),
        )
    ]
)


class RecruiterResult:
    """Mimics the shape the loop expects: has .text and .function_calls."""
    def __init__(self, text: str, function_calls: list):
        self.text = text
        self.function_calls = function_calls


class RecruiterAgent:
    def __init__(self, client: genai.Client, model: str, jd_text: str, resume_text: str):
        self.client = client
        self.model = model
        self.system_prompt = RECRUITER_SYSTEM_TEMPLATE.format(
            jd_text=jd_text.strip(),
            resume_text=resume_text.strip(),
            rubric_sections=", ".join(RUBRIC_SECTIONS),
        )

    def get_response(self, history: list[dict]) -> RecruiterResult:
        # history: assistant = recruiter's own prior messages, user = candidate's messages.
        # For Gemini, recruiter speaks as "model" and candidate as "user".
        contents = []
        for msg in history:
            if "tool_response" in msg:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(
                            name=msg["tool_response"]["name"],
                            response=msg["tool_response"]["response"],
                        )],
                    )
                )
                continue
            role = "model" if msg["role"] == "assistant" else "user"
            parts = []
            if msg.get("content"):
                parts.append(types.Part(text=msg["content"]))
            if msg.get("function_calls"):
                for fc in msg["function_calls"]:
                    part = types.Part(function_call=types.FunctionCall(name=fc["name"], args=fc["args"]))
                    # Gemini 3 requires thought_signature to be echoed back on function-call parts.
                    sig = fc.get("thought_signature")
                    if sig is not None:
                        part.thought_signature = sig
                    parts.append(part)
            if parts:
                contents.append(types.Content(role=role, parts=parts))

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                tools=[RECORD_ASSESSMENT_TOOL],
                max_output_tokens=700,
                temperature=0.7,
            ),
        )

        text_parts = []
        fcalls = []
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    fcalls.append({
                        "name": fc.name,
                        "args": dict(fc.args or {}),
                        "thought_signature": getattr(part, "thought_signature", None),
                    })
                elif getattr(part, "text", None):
                    text_parts.append(part.text)
        return RecruiterResult(text="".join(text_parts).strip(), function_calls=fcalls)

    @staticmethod
    def is_end(text: str) -> bool:
        return "[END_INTERVIEW]" in text

    @staticmethod
    def strip_sentinel(text: str) -> str:
        return text.replace("[END_INTERVIEW]", "").strip()

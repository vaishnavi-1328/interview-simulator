from __future__ import annotations
from agents.recruiter_agent import RecruiterAgent, RUBRIC_SECTIONS
from agents.candidate_agent import CandidateAgent
from core.state import InterviewState, AssessmentRecord


class InterviewLoop:
    def __init__(
        self,
        recruiter: RecruiterAgent,
        candidate: CandidateAgent,
        state: InterviewState,
        max_turns: int = 40,
        verbose: bool = True,
    ):
        self.recruiter = recruiter
        self.candidate = candidate
        self.state = state
        self.max_turns = max_turns
        self.verbose = verbose

    def run(self, opening: str) -> InterviewState:
        self._add_recruiter_opening(opening)
        if self.verbose:
            print(f"\n[Recruiter]: {opening}")

        while not self.state.terminated:
            candidate_text = self.candidate.get_response(self.state.candidate_history)
            self._record_candidate_message(candidate_text)
            if self.verbose:
                print(f"\n[Candidate]: {candidate_text}")

            self.state.turn_count += 1
            if self.state.turn_count >= self.max_turns:
                self.state.terminated = True
                self.state.termination_reason = "max_turns"
                break

            recruiter_text = self._run_recruiter_turn()
            if self.verbose:
                print(f"\n[Recruiter]: {recruiter_text}")

            if RecruiterAgent.is_end(recruiter_text):
                cleaned = RecruiterAgent.strip_sentinel(recruiter_text)
                self._record_recruiter_message(cleaned)
                self.state.terminated = True
                self.state.termination_reason = "recruiter_satisfied"
                break

            self._record_recruiter_message(recruiter_text)

        if self.verbose:
            print(f"\n[Interview ended: {self.state.termination_reason}] after {self.state.turn_count} turns")

        return self.state

    def _run_recruiter_turn(self) -> str:
        """Resolve any function calls (record_assessment), then return final text."""
        for _ in range(5):
            result = self.recruiter.get_response(self.state.recruiter_history)

            if result.function_calls:
                self.state.recruiter_history.append({
                    "role": "assistant",
                    "content": result.text or "",
                    "function_calls": result.function_calls,
                })
                for fc in result.function_calls:
                    response = self._handle_tool_call(fc["name"], fc["args"])
                    self.state.recruiter_history.append({
                        "tool_response": {"name": fc["name"], "response": response},
                    })
                    if self.verbose:
                        print(f"\n  [Assessment] {fc['name']}({fc['args']})")
                if result.text:
                    return result.text
                continue

            text = result.text or "Let's continue — can you tell me more about your most recent role?"
            return text

        return "Let's keep going. What else would you like to walk me through?"

    def _handle_tool_call(self, name: str, args: dict) -> dict:
        if name == "record_assessment":
            topic = str(args.get("topic", "")).strip()
            if topic not in RUBRIC_SECTIONS:
                return {"success": False, "error": f"topic must be one of {RUBRIC_SECTIONS}"}
            try:
                score = float(args.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))
            note = str(args.get("note", "")).strip()
            record = AssessmentRecord(
                turn=self.state.turn_count,
                topic=topic,
                score=score,
                note=note,
            )
            self.state.assessment_log.append(record)
            return {"success": True, "recorded": True}
        return {"success": False, "error": f"unknown tool {name}"}

    def _add_recruiter_opening(self, text: str) -> None:
        msg = {"role": "assistant", "content": text}
        self.state.recruiter_history.append(msg)
        self.state.candidate_history.append(msg)
        self.state.full_trajectory.append({"role": "recruiter", "content": text})

    def _record_recruiter_message(self, text: str) -> None:
        self.state.recruiter_history.append({"role": "assistant", "content": text})
        self.state.candidate_history.append({"role": "assistant", "content": text})
        self.state.full_trajectory.append({"role": "recruiter", "content": text})

    def _record_candidate_message(self, text: str) -> None:
        msg = {"role": "user", "content": text}
        self.state.recruiter_history.append(msg)
        self.state.candidate_history.append(msg)
        self.state.full_trajectory.append({"role": "candidate", "content": text})

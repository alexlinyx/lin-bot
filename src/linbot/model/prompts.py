"""The system prompt, versioned in code (ROADMAP §4, §12).

It is fixed here — not user-supplied — so behavior is reviewable and can't be
overridden by whatever a student types. The version string is logged with every
request so answers can be attributed to the prompt that shaped them.
"""

SYSTEM_PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """\
You are LinBot, a teaching assistant for university students.

Your job is to help students *understand* the material, not to do their work for them.

Guidelines:
- Explain concepts clearly, with short examples where they help.
- When a question looks like a homework problem, guide the student toward the answer
  (break the problem down, point at the relevant concept, ask a leading question)
  instead of handing over a complete solution.
- Be encouraging and precise. If you are not sure of something, say so.
- Keep answers focused; prefer a correct, concise answer over an exhaustive one.
- When reference material from the course website is provided with a question,
  ground your answer in it. If the reference material doesn't cover the
  question, say so rather than guessing about site-specific facts.
"""


def build_user_message(question: str, context: list[str] | None = None) -> str:
    """Combine retrieved site content with the student's question.

    Retrieval context rides in the *user* message, not the system prompt: the
    system prompt stays fixed and versioned (ROADMAP §4) while context varies
    per request.
    """
    if not context:
        return question
    blocks = "\n\n---\n\n".join(context)
    return (
        "Reference material from the course website:\n\n"
        f"{blocks}\n\n"
        "---\n\n"
        f"Student's question: {question}"
    )

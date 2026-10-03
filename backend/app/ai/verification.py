"""Verification Agent.

1. Chooses questions whose answers are NOT visible in the public report, based on
   the item category and the finder's private notes.
2. Produces an *advisory* consistency score for the finder. It never accepts or
   rejects on its own; the finder (a human holding the item) decides.
"""

import re

from app.ai.providers import cosine, get_text_embedder
from app.ai.providers.text import tokenize
from app.ai.understanding import normalize_category

GENERIC_HIDDEN = {
    "id": "hidden_feature",
    "question": "Describe a unique mark, scratch, sticker or other detail that is not mentioned in the public report.",
    "evidence_type": "hidden_feature",
}

BY_GROUP = {
    "bags": [{"id": "contents", "question": "What was inside the bag? List as many items as you can.",
              "evidence_type": "contents"}],
    "wallets": [{"id": "contents", "question": "What was inside (cards, number of notes, photos, etc.)? "
                 "Do not give full card numbers.", "evidence_type": "contents"}],
    "electronics": [
        {"id": "appearance", "question": "Describe the case/cover, wallpaper or lock screen, or any accessories attached.",
         "evidence_type": "private_description"},
        {"id": "serial", "question": "Optional: the last 4 characters of the serial number or IMEI (never the full number).",
         "evidence_type": "serial_number", "optional": True},
    ],
    "keys": [{"id": "contents", "question": "How many keys are there, and what is attached to the ring?",
              "evidence_type": "contents"}],
    "documents": [{"id": "private", "question": "What name and which institution/issuer appear on the document? "
                   "Do not share full ID numbers.", "evidence_type": "private_description"}],
    "accessories": [{"id": "appearance", "question": "Describe the clasp, strap, engraving or packaging in detail.",
                     "evidence_type": "private_description"}],
}

MAX_ANSWER_LEN = 1000


def build_questions(found_report) -> list[dict]:
    group = normalize_category(f"{found_report.category} {found_report.name}")[1]
    questions = list(BY_GROUP.get(group, []))
    questions.append(GENERIC_HIDDEN)
    return questions[:3]


def _sensitive_number(text: str) -> bool:
    return re.search(r"\d{9,}", text.replace(" ", "").replace("-", "")) is not None


def evaluate_answers(found_report, questions: list[dict], answers: dict[str, str]) -> tuple[float, list[str]]:
    """Compare answers with the finder's private + public knowledge of the item.

    Returns (advisory score 0..1, notes for the finder). Notes never quote private details.
    """
    reference = " ".join(filter(None, [found_report.private_details, found_report.distinctive_features,
                                       found_report.description]))
    private_ref = found_report.private_details or ""
    public_ref = " ".join(filter(None, [found_report.description, found_report.distinctive_features,
                                        found_report.name, found_report.color, found_report.brand]))
    embed = get_text_embedder().embed
    notes: list[str] = []

    answered = {q["id"]: (answers.get(q["id"]) or "").strip() for q in questions}
    required = [q for q in questions if not q.get("optional")]
    if not any(answered[q["id"]] for q in required):
        return 0.0, ["The owner did not answer the required questions."]

    all_answers = " ".join(a for a in answered.values() if a)
    sim_all = cosine(embed(all_answers), embed(reference)) if reference.strip() else 0.0

    ans_tokens = set(tokenize(all_answers))
    private_tokens = set(tokenize(private_ref)) - set(tokenize(public_ref))
    hidden_overlap = len(ans_tokens & private_tokens) / len(private_tokens) if private_tokens else None

    if hidden_overlap is not None:
        score = 0.6 * hidden_overlap + 0.4 * sim_all
        if hidden_overlap >= 0.3:
            notes.append("Answers mention details from your private notes that are not in the public report.")
        else:
            notes.append("Answers do not clearly mention the details in your private notes.")
    else:
        score = sim_all
        notes.append("You did not add private notes, so please compare the answers with the item yourself.")

    public_only = ans_tokens and ans_tokens <= set(tokenize(public_ref))
    if public_only:
        score *= 0.5
        notes.append("Answers only repeat information that is already public.")
    if _sensitive_number(all_answers):
        notes.append("An answer contains a long number. Never ask for full card or ID numbers.")

    notes.append("This score is advisory only. You decide whether the answers match the item.")
    return round(min(1.0, score), 3), notes

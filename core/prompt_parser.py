"""Turns a free-form Slack message into a structured image-generation prompt.

Input example:  "@memorylane my 5-year-old self on a beach at sunset"
Output example: PhotoRequest(age_in_years=5, scene="on a beach at sunset", ...)

The parser is deliberately simple and rule-based. It is the piece most likely to
be swapped for an LLM call later, so it is isolated behind one function.
"""

import re
from dataclasses import dataclass
from typing import Optional

# "5-year-old", "5 year old", "5yo", "5 y/o", "age 5", "aged 5"
_AGE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s*[-\s]?\s*year[-\s]?old\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*y\.?\s*/?\s*o\.?\b", re.IGNORECASE),
    re.compile(r"\bage[d]?\s*(?:of\s*)?(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bat\s+(\d{1,2})\b", re.IGNORECASE),
]

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17,
}
_WORD_AGE_PATTERN = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")\s*[-\s]?\s*year[-\s]?old\b",
    re.IGNORECASE,
)

# An age expressed any of the ways we accept, e.g. "5-year-old", "5yo", "ten year old".
_AGE_PHRASE = (
    r"(?:\d{1,2}\s*[-\s]?\s*year[-\s]?old"
    r"|\d{1,2}\s*y\.?\s*/?\s*o\.?"
    r"|(?:" + "|".join(_WORD_NUMBERS) + r")\s*[-\s]?\s*year[-\s]?old)"
)
_CHILD_NOUNS = r"(?:toddler|baby|infant|kid|child|teenager|teen|boy|girl)\b"

# Slack markup that carries no scene information.
_SLACK_MARKUP_PATTERNS = [
    re.compile(r"<@[UW][A-Z0-9]+>", re.IGNORECASE),       # user mentions
    re.compile(r"<#C[A-Z0-9]+\|[^>]*>", re.IGNORECASE),   # channel links
    re.compile(r"<(https?://[^|>]+)(?:\|[^>]*)?>", re.IGNORECASE),  # links
]

# The "who" of the request. Removed as whole phrases so that an unrelated "my"
# (as in "my house's backyard") survives into the scene description.
_SUBJECT_PHRASE_PATTERNS = [
    re.compile(
        rf"\b(?:my|me|myself)\s+(?:own\s+)?(?:as\s+)?(?:a\s+|an\s+)?"
        rf"{_AGE_PHRASE}(?:\s+(?:self|selfie|{_CHILD_NOUNS}))?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:my|me|myself)\s+(?:own\s+)?(?:as\s+)?(?:a\s+|an\s+)?"
        rf"{_CHILD_NOUNS}(?:\s+self)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|me|myself)\s+(?:younger|childhood|child|little|young|"
        r"toddler)?\s*self(?:ie)?",
        re.IGNORECASE,
    ),
    re.compile(rf"\bme\s+(?:at|aged?)\s+(?:age\s+)?\d{{1,2}}\b", re.IGNORECASE),
    re.compile(rf"\bas\s+(?:a\s+|an\s+)?{_AGE_PHRASE}", re.IGNORECASE),
    re.compile(_AGE_PHRASE, re.IGNORECASE),
    re.compile(r"\bat\s+age\s+\d{1,2}\b", re.IGNORECASE),
    re.compile(r"\bage[d]?\s*(?:of\s*)?\d{1,2}\b", re.IGNORECASE),
]

# Politeness and command framing.
_COMMAND_NOISE_PATTERNS = [
    re.compile(
        r"\b(please|pls|plz|hey|hi|hello|thanks|thank you|can you|could you|"
        r"would you|i want|i would like|i'd like|id like|generate|create|"
        r"make|draw|render|show me|give me|send me)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:a|an|the)?\s*(?:photo|picture|image|pic|shot|portrait)\s+of\b",
        re.IGNORECASE,
    ),
]

MINIMUM_SCENE_LENGTH = 3
DEFAULT_AGE_IN_YEARS = 6
YOUNGEST_SUPPORTED_AGE = 1
OLDEST_SUPPORTED_AGE = 17


@dataclass(frozen=True)
class PhotoRequest:
    """A validated, ready-to-render childhood photo request."""

    original_text: str
    age_in_years: int
    age_was_specified: bool
    scene: str
    generation_prompt: str


class UnparseableRequestError(ValueError):
    """Raised when the message does not contain enough detail to render."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _extract_age(text: str) -> Optional[int]:
    for pattern in _AGE_PATTERNS:
        match = pattern.search(text)
        if match:
            age = int(match.group(1))
            if YOUNGEST_SUPPORTED_AGE <= age <= OLDEST_SUPPORTED_AGE:
                return age
    word_match = _WORD_AGE_PATTERN.search(text)
    if word_match:
        return _WORD_NUMBERS[word_match.group(1).lower()]
    return None


def _extract_scene(text: str) -> str:
    """Strip away everything that describes *who* is in the photo, leaving
    only the description of *where and what* — the scene."""
    scene = text
    for pattern_group in (
        _SLACK_MARKUP_PATTERNS,
        _COMMAND_NOISE_PATTERNS,
        _SUBJECT_PHRASE_PATTERNS,
    ):
        for pattern in pattern_group:
            scene = pattern.sub(" ", scene)
    scene = re.sub(r"\s+", " ", scene)
    scene = re.sub(r"\s+([,.!?])", r"\1", scene)
    return scene.strip(" ,.-!?:;")


def _describe_age(age_in_years: int) -> str:
    if age_in_years <= 2:
        return f"a {age_in_years}-year-old toddler"
    if age_in_years <= 5:
        return f"a {age_in_years}-year-old young child"
    if age_in_years <= 12:
        return f"a {age_in_years}-year-old child"
    return f"a {age_in_years}-year-old teenager"


def build_generation_prompt(
    trigger_word: str, age_in_years: int, scene: str
) -> str:
    """Compose the final text prompt sent to the Flux LoRA.

    The trigger word must appear early: it is the token the LoRA was trained
    against, and it is what pulls the subject's likeness into the image.
    """
    return (
        f"A candid photograph of {trigger_word} as {_describe_age(age_in_years)}, "
        f"{scene}. "
        f"Nostalgic amateur family photo, natural lighting, soft film grain, "
        f"slightly faded colours, shot on 35mm film, authentic and unposed."
    )


def parse_photo_request(message_text: str, trigger_word: str) -> PhotoRequest:
    """Parse a Slack message into a PhotoRequest.

    Raises UnparseableRequestError if there is no usable scene description.
    """
    if not message_text or not message_text.strip():
        raise UnparseableRequestError("The message was empty.")

    cleaned_text = message_text.strip()
    age_in_years = _extract_age(cleaned_text)
    scene = _extract_scene(cleaned_text)

    if len(scene) < MINIMUM_SCENE_LENGTH:
        raise UnparseableRequestError(
            "I could not find a scene to draw in that message."
        )

    resolved_age = age_in_years or DEFAULT_AGE_IN_YEARS
    return PhotoRequest(
        original_text=cleaned_text,
        age_in_years=resolved_age,
        age_was_specified=age_in_years is not None,
        scene=scene,
        generation_prompt=build_generation_prompt(
            trigger_word, resolved_age, scene
        ),
    )

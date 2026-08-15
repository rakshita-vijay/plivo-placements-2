import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.prompt_parser import (  # noqa: E402
    DEFAULT_AGE_IN_YEARS,
    UnparseableRequestError,
    parse_photo_request,
)

TRIGGER_WORD = "TOK"


@pytest.mark.parametrize(
    "message_text, expected_age, expected_scene",
    [
        ("<@U0BOT> my 5-year-old self on a beach", 5, "on a beach"),
        ("my 2 year old self in my house's backyard", 2, "in my house's backyard"),
        ("my 10-year-old self in a classroom", 10, "in a classroom"),
        ("my 4yo self holding a puppy", 4, "holding a puppy"),
        ("me at 7 playing cricket in a dusty street", 7,
         "playing cricket in a dusty street"),
        ("my ten-year-old self riding a bicycle", 10, "riding a bicycle"),
        ("please generate a photo of my 12-year-old self at a science fair",
         12, "at a science fair"),
        ("my childhood self at my grandmother's house", DEFAULT_AGE_IN_YEARS,
         "at my grandmother's house"),
    ],
)
def test_age_and_scene_extraction(message_text, expected_age, expected_scene):
    request = parse_photo_request(message_text, TRIGGER_WORD)
    assert request.age_in_years == expected_age
    assert request.scene == expected_scene


def test_prompt_contains_trigger_word_and_scene():
    request = parse_photo_request("my 5-year-old self on a beach", TRIGGER_WORD)
    assert TRIGGER_WORD in request.generation_prompt
    assert "on a beach" in request.generation_prompt
    assert "5-year-old" in request.generation_prompt


def test_missing_age_falls_back_to_default_and_flags_it():
    request = parse_photo_request("my younger self flying a kite", TRIGGER_WORD)
    assert request.age_in_years == DEFAULT_AGE_IN_YEARS
    assert request.age_was_specified is False


def test_implausible_ages_are_ignored():
    # 45 is outside the childhood range, so it is not treated as the subject age.
    request = parse_photo_request("my 45-year-old self on a beach", TRIGGER_WORD)
    assert request.age_in_years == DEFAULT_AGE_IN_YEARS


@pytest.mark.parametrize("bad_input", ["", "   ", "<@U0BOT>", "<@U0BOT> my self"])
def test_unusable_messages_raise(bad_input):
    with pytest.raises(UnparseableRequestError):
        parse_photo_request(bad_input, TRIGGER_WORD)

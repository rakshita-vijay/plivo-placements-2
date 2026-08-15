"""Replicate API error translation."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import replicate

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from replicate_client.inference import (  # noqa: E402
    FluxLoraInferenceClient,
    ReplicateInferenceError,
    ReplicateRateLimitError,
)


def make_client():
    with patch("replicate_client.inference.Client"):
        return FluxLoraInferenceClient(
            "token", "owner/model:abc123", poll_interval_seconds=0.01
        )


def api_error(status, detail):
    error = replicate.exceptions.ReplicateError(status=status, detail=detail)
    return error


def test_rate_limit_raises_its_own_type():
    client = make_client()
    client.client.predictions.create.side_effect = api_error(429, "slow down")
    with pytest.raises(ReplicateRateLimitError):
        client.generate_image("a prompt")


@pytest.mark.parametrize(
    "status, expected_phrase",
    [
        (401, "REPLICATE_API_TOKEN"),
        (402, "out of credit"),
        (404, "LORA_MODEL_VERSION"),
        (422, "rejected the inputs"),
        (500, "rejected the request"),
    ],
)
def test_api_errors_become_actionable_messages(status, expected_phrase):
    client = make_client()
    client.client.predictions.create.side_effect = api_error(status, "detail here")
    with pytest.raises(ReplicateInferenceError) as caught:
        client.generate_image("a prompt")
    assert expected_phrase in str(caught.value)


def test_rate_limit_while_polling_does_not_abandon_the_prediction():
    client = make_client()
    prediction = MagicMock()
    prediction.id = "pred_1"
    prediction.status = "processing"
    prediction.output = None

    reload_results = [api_error(429, "slow down"), None]

    def reload_side_effect():
        result = reload_results.pop(0) if reload_results else None
        if isinstance(result, Exception):
            raise result
        prediction.status = "succeeded"
        prediction.output = ["https://cdn/out.jpg"]

    prediction.reload.side_effect = reload_side_effect
    client.client.predictions.create.return_value = prediction

    generated = client.generate_image("a prompt")
    assert generated.image_url == "https://cdn/out.jpg"
    assert prediction.reload.call_count == 2

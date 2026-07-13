from medexa.adapters.bedrock.model_resolver import bedrock_model_candidates


def test_bedrock_model_candidates_adds_us_prefix() -> None:
    ids = bedrock_model_candidates("anthropic.claude-3-5-sonnet-20240620-v1:0")
    assert ids[0] == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert "us.anthropic.claude-3-5-sonnet-20240620-v1:0" in ids


def test_bedrock_model_candidates_strips_us_prefix_fallback() -> None:
    ids = bedrock_model_candidates("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert ids[0].startswith("us.")
    assert "anthropic.claude-haiku-4-5-20251001-v1:0" in ids

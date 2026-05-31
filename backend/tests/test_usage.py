from app.worker.usage import Usage, extract_usage, UsageAccumulator


def test_extract_openai_shape():
    u = extract_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (10, 5, 15)
    assert u.cost is None


def test_extract_openrouter_cost():
    u = extract_usage({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": 0.00042}})
    assert u.cost == 0.00042


def test_extract_ollama_eval_counts_when_no_usage():
    u = extract_usage({"prompt_eval_count": 7, "eval_count": 9})
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (7, 9, 16)
    assert u.cost is None


def test_extract_missing_usage_is_zeros_none():
    u = extract_usage({"choices": [{"message": {"content": "hi"}}]})
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens, u.cost) == (0, 0, 0, None)


def test_extract_handles_garbage_without_raising():
    u = extract_usage({"usage": "not-a-dict"})
    assert (u.total_tokens, u.cost) == (0, None)


def test_accumulator_sums_tokens_and_cost_when_all_report():
    acc = UsageAccumulator()
    acc.add(Usage(10, 5, 15, 0.001))
    acc.add(Usage(2, 3, 5, 0.0005))
    assert acc.prompt_tokens == 12 and acc.completion_tokens == 8 and acc.total_tokens == 20
    assert acc.cost == 0.0015


def test_accumulator_cost_becomes_none_after_any_missing():
    acc = UsageAccumulator()
    acc.add(Usage(1, 1, 2, 0.01))
    acc.add(Usage(1, 1, 2, None))
    acc.add(Usage(1, 1, 2, 0.02))
    assert acc.total_tokens == 6
    assert acc.cost is None


def test_accumulator_empty_cost_is_none():
    assert UsageAccumulator().cost is None

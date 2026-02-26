from core.analysis.rag_eval import evaluate_retrieval_cases


def test_evaluate_retrieval_cases_metrics():
    cases = [
        {"id": "c1", "query": "휴일 주말 규정", "expected_articles": ["제39조"]},
        {"id": "c2", "query": "한도 초과 규정", "expected_articles": ["제40조"]},
        {"id": "c3", "query": "없는 질의", "expected_articles": ["제99조"]},
    ]

    def _retrieve(q: str, top_k: int):
        if "휴일" in q:
            return [{"regulation_article": "제39조"}]
        if "한도" in q:
            return [{"regulation_article": "제41조"}, {"regulation_article": "제40조"}]
        return []

    out = evaluate_retrieval_cases(cases, retrieve_fn=_retrieve, top_k=5)
    assert out["total_cases"] == 3
    assert out["zero_results"] == 1
    assert out["zero_rate"] == round(1 / 3, 4)
    assert out["hit_at_k"] == round(2 / 3, 4)
    assert out["strict_hit_top1"] == round(1 / 3, 4)

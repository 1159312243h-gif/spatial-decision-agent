from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from practice.site_selection import ProjectType
from practice.site_selection.policy_rag import (
    PolicyDocument,
    PolicyHybridRetriever,
    PolicySection,
    chunk_policy_documents,
    load_policy_corpus,
)


FIXTURE_PATH = Path(__file__).parents[1] / "data" / "fixtures" / "policies.json"


class KeywordEmbeddingProvider:
    terms = ("生态", "轨道", "物流")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(text.count(term)) for term in self.terms]
            for text in texts
        ]


def documents() -> list[PolicyDocument]:
    return [
        PolicyDocument(
            policy_id="FIXTURE-POLICY-001",
            title="合成测试空间保护规则",
            issuing_authority="测试机构",
            document_number="FIXTURE-001",
            version="fixture-1.0",
            jurisdiction="测试行政区",
            source_uri="fixture://policies/spatial-protection",
            applicable_project_types=[
                ProjectType.SHOPPING_MALL,
                ProjectType.LOGISTICS_PARK,
            ],
            sections=[
                PolicySection(
                    clause="第三条（合成测试）",
                    page_number=2,
                    text="候选地块涉及生态保护空间时，应进入人工复核流程。",
                )
            ],
        ),
        PolicyDocument(
            policy_id="FIXTURE-POLICY-002",
            title="合成测试商业设施指引",
            issuing_authority="测试机构",
            version="fixture-1.0",
            jurisdiction="测试行政区",
            source_uri="fixture://policies/commercial-access",
            applicable_project_types=[ProjectType.SHOPPING_MALL],
            sections=[
                PolicySection(
                    clause="第五条（合成测试）",
                    page_number=4,
                    text="商业设施分析可以记录轨道交通站点距离作为软指标。",
                )
            ],
        ),
        PolicyDocument(
            policy_id="FIXTURE-POLICY-003",
            title="合成测试物流设施指引",
            issuing_authority="测试机构",
            version="fixture-1.0",
            jurisdiction="另一测试区",
            source_uri="fixture://policies/logistics-access",
            applicable_project_types=[ProjectType.LOGISTICS_PARK],
            sections=[
                PolicySection(
                    clause="第六条（合成测试）",
                    text="物流设施分析可以记录高速出入口距离。",
                )
            ],
        ),
    ]


def test_chunking_preserves_auditable_policy_metadata() -> None:
    chunks = chunk_policy_documents(documents(), max_chars=100, overlap_chars=10)

    first = chunks[0]
    assert first.policy_id == "FIXTURE-POLICY-001"
    assert first.clause == "第三条（合成测试）"
    assert first.page_number == 2
    assert first.source_uri == "fixture://policies/spatial-protection"
    assert first.to_policy_reference().document_number == "FIXTURE-001"


def test_hybrid_search_returns_locatable_citation() -> None:
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(documents()),
        KeywordEmbeddingProvider(),
    )

    results = retriever.search(
        "地块碰到生态保护空间如何处理",
        project_type=ProjectType.SHOPPING_MALL,
        jurisdiction="测试行政区",
        top_k=2,
    )

    assert results[0].citation.policy_id == "FIXTURE-POLICY-001"
    assert results[0].citation.clause == "第三条（合成测试）"
    assert results[0].citation.page_number == 2
    assert results[0].citation.quote
    assert results[0].sparse_rank == 1
    assert results[0].vector_rank == 1


def test_search_filters_project_type_and_jurisdiction() -> None:
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(documents()),
        KeywordEmbeddingProvider(),
    )

    results = retriever.search(
        "物流高速",
        project_type=ProjectType.SHOPPING_MALL,
        jurisdiction="另一测试区",
    )

    assert results == []


def test_chunking_splits_long_section_with_overlap() -> None:
    document = documents()[0].model_copy(deep=True)
    document.sections[0].text = "生态保护空间。" * 40

    chunks = chunk_policy_documents(
        [document],
        max_chars=100,
        overlap_chars=20,
    )

    assert len(chunks) > 1
    assert chunks[1].char_start < chunks[0].char_end
    assert all(len(chunk.content) <= 100 for chunk in chunks)


def test_retriever_rejects_invalid_embedding_contract() -> None:
    class WrongCountProvider:
        def embed(self, texts):
            return [[1.0]]

    with pytest.raises(ValueError, match="数量"):
        PolicyHybridRetriever(
            chunk_policy_documents(documents()),
            WrongCountProvider(),
        )


def test_search_rejects_blank_query_and_invalid_top_k() -> None:
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(documents()),
        KeywordEmbeddingProvider(),
    )

    with pytest.raises(ValueError, match="不能为空"):
        retriever.search(" ", project_type=ProjectType.SHOPPING_MALL)
    with pytest.raises(ValueError, match="top_k"):
        retriever.search(
            "生态",
            project_type=ProjectType.SHOPPING_MALL,
            top_k=0,
        )


def test_policy_fixture_corpus_is_explicit_and_loadable() -> None:
    corpus = load_policy_corpus(FIXTURE_PATH)

    assert corpus.is_fixture is True
    assert corpus.version == "fixture-2026.08.1"
    assert len(corpus.documents) == 3
    assert all(
        document.source_uri.startswith("fixture://")
        for document in corpus.documents
    )

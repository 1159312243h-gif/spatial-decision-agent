from practice.site_selection import (
    PolicyHybridRetriever,
    chunk_policy_documents,
)
from practice.site_selection.mcp_tools import create_site_selection_tool_registry
from tests.test_policy_rag import KeywordEmbeddingProvider, documents
from tests.test_site_selection_mcp_tools import FakePOIReader, FakeSpatialBackend


def test_policy_retriever_is_exposed_as_optional_sixth_mcp_tool() -> None:
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(documents()),
        KeywordEmbeddingProvider(),
    )
    tools = create_site_selection_tool_registry(
        FakeSpatialBackend(),
        FakePOIReader(),
        policy_retriever=retriever,
    )

    result = tools.execute(
        "policy_search",
        {
            "query": "生态保护空间如何处理",
            "project_type": "shopping_mall",
            "jurisdiction": "测试行政区",
            "top_k": 2,
        },
    )

    assert len(tools.names) == 6
    assert result["result_count"] == 2
    assert result["results"][0]["citation"]["policy_id"] == (
        "FIXTURE-POLICY-001"
    )

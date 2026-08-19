from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType
from .rules import PolicyReference


class PolicyEmbeddingProvider(Protocol):
    """Embedding boundary; production code must inject a reviewed provider."""

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class PolicySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause: NonEmptyString
    text: NonEmptyString
    page_number: int | None = Field(default=None, ge=1)


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: NonEmptyString
    title: NonEmptyString
    issuing_authority: NonEmptyString
    document_number: NonEmptyString | None = None
    version: NonEmptyString
    jurisdiction: NonEmptyString
    source_uri: NonEmptyString
    applicable_project_types: list[ProjectType] = Field(min_length=1)
    sections: list[PolicySection] = Field(min_length=1)

    @field_validator("applicable_project_types")
    @classmethod
    def project_types_are_unique(
        cls,
        values: list[ProjectType],
    ) -> list[ProjectType]:
        if len(values) != len(set(values)):
            raise ValueError("政策适用项目类型不能重复")
        return values

    @model_validator(mode="after")
    def section_clauses_are_unique(self) -> PolicyDocument:
        clauses = [section.clause for section in self.sections]
        if len(clauses) != len(set(clauses)):
            raise ValueError("同一政策文档的条款标签不能重复")
        return self


class PolicyCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: NonEmptyString
    version: NonEmptyString
    updated_at: datetime
    is_fixture: bool = False
    documents: list[PolicyDocument] = Field(min_length=1)

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("政策语料更新时间必须包含时区")
        return value

    @model_validator(mode="after")
    def policy_ids_are_unique(self) -> PolicyCorpus:
        policy_ids = [document.policy_id for document in self.documents]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("政策语料 policy_id 不能重复")
        if self.is_fixture and any(
            not document.source_uri.startswith("fixture://")
            for document in self.documents
        ):
            raise ValueError("Fixture 政策语料必须使用 fixture:// 来源")
        return self


def load_policy_corpus(path: str | Path) -> PolicyCorpus:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PolicyCorpus.model_validate(payload)


class PolicyChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: NonEmptyString
    policy_id: NonEmptyString
    title: NonEmptyString
    issuing_authority: NonEmptyString
    document_number: NonEmptyString | None = None
    clause: NonEmptyString
    version: NonEmptyString
    jurisdiction: NonEmptyString
    source_uri: NonEmptyString
    applicable_project_types: list[ProjectType] = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    content: NonEmptyString
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> PolicyChunk:
        if self.char_end <= self.char_start:
            raise ValueError("政策切块字符区间无效")
        return self

    def to_policy_reference(self) -> PolicyReference:
        return PolicyReference(
            policy_id=self.policy_id,
            title=self.title,
            issuing_authority=self.issuing_authority,
            document_number=self.document_number,
            clause=self.clause,
            version=self.version,
            jurisdiction=self.jurisdiction,
            source_uri=self.source_uri,
        )


class PolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: NonEmptyString
    policy_id: NonEmptyString
    title: NonEmptyString
    issuing_authority: NonEmptyString
    document_number: NonEmptyString | None = None
    clause: NonEmptyString
    version: NonEmptyString
    jurisdiction: NonEmptyString
    source_uri: NonEmptyString
    page_number: int | None = Field(default=None, ge=1)
    quote: NonEmptyString


class PolicySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation: PolicyCitation
    fused_score: float = Field(gt=0)
    sparse_rank: int | None = Field(default=None, ge=1)
    vector_rank: int | None = Field(default=None, ge=1)


def chunk_policy_documents(
    documents: Iterable[PolicyDocument],
    *,
    max_chars: int = 500,
    overlap_chars: int = 80,
) -> list[PolicyChunk]:
    """Split structured policy sections while preserving citation metadata."""

    if max_chars < 100:
        raise ValueError("政策切块 max_chars 不能小于 100")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("政策切块 overlap_chars 必须在 [0, max_chars) 内")

    chunks: list[PolicyChunk] = []
    seen_policy_ids: set[str] = set()
    for document in documents:
        if document.policy_id in seen_policy_ids:
            raise ValueError(f"政策文档编号重复：{document.policy_id}")
        seen_policy_ids.add(document.policy_id)
        for section_index, section in enumerate(document.sections, start=1):
            for chunk_index, (start, end, content) in enumerate(
                _split_section(
                    section.text,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                ),
                start=1,
            ):
                chunks.append(
                    PolicyChunk(
                        chunk_id=(
                            f"{document.policy_id}:s{section_index}:c{chunk_index}"
                        ),
                        policy_id=document.policy_id,
                        title=document.title,
                        issuing_authority=document.issuing_authority,
                        document_number=document.document_number,
                        clause=section.clause,
                        version=document.version,
                        jurisdiction=document.jurisdiction,
                        source_uri=document.source_uri,
                        applicable_project_types=(
                            document.applicable_project_types
                        ),
                        page_number=section.page_number,
                        content=content,
                        char_start=start,
                        char_end=end,
                    )
                )
    if not chunks:
        raise ValueError("政策语料至少需要一个可检索切块")
    return chunks


class PolicyHybridRetriever:
    """BM25 + vector retrieval combined with reciprocal-rank fusion."""

    def __init__(
        self,
        chunks: Sequence[PolicyChunk],
        embedding_provider: PolicyEmbeddingProvider,
        *,
        sparse_weight: float = 1,
        vector_weight: float = 1,
        rrf_k: int = 60,
    ) -> None:
        if not chunks:
            raise ValueError("混合检索至少需要一个政策切块")
        if embedding_provider is None:
            raise ValueError("混合检索必须显式配置 EmbeddingProvider")
        if sparse_weight <= 0 or vector_weight <= 0:
            raise ValueError("混合检索权重必须大于 0")
        if rrf_k <= 0:
            raise ValueError("RRF k 必须大于 0")

        self._chunks = [chunk.model_copy(deep=True) for chunk in chunks]
        self._embedding_provider = embedding_provider
        self._sparse_weight = sparse_weight
        self._vector_weight = vector_weight
        self._rrf_k = rrf_k
        self._tokens = [_tokenize(chunk.content) for chunk in self._chunks]
        self._embeddings = _validate_embeddings(
            embedding_provider.embed([chunk.content for chunk in self._chunks]),
            expected_count=len(self._chunks),
        )

    def search(
        self,
        query: str,
        *,
        project_type: ProjectType,
        top_k: int = 5,
        jurisdiction: str | None = None,
    ) -> list[PolicySearchResult]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("政策检索问题不能为空")
        if top_k <= 0 or top_k > 100:
            raise ValueError("政策检索 top_k 必须在 1 到 100 之间")
        normalized_jurisdiction = jurisdiction.strip() if jurisdiction else None

        eligible = [
            index
            for index, chunk in enumerate(self._chunks)
            if project_type in chunk.applicable_project_types
            and (
                normalized_jurisdiction is None
                or chunk.jurisdiction == normalized_jurisdiction
            )
        ]
        if not eligible:
            return []

        sparse_scores = _bm25_scores(
            _tokenize(normalized_query),
            [self._tokens[index] for index in eligible],
        )
        query_embedding = _validate_embeddings(
            self._embedding_provider.embed([normalized_query]),
            expected_count=1,
            expected_dimension=len(self._embeddings[0]),
        )[0]
        vector_scores = [
            _cosine_similarity(query_embedding, self._embeddings[index])
            for index in eligible
        ]

        sparse_ranks = _rank_scores(eligible, sparse_scores, positive_only=True)
        vector_ranks = _rank_scores(eligible, vector_scores, positive_only=False)
        fused: list[tuple[int, float]] = []
        for index in eligible:
            score = 0.0
            sparse_rank = sparse_ranks.get(index)
            vector_rank = vector_ranks.get(index)
            if sparse_rank is not None:
                score += self._sparse_weight / (self._rrf_k + sparse_rank)
            if vector_rank is not None:
                score += self._vector_weight / (self._rrf_k + vector_rank)
            if score > 0:
                fused.append((index, score))
        fused.sort(key=lambda item: (-item[1], self._chunks[item[0]].chunk_id))

        return [
            PolicySearchResult(
                citation=_citation(self._chunks[index]),
                fused_score=score,
                sparse_rank=sparse_ranks.get(index),
                vector_rank=vector_ranks.get(index),
            )
            for index, score in fused[:top_k]
        ]


def _split_section(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
) -> list[tuple[int, int, str]]:
    normalized = text.strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        hard_end = min(start + max_chars, len(normalized))
        end = hard_end
        if hard_end < len(normalized):
            boundary = max(
                normalized.rfind(mark, start + max_chars // 2, hard_end)
                for mark in ("。", "！", "？", ";", "；", "\n")
            )
            if boundary >= 0:
                end = boundary + 1
        content = normalized[start:end].strip()
        if content:
            content_start = start + len(normalized[start:end]) - len(
                normalized[start:end].lstrip()
            )
            chunks.append((content_start, content_start + len(content), content))
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+", lowered)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(sequence) == 1:
            tokens.append(sequence)
        else:
            tokens.extend(
                sequence[index : index + 2]
                for index in range(len(sequence) - 1)
            )
    return tokens


def _bm25_scores(
    query_tokens: list[str],
    documents: list[list[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    if not documents:
        return []
    average_length = sum(len(document) for document in documents) / len(documents)
    average_length = average_length or 1
    document_frequency = Counter(
        token
        for document in documents
        for token in set(document)
    )
    scores = []
    for document in documents:
        frequencies = Counter(document)
        score = 0.0
        for token in set(query_tokens):
            frequency = frequencies[token]
            if not frequency:
                continue
            docs_with_token = document_frequency[token]
            inverse_frequency = math.log(
                1 + (len(documents) - docs_with_token + 0.5) / (docs_with_token + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * len(document) / average_length
            )
            score += inverse_frequency * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def _validate_embeddings(
    embeddings: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimension: int | None = None,
) -> list[list[float]]:
    rows = [list(row) for row in embeddings]
    if len(rows) != expected_count:
        raise ValueError("EmbeddingProvider 返回数量与输入不一致")
    dimension = expected_dimension or (len(rows[0]) if rows else 0)
    if dimension <= 0:
        raise ValueError("Embedding 向量维度必须大于 0")
    if any(len(row) != dimension for row in rows):
        raise ValueError("Embedding 向量维度不一致")
    if any(not math.isfinite(value) for row in rows for value in row):
        raise ValueError("Embedding 向量包含非有限值")
    if any(not any(value != 0 for value in row) for row in rows):
        raise ValueError("Embedding 向量不能为全零")
    return rows


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Embedding 向量范数不能为 0")
    return numerator / (left_norm * right_norm)


def _rank_scores(
    indices: list[int],
    scores: list[float],
    *,
    positive_only: bool,
) -> dict[int, int]:
    candidates = [
        (index, score)
        for index, score in zip(indices, scores, strict=True)
        if not positive_only or score > 0
    ]
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return {
        index: rank
        for rank, (index, _) in enumerate(candidates, start=1)
    }
def _citation(chunk: PolicyChunk) -> PolicyCitation:
    return PolicyCitation(
        chunk_id=chunk.chunk_id,
        policy_id=chunk.policy_id,
        title=chunk.title,
        issuing_authority=chunk.issuing_authority,
        document_number=chunk.document_number,
        clause=chunk.clause,
        version=chunk.version,
        jurisdiction=chunk.jurisdiction,
        source_uri=chunk.source_uri,
        page_number=chunk.page_number,
        quote=chunk.content,
    )

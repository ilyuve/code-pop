"""Tests for Chinese semantic enrichment utilities."""

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from services.chinese_enricher import (
    EnrichmentResult,
    FlowLabelResult,
    _clean_synonyms,
    _extract_json_block,
    _parse_json_safe,
    aggregate_domain_synonyms,
    expand_query_with_synonyms,
    load_domain_synonyms,
    save_embedding_enrichment,
    save_symbol_flow_label,
)


class TestJsonParsing:
    def test_extract_json_block_from_raw_json(self):
        assert _extract_json_block('{"a": 1}') == '{"a": 1}'

    def test_extract_json_block_from_markdown(self):
        text = "```json\n{\"a\": 1}\n```"
        assert _extract_json_block(text) == '{"a": 1}'

    def test_parse_json_safe_valid(self):
        assert _parse_json_safe('{"chinese_summary": "测试"}') == {"chinese_summary": "测试"}

    def test_parse_json_safe_invalid_returns_none(self):
        assert _parse_json_safe("not json") is None


class TestCleanSynonyms:
    def test_keeps_string_lists(self):
        assert _clean_synonyms({"骑士": ["骑手", "rider"]}) == {"骑士": ["骑手", "rider"]}

    def test_converts_single_string_to_list(self):
        assert _clean_synonyms({"骑士": "骑手"}) == {"骑士": ["骑手"]}

    def test_skips_non_string_keys(self):
        assert _clean_synonyms({1: ["a"]}) == {}

    def test_skips_empty_values(self):
        assert _clean_synonyms({"骑士": []}) == {}


class TestExpandQueryWithSynonyms:
    def test_generates_variants(self):
        synonyms = {"骑士": ["骑手", "rider"]}
        variants = expand_query_with_synonyms("骑士配送流程", synonyms)
        assert "骑士配送流程" in variants
        assert "骑手配送流程" in variants
        assert "rider配送流程" in variants

    def test_no_synonyms_returns_original(self):
        assert expand_query_with_synonyms("test", {}) == ["test"]


class TestDomainSynonymAggregation:
    def test_aggregate_inserts_new_term(self):
        db = MagicMock()
        repo_id = uuid4()
        db.query.return_value.filter.return_value.all.return_value = []

        aggregate_domain_synonyms(db, repo_id, [{"骑士": ["骑手"]}])

        db.add.assert_called_once()
        db.commit.assert_not_called()

    def test_aggregate_merges_existing_term(self):
        db = MagicMock()
        repo_id = uuid4()
        existing = MagicMock()
        existing.canonical_term = "骑士"
        existing.synonyms = json.dumps(["骑士"], ensure_ascii=False)
        existing.hit_count = 1
        db.query.return_value.filter.return_value.all.return_value = [existing]

        aggregate_domain_synonyms(db, repo_id, [{"骑士": ["骑手"]}])

        assert "骑手" in json.loads(existing.synonyms)
        assert existing.hit_count == 2
        db.commit.assert_not_called()

    def test_load_domain_synonyms(self):
        db = MagicMock()
        repo_id = uuid4()
        row = MagicMock()
        row.canonical_term = "骑士"
        row.synonyms = json.dumps(["骑手"], ensure_ascii=False)
        db.query.return_value.filter.return_value.all.return_value = [row]

        result = load_domain_synonyms(db, repo_id)
        assert result == {"骑士": ["骑手"]}


class TestSaveFunctions:
    def test_save_embedding_enrichment(self):
        db = MagicMock()
        embedding_id = uuid4()
        result = EnrichmentResult(
            chinese_summary="摘要",
            keywords=["k1", "k2"],
            vertical_layer="service",
            horizontal_module="delivery",
            synonyms={"骑士": ["骑手"]},
        )
        save_embedding_enrichment(db, embedding_id, "hash123", result, "deepseek-chat")
        db.add.assert_called_once()
        call_args = db.add.call_args[0][0]
        assert call_args.chinese_summary == "摘要"
        assert call_args.keywords == json.dumps(["k1", "k2"], ensure_ascii=False)

    def test_save_symbol_flow_label(self):
        db = MagicMock()
        symbol_id = uuid4()
        result = FlowLabelResult(
            layer="controller",
            module="order",
            chinese_name="创建订单",
            io_description="输入商品信息，输出订单",
        )
        save_symbol_flow_label(db, symbol_id, result)
        db.add.assert_called_once()


@pytest.mark.asyncio
class TestEnrichChunk:
    async def test_returns_result_on_valid_json(self):
        from services.chinese_enricher import enrich_chunk

        router = MagicMock()
        router.chat = AsyncMock(
            return_value=(
                MagicMock(
                    content=json.dumps(
                        {
                            "chinese_summary": "测试摘要",
                            "keywords": ["k1"],
                            "vertical_layer": "service",
                            "horizontal_module": "delivery",
                            "synonyms": {"骑士": ["骑手"]},
                        },
                        ensure_ascii=False,
                    )
                ),
                "provider-1",
            )
        )

        result = await enrich_chunk(router, "def foo(): pass", "python")
        assert result is not None
        assert result.chinese_summary == "测试摘要"
        assert result.keywords == ["k1"]
        router.chat.assert_awaited_once()

    async def test_returns_none_on_invalid_json(self):
        from services.chinese_enricher import enrich_chunk

        router = MagicMock()
        router.chat = AsyncMock(return_value=(MagicMock(content="not json"), "provider-1"))

        result = await enrich_chunk(router, "def foo(): pass", "python")
        assert result is None


@pytest.mark.asyncio
class TestEnrichSymbolFlow:
    async def test_returns_label_on_valid_json(self):
        from services.chinese_enricher import enrich_symbol_flow

        router = MagicMock()
        router.chat = AsyncMock(
            return_value=(
                MagicMock(
                    content=json.dumps(
                        {
                            "layer": "controller",
                            "module": "order",
                            "chinese_name": "创建订单",
                            "io_description": "输入商品信息，输出订单",
                        },
                        ensure_ascii=False,
                    )
                ),
                "provider-1",
            )
        )

        result = await enrich_symbol_flow(
            router, "create_order", "/order.py", "python", "def create_order(): pass"
        )
        assert result is not None
        assert result.chinese_name == "创建订单"

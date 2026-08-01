"""Tests for query intent analysis and synonym expansion."""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.query_intent import QueryIntentAnalyzer, get_intent_analyzer


class TestIntentDetection:
    def test_detects_how_it_works_chinese(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("登录是怎么实现的")
        assert intent.intent_type == "how_it_works"
        assert intent.is_chinese is True

    def test_detects_impact_analysis(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("改了订单会影响哪里")
        assert intent.intent_type == "impact_analysis"

    def test_detects_symbol_lookup(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("create_order 在哪里")
        assert intent.intent_type == "symbol_lookup"

    def test_general_intent_fallback(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("foo bar")
        assert intent.intent_type == "general"


class TestConceptExtraction:
    def test_extracts_chinese_and_english(self):
        analyzer = QueryIntentAnalyzer()
        concepts = analyzer._extract_concepts("骑士rider配送流程", is_chinese=True)
        assert "rider" in concepts
        assert "骑士" in concepts

    def test_deduplicates_concepts(self):
        analyzer = QueryIntentAnalyzer()
        concepts = analyzer._extract_concepts("order order Order", is_chinese=False)
        assert concepts.count("order") == 1


class TestSynonymExpansion:
    def test_expands_with_semantic_map(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("登录")
        assert "login" in intent.expanded_terms
        assert "authenticate" in intent.expanded_terms

    def test_expands_with_domain_synonyms(self):
        analyzer = QueryIntentAnalyzer()
        db = MagicMock()
        repo_id = uuid4()
        row = MagicMock()
        row.canonical_term = "骑士"
        row.synonyms = '["骑手", "rider"]'
        db.query.return_value.filter.return_value.all.return_value = [row]

        intent = analyzer.analyze("骑士配送", repo_id=str(repo_id), db=db)
        assert "骑手配送" in intent.expanded_terms
        assert "rider配送" in intent.expanded_terms

    def test_includes_original_query(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("测试查询")
        assert "测试查询" in intent.expanded_terms


class TestSearchStrategy:
    def test_how_it_works_strategy(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("支付流程是怎样的")
        assert intent.search_strategy.primary == "call_graph"
        assert intent.search_strategy.include_callers is True
        assert intent.search_strategy.include_callees is True

    def test_chinese_symbol_lookup_prefers_vector(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("create_order 在哪里")
        # Even though intent is symbol_lookup, Chinese query shifts primary to vector.
        assert intent.search_strategy.primary == "vector"


class TestErrorPropagation:
    def test_analysis_error_propagates(self):
        analyzer = QueryIntentAnalyzer()
        # Force the analysis to raise by breaking concept extraction.
        with patch.object(analyzer, "_extract_concepts", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                analyzer.analyze("test")


def test_get_intent_analyzer_singleton():
    a1 = get_intent_analyzer()
    a2 = get_intent_analyzer()
    assert a1 is a2

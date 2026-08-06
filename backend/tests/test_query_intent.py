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

    def test_substring_fallback_for_compound_words(self):
        analyzer = QueryIntentAnalyzer()
        concepts = analyzer._extract_concepts("订单创建流程", is_chinese=True)
        assert "订单" in concepts
        assert "创建" in concepts
        assert "流程" in concepts


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

    def test_expanded_terms_are_prioritized(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("订单创建流程")
        terms = intent.expanded_terms
        # Original query must come first.
        assert terms[0] == "订单创建流程"
        # Concepts should appear before generic/LLM expansions.
        concept_idx = terms.index("订单") if "订单" in terms else len(terms)
        generic_idx = terms.index("process") if "process" in terms else len(terms)
        assert concept_idx < generic_idx

    def test_expanded_terms_are_capped(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("订单创建流程")
        assert len(intent.expanded_terms) <= 12

    def test_semantic_map_does_not_expand_elasticsearch(self):
        analyzer = QueryIntentAnalyzer()
        intent = analyzer.analyze("中文搜索是怎么实现的")
        assert "elasticsearch" not in intent.expanded_terms
        assert "search" in intent.expanded_terms

    def test_denylist_filters_noise_terms(self):
        analyzer = QueryIntentAnalyzer()
        # Directly drive _expand_synonyms with domain synonyms containing both
        # noise and valid terms, so the test is independent of the 12-term cap
        # and LLM availability.
        terms = analyzer._expand_synonyms(
            concepts=["测试"],
            query="测试",
            is_chinese=True,
            domain_synonyms={"测试": ["medium", "platform", "system", "valid_term"]},
            enable_llm_expand=False,
            llm_router=None,
        )
        assert "medium" not in terms
        assert "platform" not in terms
        assert "system" not in terms
        assert "valid_term" in terms


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

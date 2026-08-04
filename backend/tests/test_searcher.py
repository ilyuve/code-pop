"""Tests for Chinese semantic retrieval integration in the searcher."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from schemas import SearchResultItem, SymbolEntry
from services.searcher import Searcher, _Hit


def _make_symbol(symbol_id=None, name="foo", repo=None, file=None):
    sym = MagicMock()
    sym.id = symbol_id or uuid4()
    sym.name = name
    sym.type = "function"
    sym.line = 10
    sym.repo = repo
    sym.file = file or MagicMock(path="src/order.py")
    return sym


def _make_hit(symbol_id=None, file_path="src/order.py", content="def foo(): pass"):
    return _Hit(
        result_id=uuid4(),
        file_id=uuid4(),
        repo_id=uuid4(),
        repo_name="test-repo",
        file_path=file_path,
        language="python",
        content=content,
        line=1,
        symbol_id=symbol_id,
        symbol_name="foo",
    )


@pytest.fixture
def searcher():
    db = MagicMock()
    with patch("services.searcher.Embedder") as mock_embedder_cls:
        mock_embedder = MagicMock()
        mock_embedder.encode_query.return_value = [0.1] * 1024
        mock_embedder.encode_query_sparse.return_value = {1: 0.5}
        mock_embedder_cls.return_value = mock_embedder
        searcher = Searcher(db)
    return searcher


class TestSymbolEntryWithLabel:
    def test_includes_flow_label_fields(self, searcher):
        symbol_id = uuid4()
        sym = _make_symbol(symbol_id=symbol_id, name="create_order")
        label = MagicMock()
        label.layer = "controller"
        label.module = "order"
        label.chinese_name = "创建订单"
        label.io_description = "输入商品信息，输出订单"
        searcher.db.query.return_value.filter.return_value.first.return_value = label

        entry = searcher._symbol_entry_with_label(sym)

        assert entry.layer == "controller"
        assert entry.module == "order"
        assert entry.chinese_name == "创建订单"
        assert entry.io_description == "输入商品信息，输出订单"

    def test_uses_none_when_label_missing(self, searcher):
        sym = _make_symbol(name="create_order")
        searcher.db.query.return_value.filter.return_value.first.return_value = None

        entry = searcher._symbol_entry_with_label(sym)

        assert entry.layer is None
        assert entry.module is None
        assert entry.chinese_name is None
        assert entry.io_description is None


class TestBuildCallChain:
    def test_builds_chain_with_labels(self, searcher):
        root_id = uuid4()
        caller_id = uuid4()
        callee_id = uuid4()

        root = _make_symbol(symbol_id=root_id, name="root")
        caller = _make_symbol(symbol_id=caller_id, name="caller")
        callee = _make_symbol(symbol_id=callee_id, name="callee")

        searcher.db.query.return_value.filter.return_value.first.side_effect = [
            root,
            caller,
            callee,
        ]
        searcher._query_callers = MagicMock(return_value=[caller_id])
        searcher._query_callees = MagicMock(return_value=[callee_id])
        searcher._symbol_entry_with_label = MagicMock(
            side_effect=lambda sym: SymbolEntry(
                id=str(sym.id),
                name=sym.name,
                type=sym.type,
                file_path=sym.file.path,
                line=sym.line,
                layer="service",
                module="order",
                chinese_name="中文名",
            )
        )

        chain = searcher._build_call_chain(root_id, depth=1, include_callers=True, include_callees=True)

        assert chain.root.name == "root"
        assert len(chain.upstream) == 1
        assert len(chain.downstream) == 1
        assert chain.upstream[0].chinese_name == "中文名"


class TestBM25Search:
    def test_query_includes_chinese_enrichment_fields(self, searcher):
        repo_id = uuid4()
        rows = [
            MagicMock(
                embedding_id=uuid4(),
                file_id=uuid4(),
                repo_id=repo_id,
                repo_name="test-repo",
                content="def create_order(): pass",
                start_line=1,
                end_line=2,
                file_path="src/order.py",
                language="python",
                rank=0.8,
            )
        ]
        searcher.db.execute.return_value.fetchall.return_value = rows

        hits = searcher._bm25_search("创建订单", repo_id)

        assert len(hits) == 1
        call_args = searcher.db.execute.call_args
        sql_text = str(call_args[0][0])
        assert "embedding_enrichments" in sql_text
        assert "chinese_summary" in sql_text
        assert "keywords" in sql_text


class TestSearchWithContext:
    def test_expands_chinese_query_with_synonyms(self, searcher):
        from services.query_intent import QueryIntent, SearchStrategy

        repo_id = uuid4()
        intent = QueryIntent(
            original="骑士配送",
            intent_type="general",
            is_chinese=True,
            expanded_terms=["骑士配送", "骑手配送", "rider配送"],
            search_strategy=SearchStrategy(primary="bm25", secondary="symbol"),
        )

        searcher._search_and_fuse = MagicMock(return_value=[_make_hit()])
        searcher._infer_file_role = MagicMock(return_value="service")

        context = searcher.search_with_context("骑士配送", repo_id=repo_id, intent=intent)

        searcher._search_and_fuse.assert_called_once()
        call_args = searcher._search_and_fuse.call_args
        assert call_args[0][0] == "骑士配送"
        assert call_args[0][1] == repo_id
        assert "骑手配送" in context.matched_concepts

    def test_hybrid_search_propagates_embedder_failure(self, searcher):
        searcher.embedder.encode_query.side_effect = RuntimeError("model missing")

        with pytest.raises(RuntimeError):
            searcher.hybrid_search("登录", repo_id=uuid4(), limit=10)


class TestSearchAndFuse:
    def test_calls_all_sources_and_reranks(self, searcher):
        repo_id = uuid4()
        query = "订单创建流程"
        hit = _make_hit()
        searcher._vector_search = MagicMock(return_value=[hit])
        searcher._symbol_search = MagicMock(return_value=[hit])
        searcher._bm25_search = MagicMock(return_value=[hit])
        searcher._sparse_search = MagicMock(return_value=[hit])
        searcher._graph_search = MagicMock(return_value=[hit])

        with patch("services.searcher.CodeReranker") as mock_code_reranker_cls, \
             patch("services.searcher.get_m3_reranker") as mock_get_m3_reranker:
            mock_code_reranker = MagicMock()
            mock_code_reranker.rerank.return_value = [MagicMock(id=hit.result_id)]
            mock_code_reranker_cls.return_value = mock_code_reranker

            mock_m3_reranker = MagicMock()
            mock_m3_reranker.rerank.return_value = [MagicMock(id=hit.result_id)]
            mock_get_m3_reranker.return_value = mock_m3_reranker

            hits = searcher._search_and_fuse(query, repo_id, limit=20)

            assert len(hits) == 1
            assert hits[0].result_id == hit.result_id
            mock_code_reranker.rerank.assert_called_once()
            mock_m3_reranker.rerank.assert_called_once()

    def test_expanded_terms_reach_symbol_and_bm25(self, searcher):
        """SEMANTIC_MAP English mappings must feed the symbol/BM25 paths so
        Chinese queries can match English code identifiers."""
        repo_id = uuid4()
        hit = _make_hit()
        searcher._vector_search = MagicMock(return_value=[])
        searcher._symbol_search = MagicMock(return_value=[hit])
        searcher._bm25_search = MagicMock(return_value=[])
        searcher._sparse_search = MagicMock(return_value=[])
        searcher._graph_search = MagicMock(return_value=[])

        with patch("services.searcher.CodeReranker") as mock_code_reranker_cls, \
             patch("services.searcher.get_m3_reranker") as mock_get_m3_reranker:
            mock_code_reranker_cls.return_value.rerank.return_value = []
            mock_get_m3_reranker.return_value.rerank.return_value = []

            searcher._search_and_fuse(
                "订单创建流程", repo_id, limit=20,
                search_terms=["订单创建流程", "订单", "创建", "order", "create"],
            )

        # Symbol search is invoked per term (query + expanded terms).
        symbol_queries = [c[0][0] for c in searcher._symbol_search.call_args_list]
        assert "订单创建流程" in symbol_queries
        assert "order" in symbol_queries
        assert "create" in symbol_queries

        # BM25 concepts include the English expansions for content matching.
        bm25_kwargs = searcher._bm25_search.call_args
        concepts = bm25_kwargs[1].get("concepts") or bm25_kwargs[0][2]
        assert "order" in concepts
        assert "create" in concepts
        assert "订单" in concepts

    def test_symbol_search_multi_merges_duplicates(self, searcher):
        """Overlapping expanded terms must not duplicate symbols in RRF input."""
        repo_id = uuid4()
        symbol_id = uuid4()
        hit_low = _make_hit(symbol_id=symbol_id)
        hit_low.symbol_score = 0.7
        hit_high = _make_hit(symbol_id=symbol_id)
        hit_high.symbol_score = 1.0

        def fake_symbol_search(term, rid, top_k=50):
            if term == "order":
                return [hit_high]
            return [hit_low]

        searcher._symbol_search = MagicMock(side_effect=fake_symbol_search)

        hits = searcher._symbol_search_multi(
            "订单", ["订单", "order"], repo_id,
        )

        assert len(hits) == 1
        assert hits[0].symbol_score == 1.0

    def test_hybrid_search_analyzes_and_passes_terms(self, searcher):
        repo_id = uuid4()
        hit = _make_hit()
        searcher._search_and_fuse = MagicMock(return_value=[hit])

        results = searcher.hybrid_search("订单创建流程", repo_id=repo_id, limit=10)

        assert len(results) == 1
        _, kwargs = searcher._search_and_fuse.call_args
        assert "order" in kwargs["search_terms"]

    def test_search_with_context_uses_search_and_fuse(self, searcher):
        repo_id = uuid4()
        hit = _make_hit()
        searcher._search_and_fuse = MagicMock(return_value=[hit])
        searcher._infer_file_role = MagicMock(return_value="service")

        context = searcher.search_with_context("订单创建流程", repo_id=repo_id, limit=20)

        assert searcher._search_and_fuse.call_count == 1
        args, kwargs = searcher._search_and_fuse.call_args
        assert args[:3] == ("订单创建流程", repo_id, 20)
        # Expanded terms (incl. SEMANTIC_MAP English mappings) must reach the
        # retrieval pipeline so Chinese queries can match English identifiers.
        search_terms = kwargs.get("search_terms") or args[3]
        assert "订单" in search_terms
        assert "order" in search_terms
        assert len(context.code_snippets) == 1

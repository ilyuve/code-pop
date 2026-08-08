"""Tests for SymbolRepository."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from models import Symbol
from repositories.symbol_repository import SymbolRepository


def _make_symbol(symbol_id=None, name="foo"):
    sym = MagicMock(spec=Symbol)
    sym.id = symbol_id or uuid4()
    sym.name = name
    sym.file_id = uuid4()
    sym.repo_id = uuid4()
    sym.line = 1
    sym.type = "function"
    return sym


@pytest.fixture
def repo():
    db = MagicMock()
    return SymbolRepository(db)


class TestSearchByName:
    def test_batches_symbol_lookup_by_ids(self, repo):
        """The final deduplication loop must use a single bulk query, not N+1."""
        sym1 = _make_symbol(name="create_order")
        sym2 = _make_symbol(name="create_user")
        sym3 = _make_symbol(name="delete_order")
        symbols = [sym1, sym2, sym3]

        query = repo.db.query.return_value
        # Collapse the chained filter/limit/all calls onto one mock object so
        # every scoring sub-query returns the same symbol list.
        chain = query.join.return_value.outerjoin.return_value.filter.return_value
        chain.filter.return_value = chain
        chain.limit.return_value = chain
        chain.all.return_value = symbols

        def _bulk_lookup(symbol_ids):
            by_id = {sym.id: sym for sym in symbols}
            return [by_id[sid] for sid in symbol_ids if sid in by_id]

        with patch.object(repo, "get_by_ids", side_effect=_bulk_lookup) as mock_get_by_ids:
            results = repo.search_by_name("order", repo_id=uuid4(), limit=10)

        assert len(results) == 3
        mock_get_by_ids.assert_called_once()
        call_ids = mock_get_by_ids.call_args[0][0]
        assert len(call_ids) == 3
        assert set(call_ids) == {sym1.id, sym2.id, sym3.id}

        for sym in results:
            assert hasattr(sym, "_search_score")

    def test_returns_empty_for_no_matches(self, repo):
        query = repo.db.query.return_value
        query.join.return_value.outerjoin.return_value.filter.return_value.all.return_value = []

        results = repo.search_by_name("nomatch", repo_id=uuid4(), limit=10)

        assert results == []

def test_import_chinese_enricher():
    from services import chinese_enricher
    assert chinese_enricher is not None


def test_import_llm_client():
    from services import llm_client
    assert llm_client is not None


def test_import_llm_router():
    from services import llm_router
    assert llm_router is not None


def test_import_query_intent():
    from services import query_intent
    assert query_intent is not None


def test_import_searcher():
    from services import searcher
    assert searcher is not None

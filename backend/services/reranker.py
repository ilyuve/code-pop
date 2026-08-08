import logging
import re
import collections
from typing import List, Optional

from sentence_transformers import CrossEncoder
from schemas import SearchResultItem

logger = logging.getLogger(__name__)


_m3_reranker_instance = None


RERANKER_MODEL = "BAAI/bge-reranker-base"


class M3Reranker:
    """用 bge-reranker-base 做交叉编码重排序。"""

    def __init__(self, temperature: float = 0.8):
        if not hasattr(self, '_model'):
            self._model = None

        self.temperature = temperature
        if self._model is None:
            try:
                self._model = CrossEncoder(
                    RERANKER_MODEL,
                    max_length=512,
                    device='cpu',
                )
                logger.info("M3Reranker model loaded: %s", RERANKER_MODEL)
            except Exception as e:
                logger.warning("Failed to load M3Reranker model %s: %s", RERANKER_MODEL, e)
                self._model = None

    @property
    def model(self):
        return self._model


    def rerank(self, query: str, results: List[SearchResultItem], top_k: int = 10) -> List[SearchResultItem]:
        if not results:
            return results

        if self._model is None:
            logger.warning("M3Reranker model not loaded, skipping rerank")
            return results[:top_k]

        pairs = [
            [
                query,
                f"[{r.file_role}] {r.file_path}: {r.content[:500]}"
            ]
            for r in results
        ]

        try:
            scores = self.model.predict(pairs, batch_size=8)

            for r, score in zip(results, scores):
                # Temperature scaling makes small M3 score differences more visible.
                # It does not change the relative ordering produced by M3.
                r.score = float(score) / self.temperature

            results.sort(key=lambda x: -x.score)
            return results[:top_k]
        except Exception as e:
            logger.warning("M3 reranker failed: %s", e)
            return results[:top_k]


def get_m3_reranker() -> M3Reranker:
    """返回 M3Reranker 单例实例，避免每次搜索重新加载模型。"""
    global _m3_reranker_instance
    if _m3_reranker_instance is None:
        _m3_reranker_instance = M3Reranker()
    return _m3_reranker_instance


ROLE_WEIGHTS = {
    "analyzer": 1.25,
    "searcher": 1.25,
    "service": 1.2,
    "controller": 1.15,
    "handler": 1.15,
    "repository": 1.05,
    "dao": 1.05,
    "model": 0.8,
    "entity": 0.8,
    "dto": 0.75,
    "adapter": 0.75,
    "web": 0.8,
    "config": 0.7,
    "test": 0.5,
    "utility": 1.0,
    "middleware": 1.0,
    "other": 1.0,
}


class CodeReranker:
    """基于代码特征的轻量 reranker，纯规则，不依赖 LLM。"""

    ROLE_WEIGHTS = ROLE_WEIGHTS

    # Intent-aware multipliers for how_it_works / implementation queries.
    _INTENT_ROLE_BOOST = {
        "how_it_works": {
            "service": 1.5,
            "controller": 1.5,
            "handler": 1.3,
            "repository": 1.0,
            "utility": 1.0,
            "middleware": 1.0,
            "analyzer": 0.8,
            "model": 0.55,
            "adapter": 0.55,
            "config": 0.5,
            "test": 0.3,
        },
    }

    def rerank(
        self,
        query: str,
        results: List[SearchResultItem],
        search_terms: Optional[List[str]] = None,
        intent_type: Optional[str] = None,
    ) -> List[SearchResultItem]:
        file_counts = collections.Counter(r.file_path for r in results)
        # Strip short/noise terms; keep terms longer than 1 char.
        term_patterns = [t.lower() for t in (search_terms or []) if len(t) > 1]

        for r in results:
            multiplier = 1.0
            role = getattr(r, "file_role", None) or "other"

            if self._is_definition(r.content, query):
                multiplier *= 1.15

            # Role-based weighting.
            if role in self.ROLE_WEIGHTS:
                multiplier *= self.ROLE_WEIGHTS[role]

            # Intent-aware role tuning for implementation queries.
            intent_boost = self._INTENT_ROLE_BOOST.get(intent_type, {})
            if role in intent_boost:
                multiplier *= intent_boost[role]

            # Test/config penalties.
            if self._is_test_file(r.file_path):
                multiplier *= 0.5
            elif self._is_config_file(r.file_path):
                multiplier *= 0.7

            # Same-file coherence boost.
            if file_counts[r.file_path] > 1:
                coherence = 1.0 + 0.1 * (file_counts[r.file_path] - 1)
                multiplier *= min(coherence, 1.3)

            # Domain relevance: path or content matches expanded query terms.
            if term_patterns:
                haystack = f"{r.file_path} {r.content[:300]}".lower()
                matches = sum(1 for t in term_patterns if t in haystack)
                if matches:
                    multiplier *= 1.0 + 0.05 * min(matches, 3)

            r.score *= multiplier

        results.sort(key=lambda x: -x.score)
        return results

    # Shallow definitions that should not receive the full definition bonus.
    _SHALLOW_DEF_NAMES = frozenset({"__init__", "__new__", "__repr__", "__str__"})

    def _is_shallow_snippet(self, content: str) -> bool:
        """True for snippets that are constructors, trivial getters, or very short."""
        if not content:
            return True
        lines = content.splitlines()
        if len(lines) <= 3:
            return True
        first_line = lines[0]
        name_match = re.search(r"\b(def|function)\s+(\w+)", first_line)
        if name_match and name_match.group(2) in self._SHALLOW_DEF_NAMES:
            return True
        # One-line getter/setter-like methods.
        if len(lines) <= 4 and re.search(r"\breturn\s+self\.", content):
            return True
        return False

    def _is_definition(self, content: str, query: str) -> bool:
        escaped = re.escape(query)
        patterns = [
            rf'\bclass\s+{escaped}\b',
            rf'\bdef\s+{escaped}\b',
            rf'\bfunction\s+{escaped}\b',
            rf'\binterface\s+{escaped}\b',
            rf'\bstruct\s+{escaped}\b',
        ]
        if not any(re.search(p, content, re.IGNORECASE) for p in patterns):
            return False

        # Skip shallow constructors / magic methods.
        first_line = content.splitlines()[0] if content else ""
        name_match = re.search(r'\b(def|function)\s+(\w+)', first_line)
        if name_match and name_match.group(2) in self._SHALLOW_DEF_NAMES:
            return False

        # Skip trivial one-line getters / setters.
        if len(content.splitlines()) <= 3:
            return False

        return True

    def _is_test_file(self, path: str) -> bool:
        path_lower = path.lower()
        test_indicators = [
            'test', '__tests__', '_test.', '.test.',
            '_spec.', '.spec.', 'spec_',
            'mock', 'fixture', 'stub',
        ]
        return any(indicator in path_lower for indicator in test_indicators)

    def _is_config_file(self, path: str) -> bool:
        path_lower = path.lower()
        config_indicators = [
            'config', 'settings', 'constants',
            'env.', '.env', 'yaml', 'yml',
            'dockerfile', 'docker-compose',
            'requirements.txt', 'package.json',
            'tsconfig', 'webpack', 'vite.config',
        ]
        return any(indicator in path_lower for indicator in config_indicators)

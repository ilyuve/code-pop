import logging
import re
import collections
from typing import List

from sentence_transformers import CrossEncoder
from config import settings
from schemas import SearchResultItem

logger = logging.getLogger(__name__)


_m3_reranker_instance = None


class M3Reranker:
    """用 bge-m3 做交叉编码重排序。"""

    def __init__(self):
        if not hasattr(self, '_model') or self._model is None:
            model_name = settings.embedding_model
            self._model = CrossEncoder(
                model_name,
                max_length=512,
                device='cpu',
            )

    @property
    def model(self):
        return self._model


    def rerank(self, query: str, results: List[SearchResultItem], top_k: int = 10) -> List[SearchResultItem]:
        if not results:
            return results

        pairs = [
            [query, f"{r.file_path}: {r.content[:500]}"]
            for r in results
        ]

        try:
            scores = self.model.predict(pairs, batch_size=8)

            for r, score in zip(results, scores):
                r.score = float(score)

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


class CodeReranker:
    """基于代码特征的轻量 reranker，纯规则，不依赖 LLM。"""

    def rerank(self, query: str, results: List[SearchResultItem]) -> List[SearchResultItem]:
        file_counts = collections.Counter(r.file_path for r in results)

        for r in results:
            multiplier = 1.0

            if self._is_definition(r.content, query):
                multiplier *= 1.3

            if getattr(r, 'file_role', None) == "controller":
                multiplier *= 1.2

            if self._is_test_file(r.file_path):
                multiplier *= 0.5
            elif self._is_config_file(r.file_path):
                multiplier *= 0.7

            if file_counts[r.file_path] > 1:
                coherence = 1.0 + 0.1 * (file_counts[r.file_path] - 1)
                multiplier *= min(coherence, 1.3)

            r.score *= multiplier

        results.sort(key=lambda x: -x.score)
        return results

    def _is_definition(self, content: str, query: str) -> bool:
        escaped = re.escape(query)
        patterns = [
            rf'\bclass\s+{escaped}\b',
            rf'\bdef\s+{escaped}\b',
            rf'\bfunction\s+{escaped}\b',
            rf'\binterface\s+{escaped}\b',
            rf'\bstruct\s+{escaped}\b',
        ]
        return any(re.search(p, content, re.IGNORECASE) for p in patterns)

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

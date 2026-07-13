import re
import collections
from typing import List

from schemas import SearchResultItem


class CodeReranker:
    """基于代码特征的轻量 reranker，纯规则，不依赖 LLM。"""

    def rerank(self, query: str, results: List[SearchResultItem]) -> List[SearchResultItem]:
        """
        对搜索结果应用 code-aware 信号，调整分数后重排序。

        Args:
            query: 用户查询词
            results: RRF 融合后的结果列表（已去重）

        Returns:
            调整分数后降序排列的结果
        """
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
        """检查 content 是否包含 query 的定义语句。"""
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
        """判断路径是否为测试文件。"""
        path_lower = path.lower()
        test_indicators = [
            'test', '__tests__', '_test.', '.test.',
            '_spec.', '.spec.', 'spec_',
            'mock', 'fixture', 'stub',
        ]
        return any(indicator in path_lower for indicator in test_indicators)

    def _is_config_file(self, path: str) -> bool:
        """判断路径是否为配置文件。"""
        path_lower = path.lower()
        config_indicators = [
            'config', 'settings', 'constants',
            'env.', '.env', 'yaml', 'yml',
            'dockerfile', 'docker-compose',
            'requirements.txt', 'package.json',
            'tsconfig', 'webpack', 'vite.config',
        ]
        return any(indicator in path_lower for indicator in config_indicators)
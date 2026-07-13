import re
from typing import List


class SymbolNormalizer:
    """符号名归一化，支持大小写/驼峰/下划线变体匹配。"""

    @staticmethod
    def normalize(name: str) -> str:
        """
        将任意命名风格的符号名归一化。

        示例：
        - notify_rider → notifyrider
        - NotifyRider → notifyrider
        - notifyRider → notifyrider
        - NOTIFY_RIDER → notifyrider
        - getUserById → getuserbyid
        - HTTPClient → httpclient
        """
        s = name.replace('_', ' ')
        s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
        s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
        return s.lower().replace(' ', '')

    @staticmethod
    def match(query: str, symbol_name: str) -> bool:
        """
        宽松匹配查询词和符号名。

        返回 True 当且仅当：
        - 归一化后完全相等
        - 查询词是符号名的子串（前缀匹配）
        - 符号名是查询词的子串（后缀匹配）
        """
        nq = SymbolNormalizer.normalize(query)
        ns = SymbolNormalizer.normalize(symbol_name)
        return nq == ns or nq in ns or ns in nq

    @staticmethod
    def match_all(query: str, symbol_names: List[str]) -> List[str]:
        """筛选出与查询词匹配的符号名列表。"""
        return [name for name in symbol_names if SymbolNormalizer.match(query, name)]
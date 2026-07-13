"""Query intent analysis: understand what the user wants, expand synonyms."""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SearchStrategy:
    primary: str
    secondary: str
    include_callers: bool = False
    include_callees: bool = False
    call_depth: int = 3
    result_format: str = "list"
    expand_synonyms: bool = True


@dataclass
class QueryIntent:
    original: str
    intent_type: str
    concepts: List[str] = field(default_factory=list)
    expanded_terms: List[str] = field(default_factory=list)
    search_strategy: SearchStrategy = field(default_factory=lambda: SearchStrategy("vector", "bm25"))
    is_chinese: bool = False


class QueryIntentAnalyzer:
    INTENT_PATTERNS = {
        "how_it_works": [
            r"怎么.*实现", r"怎么.*工作", r"流程.*怎样", r"原理.*什么",
            r".*是如何.*", r".*流程.*", r".*机制.*", r".*原理.*",
            r".*怎么.*运行", r".*如何.*处理",
            r"how\s+.*\bworks\b", r"how\s+.*\bimplement", r"what\s+.*\bflow",
            r"how\s+.*\bprocess", r"how\s+.*\bhandle", r"what\s+.*\bmechanism",
            r"explain\s+.*", r"walk\s+me\s+through",
        ],
        "impact_analysis": [
            r"影响.*哪里", r"改了.*影响", r"哪些地方.*用", r"哪里.*用到",
            r".*影响.*范围", r".*涉及.*", r".*关联.*",
            r"impact", r"affect", r"who\s+.*\bcall", r"where\s+.*\buse",
            r"depend\s+on", r"reference", r"who\s+.*\bdepend",
        ],
        "symbol_lookup": [
            r"在哪里", r"定义.*哪里", r"方法.*哪", r".*位置.*",
            r".*在哪.*", r"查找.*", r"定位.*",
            r"where\s+.*\bdefined", r"where\s+.*\bis", r"find\s+.*\bmethod",
            r"locate", r"definition\s+of",
        ],
        "find_bug": [
            r"bug", r"错误", r"异常", r"崩溃", r"为什么.*失败",
            r"问题.*", r"故障.*", r"排查.*",
            r"bug", r"error", r"exception", r"crash", r"why\s+.*\bfail",
            r"troubleshoot", r"debug", r"issue",
        ],
    }

    SEMANTIC_MAP: Dict[str, List[str]] = {
        "登录": ["login", "authenticate", "auth", "sign_in", "signin", "session", "token"],
        "认证": ["authenticate", "auth", "verify", "validation", "check"],
        "注册": ["register", "signup", "sign_up", "create_user", "account_create"],
        "注销": ["logout", "sign_out", "signout", "clear_session"],
        "密码": ["password", "passwd", "pwd", "credential"],
        "权限": ["permission", "role", "authority", "access_control", "rbac", "acl"],
        "jwt": ["jwt", "token", "bearer", "json_web_token"],
        "session": ["session", "cookie", "state"],
        "订单": ["order", "purchase", "transaction", "checkout", "booking"],
        "支付": ["payment", "pay", "charge", "billing", "invoice"],
        "用户": ["user", "account", "member", "customer", "client"],
        "商品": ["product", "item", "goods", "sku", "merchandise"],
        "库存": ["inventory", "stock", "warehouse", "storage"],
        "数据库": ["database", "db", "sql", "query", "repository", "dao", "mapper"],
        "缓存": ["cache", "redis", "memcached", "cached", "lru"],
        "搜索": ["search", "query", "find", "lookup", "index", "elasticsearch"],
        "日志": ["log", "logging", "logger", "trace", "audit"],
        "监控": ["monitor", "metric", "telemetry", "observability", "prometheus"],
        "配置": ["config", "configuration", "settings", "properties", "env", "yaml"],
        "任务": ["task", "job", "cron", "schedule", "worker", "queue"],
        "消息": ["message", "mq", "kafka", "rabbitmq", "queue", "event"],
        "网关": ["gateway", "proxy", "router", "ingress", "nginx"],
        "服务": ["service", "svc", "microservice", "handler"],
        "接口": ["api", "interface", "endpoint", "controller", "handler", "rpc"],
        "请求": ["request", "req", "http", "call", "invoke"],
        "响应": ["response", "res", "resp", "reply", "return"],
        "连接": ["connection", "conn", "connect", "pool", "client"],
        "创建": ["create", "new", "init", "insert", "add", "build"],
        "更新": ["update", "modify", "edit", "patch", "save", "upsert"],
        "删除": ["delete", "remove", "del", "drop", "clear", "destroy"],
        "查询": ["query", "select", "find", "get", "search", "lookup", "fetch"],
        "验证": ["validate", "verify", "check", "assert", "confirm", "test"],
        "处理": ["handle", "process", "deal", "dispose", "manage"],
        "异步": ["async", "await", "promise", "future", "callback", "deferred"],
        "并发": ["concurrent", "parallel", "thread", "goroutine", "lock", "mutex"],
    }

    GENERIC_EXPAND: Dict[str, List[str]] = {
        "flow": ["process", "handler", "service", "chain"],
        "handler": ["controller", "service", "process", "handle"],
        "service": ["handler", "manager", "provider", "impl"],
        "controller": ["handler", "endpoint", "api", "route"],
        "repository": ["dao", "mapper", "store", "data"],
        "manager": ["service", "handler", "provider"],
        "util": ["helper", "utils", "tool", "common"],
        "config": ["configuration", "settings", "properties", "env"],
        "test": ["spec", "unit", "integration", "e2e"],
    }

    def analyze(self, query: str) -> QueryIntent:
        is_chinese = bool(re.search(r'[\u4e00-\u9fff]', query))
        intent_type = self._detect_intent(query)
        concepts = self._extract_concepts(query, is_chinese)
        expanded_terms = self._expand_synonyms(concepts, query, is_chinese)
        strategy = self._build_strategy(intent_type, is_chinese)

        return QueryIntent(
            original=query,
            intent_type=intent_type,
            concepts=concepts,
            expanded_terms=expanded_terms,
            search_strategy=strategy,
            is_chinese=is_chinese,
        )

    def _detect_intent(self, query: str) -> str:
        query_lower = query.lower()
        for intent_type, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    return intent_type
        return "general"

    def _extract_concepts(self, query: str, is_chinese: bool) -> List[str]:
        concepts = []
        if is_chinese:
            english_words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*', query)
            concepts.extend(english_words)
            chinese_chars = re.findall(r'[\u4e00-\u9fff]{2,4}', query)
            concepts.extend(chinese_chars)
        else:
            camel_cases = re.findall(r'[a-zA-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+', query)
            concepts.extend(camel_cases)
            snake_cases = re.findall(r'[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+', query)
            concepts.extend(snake_cases)
            stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                         "in", "on", "at", "to", "for", "of", "with", "by", "from",
                         "how", "what", "where", "when", "why", "who", "which"}
            words = re.findall(r'[a-zA-Z]+', query.lower())
            concepts.extend([w for w in words if w not in stop_words and len(w) > 2])

        seen = set()
        result = []
        for c in concepts:
            key = c.lower()
            if key not in seen:
                seen.add(key)
                result.append(c)
        return result

    def _expand_synonyms(self, concepts: List[str], query: str, is_chinese: bool) -> List[str]:
        expanded: Set[str] = set()

        for concept in concepts:
            concept_lower = concept.lower()
            expanded.add(concept)

            if concept in self.SEMANTIC_MAP:
                expanded.update(self.SEMANTIC_MAP[concept])

            if is_chinese and concept in self.SEMANTIC_MAP:
                expanded.update(self.SEMANTIC_MAP[concept])

            if concept_lower in self.GENERIC_EXPAND:
                expanded.update(self.GENERIC_EXPAND[concept_lower])

            if not is_chinese:
                for suffix in ["s", "es", "ing", "ed", "er", "or", "tion", "ment"]:
                    if concept_lower.endswith(suffix):
                        root = concept_lower[:-len(suffix)]
                        if len(root) > 2:
                            expanded.add(root)

                if re.match(r'^[A-Z][a-z]+[A-Z]', concept):
                    parts = re.findall(r'[A-Z][a-z]*', concept)
                    expanded.update([p.lower() for p in parts])

        expanded.add(query)
        return sorted(expanded)

    def _build_strategy(self, intent_type: str, is_chinese: bool) -> SearchStrategy:
        strategies = {
            "how_it_works": SearchStrategy(
                primary="call_graph",
                secondary="vector",
                include_callers=True,
                include_callees=True,
                call_depth=3,
                result_format="flow",
                expand_synonyms=True,
            ),
            "impact_analysis": SearchStrategy(
                primary="call_graph",
                secondary="symbol",
                include_callers=True,
                include_callees=False,
                call_depth=5,
                result_format="impact",
                expand_synonyms=True,
            ),
            "symbol_lookup": SearchStrategy(
                primary="symbol",
                secondary="vector",
                include_callers=False,
                include_callees=False,
                call_depth=0,
                result_format="detail",
                expand_synonyms=True,
            ),
            "find_bug": SearchStrategy(
                primary="vector",
                secondary="symbol",
                include_callers=False,
                include_callees=True,
                call_depth=2,
                result_format="trace",
                expand_synonyms=True,
            ),
            "general": SearchStrategy(
                primary="vector",
                secondary="bm25",
                include_callers=False,
                include_callees=False,
                call_depth=0,
                result_format="list",
                expand_synonyms=True,
            ),
        }

        strategy = strategies.get(intent_type, strategies["general"])

        if is_chinese and strategy.primary == "symbol":
            strategy.primary = "vector"
            strategy.secondary = "symbol"

        return strategy


_intent_analyzer: Optional[QueryIntentAnalyzer] = None


def get_intent_analyzer() -> QueryIntentAnalyzer:
    global _intent_analyzer
    if _intent_analyzer is None:
        _intent_analyzer = QueryIntentAnalyzer()
    return _intent_analyzer
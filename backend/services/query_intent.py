"""Query intent analysis: understand what the user wants and expand synonyms."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from services.chinese_enricher import expand_query_with_synonyms, load_domain_synonyms
from services.llm_router import LLMRouter

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

    # Slimmed hard-coded Chinese-English mappings. These are high-frequency,
    # cross-lingual terms that are expensive to learn from scratch for every
    # repository. Niche or project-specific terms should come from
    # ``domain_synonyms`` (generated during indexing) or from LLM expansion.
    SEMANTIC_MAP: Dict[str, List[str]] = {
        "登录": ["login", "authenticate", "auth", "sign_in", "signin", "session", "token"],
        "认证": ["authenticate", "auth", "verify", "validation", "check"],
        "注册": ["register", "signup", "sign_up", "create_user", "account_create"],
        "密码": ["password", "passwd", "pwd", "credential"],
        "权限": ["permission", "role", "authority", "access_control", "rbac", "acl"],
        "jwt": ["jwt", "token", "bearer", "json_web_token"],
        "session": ["session", "cookie", "state"],
        "订单": ["order", "purchase", "transaction", "checkout", "booking"],
        "支付": ["payment", "pay", "charge", "billing", "invoice"],
        "用户": ["user", "account", "member", "customer", "client"],
        "数据库": ["database", "db", "sql", "query", "repository", "dao", "mapper"],
        "缓存": ["cache", "redis", "memcached", "cached", "lru"],
        "搜索": ["search", "query", "find", "lookup", "index", "elasticsearch"],
        "日志": ["log", "logging", "logger", "trace", "audit"],
        "配置": ["config", "configuration", "settings", "properties", "env", "yaml"],
        "任务": ["task", "job", "cron", "schedule", "worker", "queue"],
        "消息": ["message", "mq", "kafka", "rabbitmq", "queue", "event"],
        "服务": ["service", "svc", "microservice", "handler"],
        "接口": ["api", "interface", "endpoint", "controller", "handler", "rpc"],
        "请求": ["request", "req", "http", "call", "invoke"],
        "响应": ["response", "res", "resp", "reply", "return"],
        "创建": ["create", "new", "init", "insert", "add", "build"],
        "更新": ["update", "modify", "edit", "patch", "save", "upsert"],
        "删除": ["delete", "remove", "del", "drop", "clear", "destroy"],
        "查询": ["query", "select", "find", "get", "search", "lookup", "fetch"],
        "验证": ["validate", "verify", "check", "assert", "confirm", "test"],
    }

    # Generic role-word expansions that are relatively stable across projects.
    # Project-specific naming conventions should be learned via ``domain_synonyms``.
    GENERIC_EXPAND: Dict[str, List[str]] = {
        "flow": ["process", "handler", "service", "chain"],
        "handler": ["controller", "service", "process", "handle"],
        "service": ["handler", "manager", "provider", "impl"],
        "controller": ["handler", "endpoint", "api", "route"],
        "repository": ["dao", "mapper", "store", "data"],
        "config": ["configuration", "settings", "properties", "env"],
    }

    def analyze(
        self,
        query: str,
        repo_id: Optional[str] = None,
        db: Optional[Any] = None,
        enable_llm_expand: bool = True,
        llm_router: Optional[LLMRouter] = None,
    ) -> QueryIntent:
        is_chinese = bool(re.search(r'[\u4e00-\u9fff]', query))
        intent_type = self._detect_intent(query)
        concepts = self._extract_concepts(query, is_chinese)

        domain_synonyms: Dict[str, List[str]] = {}
        if db and repo_id:
            try:
                resolved_repo_id = UUID(repo_id) if isinstance(repo_id, str) else repo_id
                domain_synonyms = load_domain_synonyms(db, resolved_repo_id)
            except Exception as e:
                logger.warning("Failed to load domain synonyms: %s", e)

        expanded_terms = self._expand_synonyms(
            concepts,
            query,
            is_chinese,
            domain_synonyms,
            enable_llm_expand=enable_llm_expand,
            llm_router=llm_router,
        )
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

    @staticmethod
    def _split_identifier(name: str) -> List[str]:
        """Split a code identifier into meaningful tokens.

        Examples:
            createOrder -> ["create", "order"]
            OrderService -> ["order", "service"]
            process_payment -> ["process", "payment"]
            JWTToken -> ["jwt", "token"]
        """
        tokens: List[str] = []
        for part in re.split(r"[._\-]", name):
            if not part:
                continue
            # CamelCase / PascalCase: keep consecutive uppercase as one acronym,
            # then split on title-case boundaries.
            chunks = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z][a-z]*|[a-z]+", part)
            tokens.extend(ch.lower() for ch in chunks if ch)
        return tokens

    # Chinese stop-words and noise tokens that should not be treated as concepts.
    _CN_STOP_WORDS = {
        "的", "了", "在", "是", "我", "你", "他", "它", "们",
        "怎么", "什么", "如何", "为什么", "哪里", "哪些", "怎么",
        "请", "一下", "一个", "一些", "一下",
    }

    def _extract_concepts(self, query: str, is_chinese: bool) -> List[str]:
        """Extract searchable concepts from a query.

        For Chinese queries we use jieba for natural-language segmentation and
        also split any embedded English identifiers (camelCase / snake_case).
        This lets ``SEMANTIC_MAP`` and ``domain_synonyms`` actually match terms
        like ``订单`` and ``创建`` from the query ``订单创建流程``.
        """
        concepts: List[str] = []

        if is_chinese:
            # 1. English identifiers embedded in Chinese queries.
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query):
                concepts.append(token)
                concepts.extend(self._split_identifier(token))

            # 2. Chinese segmentation.
            try:
                import jieba

                tokens = jieba.lcut(query)
            except Exception:
                # Fallback: character-level tokens if jieba is not installed.
                tokens = list(query)

            for token in tokens:
                token = token.strip().lower()
                if not token or token in self._CN_STOP_WORDS:
                    continue
                if re.match(r"^[\u4e00-\u9fff]+$", token):
                    concepts.append(token)

        else:
            # English queries: keep camelCase / snake_case identifiers as concepts
            # and also split them into their constituent words.
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query):
                concepts.append(token)
                concepts.extend(self._split_identifier(token))

            stop_words = {
                "the", "a", "an", "is", "are", "was", "were", "be", "been",
                "in", "on", "at", "to", "for", "of", "with", "by", "from",
                "how", "what", "where", "when", "why", "who", "which",
            }
            words = re.findall(r"[a-zA-Z]+", query.lower())
            concepts.extend([w for w in words if w not in stop_words and len(w) > 2])

        seen: Set[str] = set()
        result: List[str] = []
        for c in concepts:
            key = c.lower()
            if key and key not in seen:
                seen.add(key)
                result.append(c)
        return result

    def _expand_synonyms(
        self,
        concepts: List[str],
        query: str,
        is_chinese: bool,
        domain_synonyms: Dict[str, List[str]],
        enable_llm_expand: bool = True,
        llm_router: Optional[LLMRouter] = None,
    ) -> List[str]:
        expanded: Set[str] = set()
        local_hit = False

        for concept in concepts:
            concept_lower = concept.lower()
            expanded.add(concept)

            if concept in self.SEMANTIC_MAP:
                expanded.update(self.SEMANTIC_MAP[concept])
                local_hit = True

            if concept_lower in self.GENERIC_EXPAND:
                expanded.update(self.GENERIC_EXPAND[concept_lower])
                local_hit = True

            # Repository-specific synonyms generated by LLM enrichment
            if concept_lower in domain_synonyms:
                expanded.update(domain_synonyms[concept_lower])
                local_hit = True

            if not is_chinese:
                for suffix in ["s", "es", "ing", "ed", "er", "or", "tion", "ment"]:
                    if concept_lower.endswith(suffix):
                        root = concept_lower[:-len(suffix)]
                        if len(root) > 2:
                            expanded.add(root)

                if re.match(r'^[A-Z][a-z]+[A-Z]', concept):
                    parts = re.findall(r'[A-Z][a-z]*', concept)
                    expanded.update([p.lower() for p in parts])

        # Add whole-query variants using domain synonyms (e.g. 骑士配送流程 -> 骑手配送流程)
        if domain_synonyms:
            expanded.update(expand_query_with_synonyms(query, domain_synonyms))
            local_hit = True

        # LLM online expansion for Chinese queries. It is *not* blocked by local hits,
        # so domain synonyms and the slimmed SEMANTIC_MAP act as a safety net while
        # the LLM can still fill coverage gaps (e.g. 骑手 -> rider).
        if enable_llm_expand and llm_router and is_chinese:
            try:
                llm_terms = self._expand_with_llm(query, concepts, llm_router)
                expanded.update(llm_terms)
            except Exception as e:
                logger.warning("LLM query expansion failed: %s", e)

        expanded.add(query)
        return sorted(expanded)

    def _expand_with_llm(
        self, query: str, concepts: List[str], llm_router: LLMRouter
    ) -> Set[str]:
        """Ask LLM for synonyms and English code keywords for the given query."""
        prompt = (
            "You are a code search assistant. Given a Chinese user query about code, "
            "return a JSON object with keys 'synonyms' (list of Chinese synonyms) and "
            "'code_terms' (list of likely English code identifiers/keywords). "
            "Keep each list short and relevant.\n\n"
            f"Query: {query}\n"
            f"Concepts: {', '.join(concepts)}\n\n"
            "Return JSON only, no markdown."
        )
        import asyncio
        import json as _json

        response, _provider_id = asyncio.run(
            llm_router.chat(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        )
        data = _json.loads(response.content)
        terms: Set[str] = set()
        for t in data.get("synonyms", []):
            terms.add(str(t))
        for t in data.get("code_terms", []):
            terms.add(str(t).lower())
        return terms

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
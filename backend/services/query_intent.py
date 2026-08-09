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

    # ------------------------------------------------------------------
    # 兜底层（FALLBACK）说明：
    # 本文件是查询意图分析与术语扩展。主路径是「在线 LLM」——见
    # `_expand_with_llm()`（analyze 中 enable_llm_expand=True 时调用）。
    # 下方这些本地硬编码映射（SEMANTIC_MAP / GENERIC_EXPAND）与
    # domain_synonyms / jieba 分词一样，仅作为**兜底**：当在线 LLM
    # 不可用、未配置或未启用时，仍能保证中文查询具备基础扩展能力。
    # 项目并非纯模板实现，请勿在未保留在线 LLM 路径的情况下依赖此处。
    # ------------------------------------------------------------------

    # Slimmed hard-coded Chinese-English mappings. These are high-frequency,
    # cross-lingual terms that are expensive to learn from scratch for every
    # repository. Niche or project-specific terms should come from
    # ``domain_synonyms`` (generated during indexing) or from LLM expansion.
    # NOTE: This is the offline fallback layer, NOT the primary path.
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
        "搜索": ["search", "query", "find"],
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

    # Terms that should never be propagated to downstream search paths.
    # These are either generic platform noise from the LLM or technologies
    # not used by the current codebase.
    EXPANSION_DENYLIST: Set[str] = {
        "medium",
        "elasticsearch",
        "platform",
        "system",
    }

    def analyze(
        self,
        query: str,
        repo_id: Optional[str] = None,
        db: Optional[Any] = None,
        enable_llm_expand: bool = True,
        llm_router: Optional[LLMRouter] = None,
    ) -> QueryIntent:
        # 主路径：在线 LLM（enable_llm_expand=True 时追加 _expand_with_llm 结果）；
        # 模板层（SEMANTIC_MAP/领域同义词/GENERIC_EXPAND）始终执行作为兜底。
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

        As a safety net, we also scan the query for any ``SEMANTIC_MAP`` /
        ``GENERIC_EXPAND`` key that appears as a substring. jieba may return
        compound words like ``订单创建`` that would otherwise miss the
        individual dictionary entries.
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
            except ImportError:
                logger.warning(
                    "jieba is not installed; falling back to character-level "
                    "segmentation. Chinese concept extraction will be degraded. "
                    "Install it with: pip install jieba"
                )
                tokens = list(query)
            except Exception:
                tokens = list(query)

            for token in tokens:
                token = token.strip().lower()
                if not token or token in self._CN_STOP_WORDS:
                    continue
                if re.match(r"^[\u4e00-\u9fff]+$", token):
                    concepts.append(token)

            # 3. Dictionary substring fallback: ensure compound jieba tokens
            #    still match individual SEMANTIC_MAP / GENERIC_EXPAND keys.
            for key in self.SEMANTIC_MAP:
                if key in query and key not in concepts:
                    concepts.append(key)
            for key in self.GENERIC_EXPAND:
                if key in query and key not in concepts:
                    concepts.append(key)

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
        """Expand query concepts with synonyms and code terms.

        The returned list is ordered by priority so that downstream callers
        (which often truncate to the first N terms) keep the most relevant
        tokens:
          1. The original query itself.
          2. Concepts extracted from the query.
          3. High-quality expansions (SEMANTIC_MAP, domain_synonyms).
          4. Generic / morphological expansions.
          5. LLM-generated terms.
        """
        semantic_hits: List[str] = []
        domain_hits: List[str] = []
        generic_hits: List[str] = []
        llm_hits: List[str] = []

        for concept in concepts:
            concept_lower = concept.lower()

            if concept in self.SEMANTIC_MAP:
                semantic_hits.extend(self.SEMANTIC_MAP[concept])

            if concept_lower in self.GENERIC_EXPAND:
                generic_hits.extend(self.GENERIC_EXPAND[concept_lower])

            if concept_lower in domain_synonyms:
                domain_hits.extend(domain_synonyms[concept_lower])

            if not is_chinese:
                for suffix in ["s", "es", "ing", "ed", "er", "or", "tion", "ment"]:
                    if concept_lower.endswith(suffix):
                        root = concept_lower[:-len(suffix)]
                        if len(root) > 2:
                            generic_hits.append(root)

                if re.match(r'^[A-Z][a-z]+[A-Z]', concept):
                    parts = re.findall(r'[A-Z][a-z]*', concept)
                    generic_hits.extend([p.lower() for p in parts])

        # Whole-query variants using domain synonyms (e.g. 骑士配送流程 -> 骑手配送流程)
        if domain_synonyms:
            domain_hits.extend(expand_query_with_synonyms(query, domain_synonyms))

        # 在线 LLM 查询扩展（主路径，仅中文查询且开启时）：
        # 失败/超时会被 try/except 兜住，自动回落到上面的模板层结果。
        if enable_llm_expand and llm_router and is_chinese:
            try:
                llm_terms = self._expand_with_llm(query, concepts, llm_router)
                llm_hits.extend(llm_terms)
            except Exception as e:
                logger.warning("LLM query expansion failed: %s", e)

        # Build the final ordered list, deduplicating while preserving order.
        ordered: List[str] = [query] + concepts
        for bucket in (semantic_hits, domain_hits, generic_hits, llm_hits):
            ordered.extend(bucket)

        seen: Set[str] = set()
        result: List[str] = []
        for term in ordered:
            key = term.lower() if term.isascii() else term
            if key and key not in seen and key not in self.EXPANSION_DENYLIST:
                seen.add(key)
                result.append(term)

        # Hard cap to avoid overwhelming downstream pipelines.
        max_terms = 12
        return result[:max_terms]

    def _expand_with_llm(
        self, query: str, concepts: List[str], llm_router: LLMRouter
    ) -> Set[str]:
        """在线 LLM 术语扩展主入口：向远程 LLM 请求同义词与英文代码词。

        本函数是「在线增强」的真正实现，仅在 enable_llm_expand=True 且
        已配置 LLM provider 时由 analyze 调用。任何异常（网络/超时/
        JSON 解析）都应由调用方 try/except 兜住，并回落到本文件的
        SEMANTIC_MAP / domain_synonyms 等离线模板层。
        """
        prompt = (
            "You are a code search assistant. Given a Chinese user query about code, "
            "return a JSON object with:\n"
            "- 'synonyms': Chinese synonyms that preserve the original intent\n"
            "- 'code_terms': English identifiers/keywords likely to appear in the codebase\n\n"
            "Rules:\n"
            "1. Only return terms clearly related to the query.\n"
            "2. Avoid generic words like 'medium', 'platform', 'system' unless explicitly mentioned.\n"
            "3. Prefer concrete code terms (function names, class names, API names) over abstract concepts.\n"
            "4. Keep each list short (<= 5 items).\n\n"
            f"Query: {query}\n"
            f"Concepts: {', '.join(concepts)}\n\n"
            "Return JSON only, no markdown."
        )
        import json as _json

        response, _provider_id = llm_router.chat_sync(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
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
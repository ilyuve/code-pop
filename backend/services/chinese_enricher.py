"""Chinese semantic enrichment for code chunks and symbols using online LLMs."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models import DomainSynonym, EmbeddingEnrichment, SymbolFlowLabel
from services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


_ENRICHMENT_PROMPT = """你是一名资深软件工程师，正在为代码仓库生成中文语义检索元数据。

请为下面的代码块生成以下字段（JSON 格式）：
- chinese_summary: 一句话中文摘要，说明这段代码做什么
- keywords: 5-10 个中文关键词列表，便于检索
- vertical_layer: 竖向分层，只能是 controller / service / repository / model / util / config / other 之一
- horizontal_module: 横向业务模块名，例如 delivery / order / payment / user
- synonyms: 一个对象，键是中文术语，值是同义词列表（可包含英文）。例如 {"骑士": ["骑手", "rider"], "配送": ["delivery", "dispatch"]}

代码：
```{language}
{content}
```

只输出合法 JSON，不要任何解释。"""


_FLOW_LABEL_PROMPT = """你是一名资深软件工程师，正在为函数生成流程标签。

函数名：{name}
文件路径：{file_path}
代码：
```{language}
{content}
```

请生成 JSON：
- layer: 竖向分层，只能是 controller / service / repository / model / util / config / other 之一
- module: 横向业务模块名
- chinese_name: 函数的中文名，简短（6 个字以内）
- io_description: 函数的输入输出描述，一句话

只输出合法 JSON，不要任何解释。"""


@dataclass
class EnrichmentResult:
    chinese_summary: str = ""
    keywords: List[str] = field(default_factory=list)
    vertical_layer: str = ""
    horizontal_module: str = ""
    synonyms: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class FlowLabelResult:
    layer: str = ""
    module: str = ""
    chinese_name: str = ""
    io_description: str = ""


def _extract_json_block(text: str) -> str:
    """Extract JSON from markdown code block or raw text."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_extract_json_block(text))
    except Exception as e:
        logger.warning("Failed to parse LLM JSON output: %s", e)
        return None


def _clean_synonyms(synonyms: Dict[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for key, value in synonyms.items():
        if not isinstance(key, str):
            continue
        items = []
        if isinstance(value, list):
            for v in value:
                if isinstance(v, str):
                    items.append(v)
        elif isinstance(value, str):
            items.append(value)
        if items:
            result[key] = items
    return result


async def enrich_chunk(
    router: LLMRouter,
    content: str,
    language: str,
    repo_id: Optional[str] = None,
) -> Optional[EnrichmentResult]:
    """Generate Chinese enrichment for a single code chunk."""
    messages = [
        {"role": "system", "content": "你是一个代码语义分析助手，输出合法 JSON。"},
        {"role": "user", "content": _ENRICHMENT_PROMPT.format(content=content[:4000], language=language)},
    ]
    try:
        resp, _ = await router.chat(
            messages,
            operation="enrich_chunk",
            repo_id=repo_id,
            response_format={"type": "json_object"},
        )
        data = _parse_json_safe(resp.content)
        if not data:
            return None
        return EnrichmentResult(
            chinese_summary=data.get("chinese_summary", ""),
            keywords=data.get("keywords", []),
            vertical_layer=data.get("vertical_layer", ""),
            horizontal_module=data.get("horizontal_module", ""),
            synonyms=_clean_synonyms(data.get("synonyms", {})),
        )
    except Exception as e:
        logger.warning("Chunk enrichment failed: %s", e)
        return None


async def enrich_symbol_flow(
    router: LLMRouter,
    name: str,
    file_path: str,
    language: str,
    content: str,
    repo_id: Optional[str] = None,
) -> Optional[FlowLabelResult]:
    """Generate flow label for a single symbol."""
    messages = [
        {"role": "system", "content": "你是一个代码语义分析助手，输出合法 JSON。"},
        {
            "role": "user",
            "content": _FLOW_LABEL_PROMPT.format(
                name=name,
                file_path=file_path,
                language=language,
                content=content[:2000],
            ),
        },
    ]
    try:
        resp, _ = await router.chat(
            messages,
            operation="enrich_symbol_flow",
            repo_id=repo_id,
            response_format={"type": "json_object"},
        )
        data = _parse_json_safe(resp.content)
        if not data:
            return None
        return FlowLabelResult(
            layer=data.get("layer", ""),
            module=data.get("module", ""),
            chinese_name=data.get("chinese_name", ""),
            io_description=data.get("io_description", ""),
        )
    except Exception as e:
        logger.warning("Symbol flow label enrichment failed: %s", e)
        return None


def aggregate_domain_synonyms(
    db: Session,
    repo_id: UUID,
    synonym_batches: List[Dict[str, List[str]]],
) -> None:
    """Merge LLM-generated synonyms into repository-level domain_synonyms table."""
    existing = {
        row.canonical_term: row
        for row in db.query(DomainSynonym).filter(DomainSynonym.repo_id == repo_id).all()
    }

    for batch in synonym_batches:
        for term, synonyms in batch.items():
            term = term.strip().lower()
            if not term or not synonyms:
                continue
            cleaned = sorted({s.strip() for s in synonyms if s.strip()})
            # Always include the canonical term itself in the synonym set so queries can normalize.
            cleaned = sorted({term} | set(cleaned))
            if term in existing:
                row = existing[term]
                current = set(json.loads(row.synonyms))
                current.update(cleaned)
                row.synonyms = json.dumps(sorted(current), ensure_ascii=False)
                row.frequency += 1
            else:
                row = DomainSynonym(
                    repo_id=repo_id,
                    canonical_term=term,
                    synonyms=json.dumps(cleaned, ensure_ascii=False),
                    source="auto",
                    frequency=1,
                )
                db.add(row)
                existing[term] = row
    db.commit()


def load_domain_synonyms(db: Session, repo_id: UUID) -> Dict[str, List[str]]:
    """Return {canonical_term: [synonyms]} for a repository."""
    rows = db.query(DomainSynonym).filter(DomainSynonym.repo_id == repo_id).all()
    result: Dict[str, List[str]] = {}
    for row in rows:
        try:
            result[row.canonical_term] = json.loads(row.synonyms)
        except Exception:
            continue
    return result


def expand_query_with_synonyms(
    query: str,
    domain_synonyms: Dict[str, List[str]],
) -> List[str]:
    """Generate query variants by replacing canonical terms with their synonyms."""
    variants = {query}
    for term, synonyms in domain_synonyms.items():
        if term in query:
            for synonym in synonyms:
                if synonym == term:
                    continue
                variant = query.replace(term, synonym)
                variants.add(variant)
    return sorted(variants)


def save_embedding_enrichment(
    db: Session,
    embedding_id: UUID,
    content_hash: str,
    result: EnrichmentResult,
    generated_by: str,
) -> None:
    """Persist enrichment result for an embedding."""
    enrichment = EmbeddingEnrichment(
        embedding_id=embedding_id,
        content_hash=content_hash,
        chinese_summary=result.chinese_summary,
        keywords=json.dumps(result.keywords, ensure_ascii=False),
        vertical_layer=result.vertical_layer,
        horizontal_module=result.horizontal_module,
        synonyms=json.dumps(result.synonyms, ensure_ascii=False),
        generated_by=generated_by,
    )
    db.add(enrichment)


def save_symbol_flow_label(
    db: Session,
    symbol_id: UUID,
    result: FlowLabelResult,
) -> None:
    """Persist flow label for a symbol."""
    label = SymbolFlowLabel(
        symbol_id=symbol_id,
        layer=result.layer,
        module=result.module,
        chinese_name=result.chinese_name,
        io_description=result.io_description,
    )
    db.add(label)

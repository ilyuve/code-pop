# CodePop - Python Backend with Full Features
# FastAPI implementation following technical documentation v2.1

from typing import Optional, List, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from collections import defaultdict
import uuid
import json
import hashlib
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import math

# --- Configuration ---
MAX_RETRIES = 3
RETRY_DELAY = 1.0
EMBEDDING_DIM = 384
MAX_TOKENS = 8000

# --- Enums ---

class Language(str, Enum):
    typescript = "typescript"
    python = "python"
    go = "go"
    rust = "rust"
    java = "java"
    cpp = "cpp"

class RepoStatus(str, Enum):
    indexed = "indexed"
    indexing = "indexing"
    error = "error"
    degraded = "degraded"

class SymbolType(str, Enum):
    function = "function"
    class_ = "class"
    variable = "variable"
    interface = "interface"
    method = "method"
    property = "property"
    import_ = "import"

class SearchMode(str, Enum):
    semantic = "semantic"
    symbol = "symbol"
    hybrid = "hybrid"

# --- Models ---

class Repository(BaseModel):
    id: str
    name: str
    path: str
    git_url: Optional[str] = None
    status: RepoStatus = RepoStatus.indexing
    file_count: int = 0
    symbol_count: int = 0
    embedding_count: int = 0
    created_at: datetime
    updated_at: datetime
    git_modified_at: Optional[datetime] = None
    git_author: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    indexing_progress: int = 0

class Symbol(BaseModel):
    id: str
    file_id: str
    repo_id: str
    name: str
    type: SymbolType
    kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    parent_id: Optional[str] = None
    is_exported: bool = False
    docstring: Optional[str] = None

class CodeFile(BaseModel):
    id: str
    repo_id: str
    path: str
    language: str
    content: str
    content_hash: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
    git_modified_at: Optional[datetime] = None

class Embedding(BaseModel):
    id: str
    file_id: str
    chunk_index: int
    content: str
    embedding: List[float]
    token_count: int
    created_at: datetime

class CallGraphEdge(BaseModel):
    id: str
    source_symbol_id: str
    target_symbol_id: str
    source_file_id: str
    target_file_id: str
    repo_id: str
    call_type: str  # direct, indirect, import

class SearchQuery(BaseModel):
    query: str
    repo_id: Optional[str] = None
    language: Optional[Language] = None
    limit: int = 20
    max_tokens: int = 8000
    mode: SearchMode = SearchMode.hybrid

class SearchResult(BaseModel):
    id: str
    file_id: str
    file_path: str
    content: str
    similarity: float
    language: str
    symbols: List[str] = []
    line: int = 0
    score: float = 0.0
    score_breakdown: Dict[str, float] = {}

class IndexProgress(BaseModel):
    repo_id: str
    total_files: int
    processed_files: int
    status: str
    error: Optional[str] = None

class SystemStatus(BaseModel):
    status: str
    version: str
    uptime: float
    active_requests: int
    indexing_tasks: int
    degraded_features: List[str] = []
    metrics: Dict[str, float] = {}

class DegradationStatus(BaseModel):
    feature: str
    status: str
    reason: Optional[str] = None
    fallback: Optional[str] = None

# --- In-memory database ---

repos: Dict[str, Repository] = {}
files: Dict[str, CodeFile] = {}
symbols: Dict[str, Symbol] = {}
embeddings: Dict[str, Embedding] = {}
call_graph: Dict[str, CallGraphEdge] = {}
search_history: List[Dict[str, Any]] = []
index_tasks: Dict[str, IndexProgress] = {}

# --- Embedding Manager ---

class EmbeddingManager:
    def __init__(self):
        self.active_provider = "local"
        self.models = {
            "local": {
                "name": "BAAI/bge-small-en",
                "dim": 384,
                "max_tokens": 512,
            }
        }
        self.fallback_enabled = True
    
    def generate_embedding(self, text: str) -> List[float]:
        """生成文本嵌入向量"""
        try:
            return self._generate_local_embedding(text)
        except Exception as e:
            if self.fallback_enabled:
                return self._generate_fallback_embedding(text)
            raise e
    
    def _generate_local_embedding(self, text: str) -> List[float]:
        """使用本地模型生成嵌入"""
        # 模拟嵌入生成（实际应使用 sentence-transformers）
        hash_val = hashlib.md5(text.encode()).digest()
        embedding = []
        for i in range(EMBEDDING_DIM):
            embedding.append((hash_val[i % 16] + i * 0.1) / 256.0)
        # 归一化
        norm = math.sqrt(sum(x*x for x in embedding))
        return [x/norm for x in embedding]
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        """降级时使用的简单嵌入"""
        embedding = []
        for i in range(EMBEDDING_DIM):
            embedding.append(math.sin(i * len(text)) * 0.5 + 0.5)
        norm = math.sqrt(sum(x*x for x in embedding))
        return [x/norm for x in embedding]

# --- Search Engine ---

class SearchEngine:
    def __init__(self):
        self.embedding_manager = EmbeddingManager()
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    async def search(self, query: SearchQuery) -> List[SearchResult]:
        """四路召回混合检索"""
        query_embedding = self.embedding_manager.generate_embedding(query.query)
        
        # 四路召回
        vector_results = await self._vector_search(query, query_embedding)
        symbol_results = await self._symbol_search(query)
        bm25_results = await self._bm25_search(query)
        graph_results = await self._graph_search(query)
        
        # 合并结果
        all_results = self._merge_results(
            vector_results, symbol_results, bm25_results, graph_results
        )
        
        # 重排序
        final_results = self._hybrid_rerank(all_results, query_embedding)
        
        return final_results[:query.limit]
    
    async def _vector_search(self, query: SearchQuery, query_embedding: List[float]) -> List[Dict[str, Any]]:
        """向量语义检索"""
        results = []
        repo_filter = query.repo_id
        
        for emb in embeddings.values():
            file = files.get(emb.file_id)
            if not file:
                continue
            if repo_filter and file.repo_id != repo_filter:
                continue
            
            similarity = self._cosine_similarity(query_embedding, emb.embedding)
            if similarity > 0.5:
                results.append({
                    "id": emb.id,
                    "file_id": emb.file_id,
                    "content": emb.content,
                    "similarity": similarity,
                    "source": "vector",
                    "file_path": file.path,
                    "language": file.language,
                })
        
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:50]
    
    async def _symbol_search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        """符号精确匹配检索"""
        results = []
        repo_filter = query.repo_id
        
        query_tokens = query.query.lower().split()
        
        for symbol in symbols.values():
            file = files.get(symbol.file_id)
            if not file:
                continue
            if repo_filter and file.repo_id != repo_filter:
                continue
            
            symbol_name = symbol.name.lower()
            score = 0
            
            # 精确匹配
            if query.query.lower() == symbol_name:
                score += 3.0
            # 前缀匹配
            elif symbol_name.startswith(query.query.lower()):
                score += 2.0
            # 包含匹配
            elif query.query.lower() in symbol_name:
                score += 1.0
            
            # 检查是否包含关键词
            for token in query_tokens:
                if token in symbol_name:
                    score += 0.5
            
            if score > 0:
                results.append({
                    "id": symbol.id,
                    "file_id": symbol.file_id,
                    "symbol_name": symbol.name,
                    "score": score,
                    "source": "symbol",
                    "file_path": file.path,
                    "language": file.language,
                    "line": symbol.line,
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:30]
    
    async def _bm25_search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        """BM25 全文检索"""
        results = []
        repo_filter = query.repo_id
        k1 = 1.5
        b = 0.75
        
        query_tokens = query.query.lower().split()
        doc_count = len(files)
        
        # 计算 IDF
        df = defaultdict(int)
        for file in files.values():
            if repo_filter and file.repo_id != repo_filter:
                continue
            file_tokens = set(file.content.lower().split())
            for token in query_tokens:
                if token in file_tokens:
                    df[token] += 1
        
        for file in files.values():
            if repo_filter and file.repo_id != repo_filter:
                continue
            
            score = 0
            file_tokens = file.content.lower().split()
            doc_len = len(file_tokens)
            avg_doc_len = sum(len(f.content.split()) for f in files.values()) / max(doc_count, 1)
            
            for token in query_tokens:
                tf = file_tokens.count(token)
                if tf == 0:
                    continue
                
                idf = math.log((doc_count - df[token] + 0.5) / (df[token] + 0.5) + 1)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * doc_len / avg_doc_len)
                score += idf * numerator / denominator
            
            if score > 0.1:
                results.append({
                    "id": file.id,
                    "file_id": file.id,
                    "content": file.content[:500],
                    "score": score,
                    "source": "bm25",
                    "file_path": file.path,
                    "language": file.language,
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:30]
    
    async def _graph_search(self, query: SearchQuery) -> List[Dict[str, Any]]:
        """图检索 - 调用链分析"""
        results = []
        repo_filter = query.repo_id
        
        query_tokens = query.query.lower().split()
        
        # 找到相关符号
        related_symbols = set()
        for symbol in symbols.values():
            if any(token in symbol.name.lower() for token in query_tokens):
                related_symbols.add(symbol.id)
        
        # 查找调用链
        for edge in call_graph.values():
            if repo_filter and edge.repo_id != repo_filter:
                continue
            
            if edge.source_symbol_id in related_symbols or edge.target_symbol_id in related_symbols:
                source_sym = symbols.get(edge.source_symbol_id)
                target_sym = symbols.get(edge.target_symbol_id)
                source_file = files.get(edge.source_file_id)
                
                if source_file:
                    results.append({
                        "id": edge.id,
                        "file_id": edge.source_file_id,
                        "source": "graph",
                        "score": 1.0,
                        "file_path": source_file.path,
                        "language": source_file.language,
                        "relation": f"{source_sym.name if source_sym else 'unknown'} -> {target_sym.name if target_sym else 'unknown'}",
                    })
        
        return results[:20]
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0
    
    def _merge_results(self, *result_lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并多路检索结果"""
        merged = {}
        
        for results in result_lists:
            for result in results:
                key = f"{result['file_id']}-{result.get('chunk_index', 0)}"
                if key not in merged:
                    merged[key] = {
                        "file_id": result["file_id"],
                        "file_path": result["file_path"],
                        "language": result["language"],
                        "content": result.get("content", ""),
                        "sources": [],
                        "scores": {},
                    }
                
                merged[key]["sources"].append(result["source"])
                merged[key]["scores"][result["source"]] = result.get("similarity", result.get("score", 0))
        
        return list(merged.values())
    
    def _hybrid_rerank(self, results: List[Dict[str, Any]], query_embedding: List[float]) -> List[SearchResult]:
        """混合重排序"""
        final_results = []
        
        for result in results:
            # 加权融合
            weights = {
                "vector": 0.4,
                "symbol": 0.3,
                "bm25": 0.2,
                "graph": 0.1,
            }
            
            total_score = 0
            for source, score in result["scores"].items():
                total_score += score * weights.get(source, 0.1)
            
            # 额外加分项
            if "symbol" in result["sources"] and "vector" in result["sources"]:
                total_score += 0.1  # 多源确认加分
            
            final_results.append({
                **result,
                "score": total_score,
                "score_breakdown": result["scores"],
            })
        
        final_results.sort(key=lambda x: x["score"], reverse=True)
        
        return [
            SearchResult(
                id=str(uuid.uuid4()),
                file_id=r["file_id"],
                file_path=r["file_path"],
                content=r["content"],
                similarity=r["scores"].get("vector", 0),
                language=r["language"],
                score=r["score"],
                score_breakdown=r["score_breakdown"],
            )
            for r in final_results
        ]

# --- Degradation Manager ---

class DegradationManager:
    def __init__(self):
        self.features = {
            "embedding": {"status": "healthy", "reason": None, "fallback": None},
            "search": {"status": "healthy", "reason": None, "fallback": None},
            "indexing": {"status": "healthy", "reason": None, "fallback": None},
            "graph": {"status": "healthy", "reason": None, "fallback": None},
        }
        self.metrics = {
            "request_count": 0,
            "error_count": 0,
            "latency_ms": 0,
            "avg_latency_ms": 0,
            "indexing_queue_length": 0,
        }
        self.start_time = time.time()
    
    def report_health(self, feature: str, status: str, reason: Optional[str] = None):
        """报告功能健康状态"""
        if feature in self.features:
            self.features[feature]["status"] = status
            self.features[feature]["reason"] = reason
            
            if status == "degraded":
                self.features[feature]["fallback"] = "使用降级模式"
    
    def increment_metric(self, metric: str, value: float = 1):
        """增加指标计数"""
        if metric in self.metrics:
            self.metrics[metric] += value
    
    def record_latency(self, latency_ms: float):
        """记录延迟"""
        self.metrics["latency_ms"] += latency_ms
        self.metrics["request_count"] += 1
        self.metrics["avg_latency_ms"] = (
            self.metrics["latency_ms"] / self.metrics["request_count"]
        )
    
    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        degraded_features = [
            feature for feature, info in self.features.items()
            if info["status"] != "healthy"
        ]
        
        return {
            "status": "healthy" if not degraded_features else "degraded",
            "uptime": time.time() - self.start_time,
            "active_requests": self.metrics["request_count"],
            "indexing_tasks": self.metrics["indexing_queue_length"],
            "degraded_features": degraded_features,
            "metrics": self.metrics,
            "features": self.features,
        }

# --- Global Instances ---
search_engine = SearchEngine()
degradation_manager = DegradationManager()

# --- App ---

app = FastAPI(
    title="CodePop API",
    description="面向 AI Agent 的代码专用检索基础设施 - 四路召回混合检索引擎",
    version="0.1.0",
    docs_url="/api-docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket Manager ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: defaultdict[str, List[str]] = defaultdict(list)
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            for channel in list(self.subscriptions.keys()):
                if client_id in self.subscriptions[channel]:
                    self.subscriptions[channel].remove(client_id)
    
    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)
    
    async def broadcast(self, message: dict, channel: str):
        for client_id in self.subscriptions[channel]:
            if client_id in self.active_connections:
                await self.active_connections[client_id].send_json(message)
    
    def subscribe(self, client_id: str, channel: str):
        if client_id not in self.subscriptions[channel]:
            self.subscriptions[channel].append(client_id)

ws_manager = ConnectionManager()

# --- Repository Routes ---

@app.post("/api/repos", response_model=Repository)
async def create_repo(name: str, path: str, git_url: Optional[str] = None):
    """创建代码仓库"""
    start_time = time.time()
    
    if any(r.path == path for r in repos.values()):
        raise HTTPException(status_code=409, detail="仓库已存在")
    
    repo_id = str(uuid.uuid4())
    now = datetime.now()
    
    repo = Repository(
        id=repo_id,
        name=name,
        path=path,
        git_url=git_url,
        created_at=now,
        updated_at=now,
    )
    
    repos[repo_id] = repo
    
    # 异步触发索引
    asyncio.create_task(run_indexing(repo_id))
    
    degradation_manager.record_latency((time.time() - start_time) * 1000)
    
    return repo

@app.get("/api/repos", response_model=List[Repository])
async def list_repos():
    """获取所有仓库列表"""
    return list(repos.values())

@app.get("/api/repos/{repo_id}", response_model=Repository)
async def get_repo(repo_id: str):
    """获取单个仓库详情"""
    repo = repos.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return repo

@app.patch("/api/repos/{repo_id}", response_model=Repository)
async def update_repo(repo_id: str, name: Optional[str] = None):
    """更新仓库信息"""
    repo = repos.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    if name:
        repo.name = name
    repo.updated_at = datetime.now()
    
    return repo

@app.delete("/api/repos/{repo_id}")
async def delete_repo(repo_id: str):
    """删除仓库"""
    if repo_id not in repos:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    # 删除相关数据
    files_to_delete = [fid for fid, f in files.items() if f.repo_id == repo_id]
    for fid in files_to_delete:
        del files[fid]
    
    symbols_to_delete = [sid for sid, s in symbols.items() if s.file_id in files_to_delete]
    for sid in symbols_to_delete:
        del symbols[sid]
    
    embeddings_to_delete = [eid for eid, e in embeddings.items() if e.file_id in files_to_delete]
    for eid in embeddings_to_delete:
        del embeddings[eid]
    
    edges_to_delete = [eid for eid, e in call_graph.items() if e.repo_id == repo_id]
    for eid in edges_to_delete:
        del call_graph[eid]
    
    del repos[repo_id]
    
    return {"status": "success"}

@app.post("/api/repos/{repo_id}/index")
async def trigger_index(repo_id: str):
    """触发仓库索引"""
    repo = repos.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    repo.status = RepoStatus.indexing
    repo.indexing_progress = 0
    repo.updated_at = datetime.now()
    
    asyncio.create_task(run_indexing(repo_id))
    
    return {"status": "indexing", "repo_id": repo_id}

@app.get("/api/repos/{repo_id}/files")
async def get_repo_files(repo_id: str):
    """获取仓库文件列表"""
    if repo_id not in repos:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    repo_files = [f for f in files.values() if f.repo_id == repo_id]
    return repo_files

@app.get("/api/repos/{repo_id}/symbols")
async def get_repo_symbols(repo_id: str):
    """获取仓库符号列表"""
    if repo_id not in repos:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    repo_files = [fid for fid, f in files.items() if f.repo_id == repo_id]
    repo_symbols = [s for s in symbols.values() if s.file_id in repo_files]
    
    return repo_symbols

@app.get("/api/repos/{repo_id}/call-graph")
async def get_repo_call_graph(repo_id: str):
    """获取仓库调用图"""
    if repo_id not in repos:
        raise HTTPException(status_code=404, detail="仓库不存在")
    
    edges = [e for e in call_graph.values() if e.repo_id == repo_id]
    return {"edges": edges}

# --- Search Routes ---

@app.post("/api/search", response_model=List[SearchResult])
async def search_code(query: SearchQuery):
    """四路召回混合检索"""
    start_time = time.time()
    
    try:
        results = await search_engine.search(query)
        
        # Add to history
        search_history.append({
            "query": query.query,
            "timestamp": datetime.now().isoformat(),
            "results": len(results),
            "mode": query.mode.value,
        })
        
        degradation_manager.record_latency((time.time() - start_time) * 1000)
        degradation_manager.increment_metric("request_count")
        
        return results
    
    except Exception as e:
        degradation_manager.report_health("search", "degraded", str(e))
        degradation_manager.increment_metric("error_count")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/search/symbol")
async def search_symbol(
    query: str,
    repo_id: Optional[str] = None,
    limit: int = 20,
):
    """符号精确搜索"""
    results = []
    
    for symbol in symbols.values():
        file = files.get(symbol.file_id)
        if not file:
            continue
        if repo_id and file.repo_id != repo_id:
            continue
        
        if query.lower() in symbol.name.lower():
            results.append({
                "id": symbol.id,
                "name": symbol.name,
                "type": symbol.type.value,
                "kind": symbol.kind,
                "file_path": file.path,
                "language": file.language,
                "line": symbol.line,
                "is_exported": symbol.is_exported,
            })
    
    return results[:limit]

@app.get("/api/search/history")
async def get_search_history(limit: int = 10):
    """获取搜索历史"""
    return search_history[-limit:][::-1]

# --- System Routes ---

@app.get("/api/health", response_model=SystemStatus)
async def health():
    """健康检查"""
    status = degradation_manager.get_status()
    return SystemStatus(
        status=status["status"],
        version="0.1.0",
        uptime=status["uptime"],
        active_requests=status["active_requests"],
        indexing_tasks=status["indexing_tasks"],
        degraded_features=status["degraded_features"],
        metrics=status["metrics"],
    )

@app.get("/api/health/ready")
async def health_ready():
    """就绪检查"""
    return {"status": "ready"}

@app.get("/api/health/live")
async def health_live():
    """存活检查"""
    return {"status": "live"}

@app.get("/api/metrics")
async def get_metrics():
    """获取监控指标"""
    return degradation_manager.get_status()["metrics"]

@app.get("/api/degradation")
async def get_degradation_status():
    """获取降级状态"""
    return degradation_manager.get_status()["features"]

# --- WebSocket Routes ---

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket 实时更新"""
    await ws_manager.connect(websocket, client_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("action") == "subscribe":
                channel = data.get("channel", "repos")
                ws_manager.subscribe(client_id, channel)
                await ws_manager.send_personal_message(
                    {"type": "subscribed", "channel": channel}, client_id
                )
            
            elif data.get("action") == "unsubscribe":
                channel = data.get("channel")
                if client_id in ws_manager.subscriptions[channel]:
                    ws_manager.subscriptions[channel].remove(client_id)
            
            elif data.get("action") == "ping":
                await ws_manager.send_personal_message({"type": "pong"}, client_id)
    
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)

# --- MCP Server Routes ---

@app.post("/mcp")
async def mcp_handler(request: dict):
    """MCP 协议处理"""
    start_time = time.time()
    
    try:
        method = request.get("method")
        params = request.get("params", {})
        
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            result = await handle_mcp_tool(tool_name, arguments)
            
            degradation_manager.record_latency((time.time() - start_time) * 1000)
            
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
            }
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"tools": get_mcp_tools()},
            }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32601, "message": "Method not found"},
            }
    
    except Exception as e:
        degradation_manager.increment_metric("error_count")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32603, "message": str(e)},
        }

async def handle_mcp_tool(tool_name: str, arguments: Dict[str, Any]):
    """处理 MCP 工具调用"""
    tools = {
        "search_code": search_code_mcp,
        "get_repo_info": get_repo_info_mcp,
        "list_repos": list_repos_mcp,
        "index_repo": index_repo_mcp,
        "get_file_content": get_file_content_mcp,
        "get_call_graph": get_call_graph_mcp,
    }
    
    if tool_name not in tools:
        raise ValueError(f"Tool not found: {tool_name}")
    
    return await tools[tool_name](arguments)

async def search_code_mcp(args: Dict[str, Any]):
    """MCP: 语义代码搜索"""
    query = args.get("query", "")
    repo_id = args.get("repo_id")
    
    results = await search_engine.search(SearchQuery(query=query, repo_id=repo_id, limit=10))
    return {"results": [r.dict() for r in results]}

async def get_repo_info_mcp(args: Dict[str, Any]):
    """MCP: 获取仓库信息"""
    repo_id = args.get("repo_id")
    repo = repos.get(repo_id)
    
    if not repo:
        return {"error": "Repository not found"}
    
    return repo.dict()

async def list_repos_mcp(args: Dict[str, Any]):
    """MCP: 列出所有仓库"""
    return {"repos": [r.dict() for r in repos.values()]}

async def index_repo_mcp(args: Dict[str, Any]):
    """MCP: 索引仓库"""
    path = args.get("path")
    
    existing = next((r for r in repos.values() if r.path == path), None)
    if existing:
        await trigger_index(existing.id)
        return {"status": "indexing", "repo_id": existing.id}
    
    name = path.split("/")[-1]
    repo = await create_repo(name=name, path=path)
    return {"status": "created", "repo_id": repo.id}

async def get_file_content_mcp(args: Dict[str, Any]):
    """MCP: 获取文件内容"""
    file_id = args.get("file_id")
    file = files.get(file_id)
    
    if not file:
        return {"error": "File not found"}
    
    return {
        "content": file.content,
        "path": file.path,
        "language": file.language,
    }

async def get_call_graph_mcp(args: Dict[str, Any]):
    """MCP: 获取调用图"""
    repo_id = args.get("repo_id")
    
    edges = [e.dict() for e in call_graph.values() if e.repo_id == repo_id]
    return {"edges": edges}

def get_mcp_tools():
    """获取 MCP 工具列表"""
    return [
        {
            "name": "search_code",
            "description": "四路召回混合语义代码搜索",
            "parameters": {
                "query": {"type": "string", "description": "搜索查询"},
                "repo_id": {"type": "string", "description": "仓库ID（可选）"},
            },
        },
        {
            "name": "get_repo_info",
            "description": "获取仓库详细信息",
            "parameters": {
                "repo_id": {"type": "string", "description": "仓库ID"},
            },
        },
        {
            "name": "list_repos",
            "description": "列出所有已索引仓库",
            "parameters": {},
        },
        {
            "name": "index_repo",
            "description": "索引新仓库",
            "parameters": {
                "path": {"type": "string", "description": "仓库路径"},
            },
        },
        {
            "name": "get_file_content",
            "description": "获取文件内容",
            "parameters": {
                "file_id": {"type": "string", "description": "文件ID"},
            },
        },
        {
            "name": "get_call_graph",
            "description": "获取函数调用图",
            "parameters": {
                "repo_id": {"type": "string", "description": "仓库ID"},
            },
        },
    ]

# --- Indexing Logic ---

async def run_indexing(repo_id: str):
    """执行仓库索引"""
    repo = repos.get(repo_id)
    if not repo:
        return
    
    degradation_manager.report_health("indexing", "healthy")
    
    try:
        # Mock files for demonstration
        mock_files = [
            {"name": "main.py", "language": "python"},
            {"name": "utils.py", "language": "python"},
            {"name": "api.py", "language": "python"},
            {"name": "config.py", "language": "python"},
        ]
        
        total_files = len(mock_files)
        repo.indexing_progress = 0
        
        for i, mock_file in enumerate(mock_files):
            # Create file
            file_content = generate_mock_content(mock_file["name"], mock_file["language"])
            content_hash = hashlib.sha256(file_content.encode()).hexdigest()
            
            file = CodeFile(
                id=str(uuid.uuid4()),
                repo_id=repo_id,
                path=f"{repo.path}/{mock_file['name']}",
                language=mock_file["language"],
                content=file_content,
                content_hash=content_hash,
                size_bytes=len(file_content),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            
            files[file.id] = file
            
            # Create symbols and call graph
            await extract_symbols_and_graph(file)
            
            # Create embeddings
            await create_embeddings(file)
            
            # Update progress
            repo.indexing_progress = ((i + 1) / total_files) * 100
            repo.file_count += 1
            
            # Broadcast progress
            await ws_manager.broadcast({
                "type": "repo_update",
                "repo_id": repo_id,
                "progress": repo.indexing_progress,
            }, "repos")
            
            await asyncio.sleep(0.5)  # Simulate indexing delay
        
        repo.status = RepoStatus.indexed
        repo.last_indexed_at = datetime.now()
        repo.symbol_count = len([s for s in symbols.values() if s.repo_id == repo_id])
        repo.embedding_count = len([e for e in embeddings.values() if e.file_id in files and files[e.file_id].repo_id == repo_id])
        
        await ws_manager.broadcast({
            "type": "repo_indexed",
            "repo_id": repo_id,
        }, "repos")
        
    except Exception as e:
        repo.status = RepoStatus.error
        degradation_manager.report_health("indexing", "degraded", str(e))
        await ws_manager.broadcast({
            "type": "repo_error",
            "repo_id": repo_id,
            "error": str(e),
        }, "repos")

def generate_mock_content(filename: str, language: str) -> str:
    """生成模拟代码内容"""
    if language == "python":
        if "main" in filename:
            return '''#!/usr/bin/env python3
"""Main entry point for the application."""

import asyncio
from fastapi import FastAPI
from api import router
from utils import setup_logging, initialize_db
from config import settings

app = FastAPI(title="CodePop API", version="0.1.0")

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()
    initialize_db()
    app.include_router(router)
    return app

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}

async def main():
    """Main entry point."""
    application = create_app()
    # Run with uvicorn
    import uvicorn
    await uvicorn.main(["--host", "0.0.0.0", "--port", "3000"])

if __name__ == "__main__":
    asyncio.run(main())
'''
        elif "utils" in filename:
            return '''"""Utility functions for the application."""

import logging
import os
from typing import Optional

def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

def initialize_db(connection_string: Optional[str] = None) -> None:
    """Initialize database connection."""
    from database import Database
    db_url = connection_string or os.getenv("DATABASE_URL")
    Database.initialize(db_url)

def calculate_similarity(vec1: list, vec2: list) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    return dot_product / (norm1 * norm2) if norm1 and norm2 else 0.0
'''
        elif "api" in filename:
            return '''"""API routes for the application."""

from fastapi import APIRouter, HTTPException
from models import Repository, SearchQuery, SearchResult
from services import search_service, repo_service

router = APIRouter(prefix="/api")

@router.post("/repos", response_model=Repository)
async def create_repo(name: str, path: str):
    """Create a new repository."""
    return await repo_service.create_repo(name, path)

@router.get("/repos", response_model=list[Repository])
async def list_repos():
    """List all repositories."""
    return await repo_service.list_repos()

@router.post("/search", response_model=list[SearchResult])
async def search_code(query: SearchQuery):
    """Search code using hybrid retrieval."""
    return await search_service.search(query)
'''
        else:
            return '''"""Configuration settings for the application."""

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings."""
    
    database_url: str = "sqlite:///./codepop.db"
    api_port: int = 3000
    debug: bool = False
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()
'''
    
    return f"// {filename}\nconsole.log('Hello World');"

async def extract_symbols_and_graph(file: CodeFile):
    """提取符号和调用图"""
    # Extract symbols
    symbols_to_create = [
        {"name": "create_app", "type": "function", "line": 12},
        {"name": "main", "type": "function", "line": 28},
        {"name": "app", "type": "variable", "line": 10},
    ]
    
    created_symbols = []
    
    for sym_data in symbols_to_create:
        symbol = Symbol(
            id=str(uuid.uuid4()),
            file_id=file.id,
            repo_id=file.repo_id,
            name=sym_data["name"],
            type=SymbolType[sym_data["type"]],
            kind=sym_data["type"],
            line=sym_data["line"],
            column=0,
            end_line=sym_data["line"] + 5,
            end_column=0,
            is_exported=True,
        )
        symbols[symbol.id] = symbol
        created_symbols.append(symbol)
    
    # Create call graph edges
    if len(created_symbols) >= 2:
        edge = CallGraphEdge(
            id=str(uuid.uuid4()),
            source_symbol_id=created_symbols[0].id,  # main
            target_symbol_id=created_symbols[1].id,  # create_app
            source_file_id=file.id,
            target_file_id=file.id,
            repo_id=file.repo_id,
            call_type="direct",
        )
        call_graph[edge.id] = edge

async def create_embeddings(file: CodeFile):
    """创建文件嵌入"""
    # Chunk the content
    lines = file.content.split("\n")
    chunk_size = 50
    chunks = [lines[i:i+chunk_size] for i in range(0, len(lines), chunk_size)]
    
    for i, chunk_lines in enumerate(chunks):
        chunk_content = "\n".join(chunk_lines)
        embedding = search_engine.embedding_manager.generate_embedding(chunk_content)
        
        emb = Embedding(
            id=str(uuid.uuid4()),
            file_id=file.id,
            chunk_index=i,
            content=chunk_content,
            embedding=embedding,
            token_count=len(chunk_content) // 4,
            created_at=datetime.now(),
        )
        
        embeddings[emb.id] = emb

# --- Prometheus Metrics Endpoint ---

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    status = degradation_manager.get_status()
    metrics = status["metrics"]
    
    lines = []
    lines.append("# HELP codepop_request_count Total requests")
    lines.append(f"# TYPE codepop_request_count counter")
    lines.append(f"codepop_request_count {metrics['request_count']}")
    
    lines.append("# HELP codepop_error_count Total errors")
    lines.append(f"# TYPE codepop_error_count counter")
    lines.append(f"codepop_error_count {metrics['error_count']}")
    
    lines.append("# HELP codepop_avg_latency_ms Average latency")
    lines.append(f"# TYPE codepop_avg_latency_ms gauge")
    lines.append(f"codepop_avg_latency_ms {metrics['avg_latency_ms']}")
    
    lines.append("# HELP codepop_indexing_tasks Active indexing tasks")
    lines.append(f"# TYPE codepop_indexing_tasks gauge")
    lines.append(f"codepop_indexing_tasks {metrics['indexing_queue_length']}")
    
    lines.append("# HELP codepop_uptime_seconds Uptime in seconds")
    lines.append(f"# TYPE codepop_uptime_seconds gauge")
    lines.append(f"codepop_uptime_seconds {status['uptime']}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)

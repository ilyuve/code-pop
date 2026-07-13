from collections import deque
from typing import List, Dict, Optional
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from models import CallGraphEdge, FrameworkRoute, Symbol


@dataclass
class ImpactResult:
    symbol: str
    file_path: str
    line: int
    affected_routes: List[Dict]
    upstream_chain: List[str]
    depth: int
    risk_level: str


class ImpactAnalyzer:
    """分析代码变更的影响面。"""

    def __init__(self, db_session: Session):
        self.db = db_session

    def analyze(
        self,
        symbol_name: str,
        repo_id,
        max_depth: int = 5,
    ) -> ImpactResult:
        """
        从 symbol_name 出发，向上遍历调用链，找到所有受影响的 HTTP 路由。

        Args:
            symbol_name: 目标函数/方法名，如 "send_notification"
            repo_id: 仓库 ID
            max_depth: 最大向上遍历深度，防止循环依赖导致无限递归

        Returns:
            ImpactResult，包含受影响路由和调用链
        """
        visited = set()
        queue = deque([(symbol_name, 0, [symbol_name])])

        affected_routes: List[Dict] = []
        upstream_chain: List[str] = []

        while queue:
            current, depth, chain = queue.popleft()

            if current in visited or depth > max_depth:
                continue
            visited.add(current)

            routes = self._find_routes_by_handler(current, repo_id)
            for route in routes:
                affected_routes.append({
                    "framework": route.framework,
                    "method": route.http_method,
                    "path": route.path,
                    "handler": route.handler_symbol,
                })

            callers = self._get_callers(current, repo_id)
            for caller in callers:
                new_chain = chain + [caller]
                queue.append((caller, depth + 1, new_chain))

                if len(new_chain) > len(upstream_chain):
                    upstream_chain = new_chain

        symbol_info = self._get_symbol_info(symbol_name, repo_id)

        risk = self._calculate_risk(affected_routes, upstream_chain)

        return ImpactResult(
            symbol=symbol_name,
            file_path=symbol_info.file_path if symbol_info else "",
            line=symbol_info.line if symbol_info else 0,
            affected_routes=affected_routes,
            upstream_chain=upstream_chain,
            depth=len(upstream_chain) - 1,
            risk_level=risk,
        )

    def _find_routes_by_handler(self, handler_name: str, repo_id) -> List[FrameworkRoute]:
        """根据 handler 名称查找路由。"""
        return self.db.query(FrameworkRoute).filter(
            FrameworkRoute.repo_id == repo_id,
            FrameworkRoute.handler_symbol == handler_name,
        ).all()

    def _get_callers(self, symbol_name: str, repo_id) -> List[str]:
        """查找调用指定符号的符号名列表。"""
        symbol_ids = self.db.query(Symbol.id).filter(
            Symbol.repo_id == repo_id,
            Symbol.name == symbol_name,
        ).all()

        if not symbol_ids:
            return []

        target_ids = [s.id for s in symbol_ids]

        edge_ids = self.db.query(CallGraphEdge.source_symbol_id).filter(
            CallGraphEdge.repo_id == repo_id,
            CallGraphEdge.target_symbol_id.in_(target_ids),
        ).distinct().all()

        if not edge_ids:
            return []

        source_ids = [e.source_symbol_id for e in edge_ids]

        callers = self.db.query(Symbol.name).filter(
            Symbol.repo_id == repo_id,
            Symbol.id.in_(source_ids),
        ).distinct().all()

        return [c.name for c in callers]

    def _get_symbol_info(self, symbol_name: str, repo_id) -> Optional[Symbol]:
        """获取符号位置信息。"""
        return self.db.query(Symbol).filter(
            Symbol.repo_id == repo_id,
            Symbol.name == symbol_name,
        ).first()

    def _calculate_risk(self, routes: List[Dict], chain: List[str]) -> str:
        """根据受影响路由数量和调用链深度计算风险等级。"""
        if len(routes) > 0:
            return "high"
        if len(chain) > 3:
            return "medium"
        return "low"
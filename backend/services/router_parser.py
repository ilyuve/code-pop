import re
from dataclasses import dataclass
from typing import List


@dataclass
class RouteInfo:
    framework: str
    method: str
    path: str
    handler: str
    line: int


class RouterParser:
    """从代码文本中提取 Web 框架路由定义。"""

    def parse(self, code: str, language: str) -> List[RouteInfo]:
        """根据语言选择对应的解析器。"""
        if language == "python":
            return self._parse_python(code)
        elif language in ("javascript", "typescript"):
            return self._parse_js(code)
        elif language == "java":
            return self._parse_java(code)
        return []

    def _parse_python(self, code: str) -> List[RouteInfo]:
        """解析 Python 框架路由：FastAPI / Flask / Django。"""
        routes = []
        lines = code.split('\n')

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            match = re.search(
                r'@\w+\.(get|post|put|delete|patch|head|options)\(["\']([^"\']+)["\']',
                stripped,
                re.IGNORECASE
            )
            if match:
                method = match.group(1).upper()
                path = match.group(2)
                handler = self._find_next_python_def(lines, i)
                routes.append(RouteInfo("fastapi", method, path, handler, i))
                continue

            match = re.search(
                r'@\w+\.route\(["\']([^"\']+)["\']',
                stripped
            )
            if match:
                path = match.group(1)
                method = "GET"
                methods_match = re.search(r'methods=\[["\']([A-Z]+)["\']', stripped)
                if methods_match:
                    method = methods_match.group(1)
                handler = self._find_next_python_def(lines, i)
                routes.append(RouteInfo("flask", method, path, handler, i))
                continue

            match = re.search(
                r'(?:path|re_path)\(["\']([^"\']+)["\'],\s*(\w+)',
                stripped
            )
            if match:
                path = match.group(1)
                handler = match.group(2)
                routes.append(RouteInfo("django", "ANY", path, handler, i))

        return routes

    def _parse_js(self, code: str) -> List[RouteInfo]:
        """解析 Express 路由。"""
        routes = []
        for i, line in enumerate(code.split('\n'), start=1):
            match = re.search(
                r'\.(get|post|put|delete|patch|head|options)\(["\']([^"\']+)["\']',
                line.strip()
            )
            if match:
                method = match.group(1).upper()
                path = match.group(2)
                routes.append(RouteInfo("express", method, path, "", i))
        return routes

    def _parse_java(self, code: str) -> List[RouteInfo]:
        """解析 Spring Boot 路由。"""
        routes = []
        for i, line in enumerate(code.split('\n'), start=1):
            match = re.search(
                r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\(["\']([^"\']+)["\']',
                line.strip()
            )
            if match:
                mapping_type = match.group(1)
                path = match.group(2)
                if mapping_type == "RequestMapping":
                    method = "ANY"
                else:
                    method = mapping_type.replace("Mapping", "").upper()
                routes.append(RouteInfo("spring", method, path, "", i))
        return routes

    def _find_next_python_def(self, lines: List[str], start: int) -> str:
        """从 start 行开始找下一个 Python 函数/类定义。"""
        for j in range(start, min(start + 5, len(lines))):
            match = re.search(r'^(?:async\s+)?def\s+(\w+)', lines[j])
            if match:
                return match.group(1)
            match = re.search(r'^class\s+(\w+)', lines[j])
            if match:
                return match.group(1)
        return ""
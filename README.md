# CodePop - AI 代码检索基础设施

> 让 AI 更精准地理解你的代码仓库

## 简介

CodePop 是面向 AI Agent 的代码专用检索基础设施。通过混合索引、智能检索与上下文压缩，为 Claude Code、Codex、Cursor 等编码 Agent 提供精准的代码上下文，降低幻觉率，提升代码理解深度。

**核心优势**：
- 🚀 **开箱即用**：Docker 一键部署，5 分钟完成配置
- 🎯 **精准检索**：向量 + 符号 + 图检索的混合索引
- 📊 **上下文压缩**：智能 Token 控制，降低 API 成本
- 🔌 **多 Agent 支持**：原生支持 Claude Code、Cursor、VS Code 等
- 🐘 **PostgreSQL + pgvector**：成熟稳定，运维友好

## 快速开始

### 1. 一键启动

```bash
# 克隆仓库
git clone https://github.com/your-username/codepop.git
cd codepop

# 启动服务
docker compose up -d

# 打开管理界面
open http://localhost:8080
```

### 2. 配置仓库

通过 Web 界面配置：
1. 打开 http://localhost:8080
2. 选择 **快速配置向导**
3. 添加 GitHub/Gitee 仓库或本地代码路径
4. 配置向量嵌入服务（OpenAI / 本地模型）

### 3. 接入 Agent

**Claude Code**：
```bash
claude config add mcp-server codepop npx @codepop/mcp-server
```

**Cursor**（settings.json）：
```json
{
  "mcpServers": {
    "codepop": {
      "url": "http://localhost:8081/mcp"
    }
  }
}
```

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent CLI 层                         │
│  Claude Code │ Cursor │ VS Code │ 自研 Agent                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (MCP / REST)                    │
│  • MCP Server（原生支持 Claude Code）                        │
│  • REST API（兼容 OpenAI 格式）                             │
│  • WebSocket（实时同步）                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      检索服务层                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │ 意图理解    │ │ 混合检索    │ │ 上下文补全  │          │
│  │ (规则引擎)  │ │ (向量+符号) │ │ (图遍历)   │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 PostgreSQL + pgvector                       │
│  • 向量索引 (embedding)                                    │
│  • 符号索引 (symbols)                                       │
│  • 调用图关系 (call_graph)                                 │
│  • Git 历史 (git_commits)                                  │
└─────────────────────────────────────────────────────────────┘
```

## 核心功能

### 🔍 混合检索引擎
- **向量检索**：基于 pgvector 的语义相似度检索
- **符号检索**：精确匹配函数、类、变量名称
- **图检索**：调用链分析、影响面分析
- **时间衰减**：优先返回近期修改的代码

### 📦 增量索引
- Git Webhook 触发实时同步
- 文件系统监听自动更新
- 支持全量/增量两种模式

### 🎯 上下文压缩
- 智能 Token 控制，自动压缩到模型窗口限制
- 优先级排序：核心代码 > 调用链 > 类型定义 > 测试文件
- 支持 8K/32K/128K 等多种模型窗口

### 🔌 多 Agent 支持
- Claude Code（原生 MCP）
- Cursor（MCP Server）
- VS Code / JetBrains（REST API）
- 自定义 Agent（SDK）

## 部署方式

### 本地开发
```bash
docker compose up -d
```

### 生产环境
```bash
# 配置环境变量
cp .env.example .env
vim .env

# 启动
docker compose -f docker-compose.prod.yml up -d
```

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql://postgres@localhost:5432/codepop` |
| `OPENAI_API_KEY` | OpenAI API Key | 空 |
| `CODEPOP_PORT` | 服务端口 | `8080` |
| `CODEPOP_MCP_PORT` | MCP 端口 | `8081` |

### 向量嵌入配置

支持多种嵌入服务：
- OpenAI（推荐）
- Azure OpenAI
- 本地模型（Ollama）
- Cohere

## 性能指标

| 指标 | 目标值 |
|------|--------|
| 查询延迟 P95 | < 500ms |
| Top-5 命中率 | > 85% |
| Token 压缩率 | 60-80% |
| 增量同步延迟 | < 3s |

## 项目结构

```
codepop/
├── arch/                    # 技术文档
│   └── postgresql-pgvector-design.md
├── docker/                  # Docker 配置
│   ├── docker-compose.yml
│   └── Dockerfile
├── docs/                    # 用户文档
├── benchmarks/              # 评测数据集
├── src/                     # 源代码
│   ├── server/              # 后端服务
│   ├── web/                 # Web 管理界面
│   └── cli/                 # CLI 工具
└── README.md
```

## 贡献指南

欢迎提交 PR 和 Issue！

### 开发环境

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 运行测试
npm test
```

## 许可证

MIT License

## 联系方式

- 官方文档：https://docs.codepop.dev
- GitHub：https://github.com/your-username/codepop
- 问题反馈：https://github.com/your-username/codepop/issues

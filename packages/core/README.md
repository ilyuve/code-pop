# @codepop/core

CodePop 核心库，提供数据库适配层与业务服务。

## 功能

- 数据库适配器工厂模式
- PostgreSQL + pgvector 适配器
- Mock 适配器（测试用）
- 代码检索服务

## 安装

```bash
pnpm install
```

## 开发

```bash
# 构建
pnpm build

# 监听模式
pnpm dev

# 测试
pnpm test
```

## 目录结构

```
src/
├── data/                # 数据库适配层
│   ├── adapter.ts       # 统一接口定义
│   ├── adapter-factory.ts # 工厂模式
│   ├── postgresql-adapter.ts # PostgreSQL 实现
│   └── mock-adapter.ts  # Mock 实现
├── service/             # 业务服务
│   └── code-search-service.ts
└── index.ts             # 导出入口
```

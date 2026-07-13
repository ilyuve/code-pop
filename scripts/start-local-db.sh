#!/bin/bash

echo "启动本地 PostgreSQL (仅数据库)..."
docker compose -f docker-compose.local.yml up -d

echo ""
echo "等待数据库就绪..."
sleep 5

echo ""
echo "数据库已启动，端口: 5432"
echo "连接信息:"
echo "  数据库: codepop"
echo "  用户: postgres"
echo "  密码: codepop123"
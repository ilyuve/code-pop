# Contributing to CodePop

感谢你对 CodePop 项目的关注和贡献！以下是参与贡献的指南。

## 📋 贡献流程

1. **Fork 仓库**：点击 GitHub 页面右上角的 "Fork" 按钮
2. **克隆仓库**：`git clone https://github.com/your-username/codepop.git`
3. **创建分支**：`git checkout -b feature/your-feature-name`
4. **提交修改**：`git commit -m "feat: add your feature"`
5. **推送分支**：`git push origin feature/your-feature-name`
6. **创建 PR**：在 GitHub 上提交 Pull Request

## 🐛 报告问题

使用 GitHub Issues 报告问题时，请提供：
- 清晰的问题描述
- 复现步骤
- 预期行为和实际行为
- 截图或错误日志（如有）

## ✨ 提交功能建议

欢迎提出功能建议！在提交前请先查看现有 Issues，避免重复。

## 📝 代码规范

### 代码风格
- TypeScript/JavaScript：使用 ESLint，遵循 Airbnb 规范
- Python：使用 Black 格式化，Flake8 检查
- 所有代码必须通过 lint 检查

### 提交信息规范

使用 Conventional Commits 格式：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**类型说明**：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码风格（不影响逻辑）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具相关

## 🧪 测试要求

- 新增功能必须附带单元测试
- 所有测试必须通过才能合并
- 代码覆盖率目标：>= 80%

## 📄 许可证

所有贡献的代码均遵循 MIT 许可证。

---

再次感谢你的贡献！🎉

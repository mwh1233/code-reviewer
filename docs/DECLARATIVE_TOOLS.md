# 声明式工具说明

## 目标

Phase 2 将工具系统从 class-based 样板代码迁移到声明式函数注册：

- 工具定义就是函数本身
- 用 `@tool` 装饰器声明能力
- 用类型注解自动生成 JSON Schema
- 新增工具不需要修改主循环

## 关键文件

- `src/codereviewer/tools/declarative.py`
- `src/codereviewer/tools/registry.py`
- `src/codereviewer/tools/auto_discover.py`
- `src/codereviewer/tools/builtin/`

## 新增一个工具的步骤

1. 在 `src/codereviewer/tools/builtin/` 下新增一个 `.py` 文件
2. 写一个带 `@tool(...)` 的函数
3. 通过类型注解描述输入参数
4. 如需运行时上下文，接收 `ToolExecutionContext`
5. 返回 `dict`，由 registry 自动包装为 `ToolResult`

示例：

```python
from codereviewer.domain.models import ToolExecutionContext
from codereviewer.tools.declarative import tool


@tool(
    name="list_snapshot_files",
    description="List changed files from the immutable review snapshot.",
    execution_policy="snapshot_read_only",
    max_output_chars=4000,
    failure_behavior="return_error",
)
def list_snapshot_files(
    context: ToolExecutionContext,
) -> dict[str, object]:
    return {"files": list(context.snapshot.changed_files)}
```

## 设计约束

- 只允许显式注册的工具进入主流程
- 新增工具不能要求修改 `AgentRuntime` 或 `ReviewRunner` 主循环
- 不向模型暴露任意 shell
- 工具必须是只读或受控能力
- 输出必须有界，错误必须结构化返回

## 自动发现机制

内置工具通过 `discover_and_register()` 从受控目录自动发现：

- 扫描 `tools/builtin/` 下的模块
- 跳过 `_` 开头模块
- 只注册带 `@tool` 标记的函数

因此，新增普通内置工具时不需要修改 `__init__.py`。

## 当前内置工具

- `read_diff`
- `read_file`
- `list_changed_files`
- `find_references`

这些工具都通过同一个 `ToolRegistry` 暴露给：

- 阶段 4 规则引擎
- 阶段 5 `AgentRuntime`

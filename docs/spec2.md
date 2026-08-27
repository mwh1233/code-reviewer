# spec2.md — v2 迭代方案：Agent Runtime + 声明式工具

> 版本：v2.0
> 日期：2026-08-27
> 前置文档：docs/SPEC.md（v1 需求）、docs/mvp_review.md（v1 代码审查）、docs/ARCHITECTURE.md（v1 架构）
> 参考：[toolregistry](https://toolregistry.readthedocs.io/) 纯声明式工具管理

---

## 1. 背景与目标

### 1.1 v1 现状

v1 已完成 8 阶段 Pipeline 全流程跑通，工程化基础设施完善：
- 预算四级降级、Trace artifact 持久化、全链路 Security 脱敏
- 置信度独立判定（EvidenceValidator）、评论去重合并（FindingAggregator）
- 发布控制 + head SHA 校验、Resume 支持全部 8 阶段

### 1.2 v1 核心问题

详见 mvp_review.md，两个核心问题：

1. **LLM 审查是单次 prompt-response，没有 tool-use 循环**：模型不能主动调 `read_file` / `read_diff` / `find_references` 获取上下文，只能看一眼截断后的 diff 就输出结论。工具系统只有规则引擎在用，LLM 完全不用。
2. **工具定义样板代码多，非声明式**：每个工具需要手动写 Input Pydantic 模型、`ToolSpec`（name/description/input_schema/output_schema/execution_policy/max_output_chars/failure_behavior）、`run()` 方法手动 validate 和构造 ToolResult。新增工具成本高，schema 容易和实际参数不一致。

### 1.3 v2 核心目标（两件事）

| 目标 | 说明 | 验收标准 |
|---|---|---|
| **G1: Agent Runtime** | 把 LLM 审查从单次调用改为多轮 tool-use 循环，模型能主动调工具获取上下文、提交评论、结束循环 | 模型能调用 read_file/read_diff/find_references，能通过 code_comment 提交评论，通过 task_done 结束 |
| **G2: 声明式工具** | 用 `@tool` 装饰器 + 类型注解自动生成 JSON Schema，工具定义就是函数本身，消除样板代码 | 每个工具从 ~60 行降到 ~15 行，schema 从类型注解自动生成，新增工具只需写一个函数 |

### 1.4 v2 配套目标（非核心，但随核心一起做）

| 目标 | 说明 |
|---|---|
| G3: 评论定位校验 | 验证 LLM 返回的 file/line 是否在 diff 新增行范围内，无效定位降级为 REFERENCE |
| G4: Trace 增强 | 记录每轮工具调用和评论提交，可追溯每条评论的产生过程 |
| G5: LLM Adapter 扩展 | 支持 function calling（tools 参数 + tool_calls 响应） |

### 1.5 v2 非目标

明确不做，避免范围蔓延：
- ❌ Review Filter（独立 LLM 调用过滤错误评论）→ v3
- ❌ 文件分组 + 并发执行 → v3
- ❌ Plan 阶段（大变更先做审查计划）→ v3
- ❌ Context compression（多轮 prompt 压缩）→ v3
- ❌ 跨文件评论重定位 → v3
- ❌ 多 Agent 编排 → 超出范围
- ❌ Web UI → 超出范围
- ❌ 直接引入 toolregistry 第三方库 → 自己实现轻量版，控制完全在手里

---

## 2. 整体架构

### 2.1 8 阶段 Pipeline（保持不变，内部增强）

```
┌──────────────────────────────────────────────────────────────────────┐
│                         v2 Review Pipeline                             │
├────────────────────┬─────────────────────────────────────────────────┤
│ 1 INPUT_VALIDATED   │ 保持不变                                         │
│ 2 SNAPSHOT_CREATED  │ 保持不变                                         │
│ 3 ANALYSIS_PREPARED │ 保持不变                                         │
│ 4 DETERMINISTIC     │ 保持不变（规则引擎用新的声明式工具接口，向后兼容）│
│   _CHECKS_DONE      │                                                  │
├────────────────────┼─────────────────────────────────────────────────┤
│ 5 FINDINGS          │ ⭐ 核心重构：AgentRuntime 多轮 tool-use 循环     │
│   _GENERATED        │    使用声明式工具系统                              │
├────────────────────┼─────────────────────────────────────────────────┤
│ 6 FINDINGS          │ ⭐ 增强：CommentLocator 定位校验 + 现有置信度/去重│
│   _VERIFIED         │                                                  │
├────────────────────┼─────────────────────────────────────────────────┤
│ 7 OUTPUTS_PREPARED  │ 保持不变                                         │
│ 8 PUBLISH           │ 保持不变                                         │
│   _ATTEMPTED        │                                                  │
└────────────────────┴─────────────────────────────────────────────────┘
```

### 2.2 工具层架构重构

```
v1 工具层（当前）：
  ToolRegistry（存 Tool 类实例）
    └─ Tool 类（meta: ToolSpec 手动 schema + run() 方法）
         └─ 每个工具 ~60 行样板代码

v2 工具层（声明式）：
  ToolRegistry（存装饰后的函数 + 自动生成的 schema）
    └─ @tool 装饰的函数（类型注解 → 自动 JSON Schema）
         └─ 每个工具 ~15 行，无样板代码
```

### 2.3 新增/改动模块总览

| 类型 | 模块 | 路径 | 说明 |
|---|---|---|---|
| 🆕 新增 | AgentRuntime | `services/agent_runtime.py` | 外层多轮 + 内层 tool-use 循环核心 |
| 🆕 新增 | 声明式工具装饰器 | `tools/declarative.py` | `@tool` 装饰器 + 类型注解转 JSON Schema |
| 🆕 新增 | 工具自动发现 | `tools/auto_discover.py` | 扫描目录自动注册 `@tool` 装饰的函数，新增工具只需加文件 |
| 🆕 新增 | ToolExecutionContext | `domain/models.py` | 工具执行上下文（snapshot/provider 注入） |
| 🆕 新增 | CommentLocator | `services/comment_locator.py` | 评论定位校验（配套） |
| ✏️ 改动 | ToolRegistry | `tools/registry.py` | 支持声明式工具注册、schema 生成、执行 |
| ✏️ 改动 | ToolEngine | `services/tool_engine.py` | 适配新接口，保持对规则引擎的向后兼容 |
| ✏️ 改动 | 内置工具 | `tools/builtin/*.py` | 全部改为声明式函数 |
| ✏️ 改动 | OpenAICompatibleLLMProvider | `adapters/llm/openai_compatible.py` | 支持 function calling |
| ✏️ 改动 | ReviewRunner | `services/review_runner.py` | 阶段 5 接入 AgentRuntime，阶段 6 接入 CommentLocator |
| ✏️ 改动 | 领域模型 | `domain/models.py` | 新增 AgentLoopState/ToolCallRecord/ToolChatMessage 等 |
| ✏️ 改动 | TraceManager | `services/trace_manager.py` | 支持 details 字段，记录工具调用 |
| ✏️ 改动 | LLMProvider Protocol | `domain/interfaces/llm.py` | 新增 chat_with_tools 方法 |

---

## 3. 核心一：Agent Runtime 详细设计

### 3.1 整体结构：外层多轮 × 内层 tool-use 循环

```
AgentRuntime.run(snapshot, existing_findings) -> list[Finding]
│
├─ 构建初始上下文（system prompt + diff 摘要 + 规则已发现 finding + 工具列表）
│
├─ 外层循环（round = 1 .. max_rounds，默认 2）
│    │
│    ├─ 注入上一轮已确认的评论（round 1 为空）
│    ├─ 预算检查（plan_llm_call）→ 决定降级级别或停止
│    │
│    ├─ 内层 Agent 循环（tool-use loop）
│    │    │
│    │    ├─ 发送 messages + tools 给 LLM
│    │    ├─ 解析响应：
│    │    │   ├─ tool_calls → 分发处理
│    │    │   │   ├─ code_comment → 收集评论，追加 tool_result，继续
│    │    │   │   ├─ task_done → 结束内层循环
│    │    │   │   └─ read_file/read_diff/find_references/list_changed_files
│    │    │   │       → 委托声明式 ToolRegistry 执行，结果追加为 tool role 消息
│    │    │   └─ 无 tool_calls（纯文本）→ 记录到 trace，继续（或空轮终止）
│    │    │
│    │    └─ 终止条件：
│    │         ├─ task_done → 正常结束
│    │         ├─ 达到 max_tool_rounds（默认 15）→ 强制结束
│    │         ├─ 连续 N 轮空响应（默认 3）→ 结束
│    │         └─ 预算耗尽 → grace round（只允许 code_comment / task_done）
│    │
│    ├─ 收集本轮新评论，记录 trace
│    └─ 终止条件：无新评论 / 达到 max_rounds / 预算耗尽
│
└─ 输出：所有轮次收集的评论列表
```

### 3.2 工具分类与职责边界

| 类别 | 工具名 | 处理方 | 说明 |
|---|---|---|---|
| **控制工具** | `code_comment` | AgentRuntime 内部 | 提交一条评论，参数：file/line/summary/severity/explanation/suggested_fix |
| **控制工具** | `task_done` | AgentRuntime 内部 | 声明审查完成，结束内层循环 |
| **分析工具** | `read_file` | 声明式 ToolRegistry | 读取完整文件内容（截断到 max_chars） |
| **分析工具** | `read_diff` | 声明式 ToolRegistry | 读取指定文件的 diff |
| **分析工具** | `list_changed_files` | 声明式 ToolRegistry | 列出所有变更文件 |
| **分析工具** | `find_references` | 声明式 ToolRegistry | 查找符号引用（grep） |

**关键设计原则**：
- 控制工具由 AgentRuntime 直接处理，因为它们改变循环状态（收集评论 / 结束循环）
- 分析工具委托给声明式 ToolRegistry，复用自动 schema 生成、上下文注入、错误处理
- 工具定义（schema）统一由 AgentRuntime 组装：控制工具硬编码，分析工具从 ToolRegistry 动态获取

### 3.3 控制工具 schema

#### code_comment

```json
{
  "name": "code_comment",
  "description": "Submit one code review comment. Call this whenever you find a concrete issue grounded in the diff or file content you have read. You may call this multiple times.",
  "parameters": {
    "type": "object",
    "properties": {
      "file": {"type": "string", "description": "File path relative to repo root. Must be one of the changed files."},
      "line": {"type": "integer", "description": "Line number in the NEW file (1-based). Must point to an added line in the diff."},
      "summary": {"type": "string", "description": "One-line summary of the issue."},
      "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
      "explanation": {"type": "string", "description": "Detailed explanation of why this is an issue, referencing specific code."},
      "suggested_fix": {"type": "string", "description": "Optional suggested fix.", "nullable": true}
    },
    "required": ["file", "line", "summary", "severity", "explanation"]
  }
}
```

#### task_done

```json
{
  "name": "task_done",
  "description": "Declare that you have completed the review. Call this when you have no more issues to report or no more tools to call. After this call, the review loop ends.",
  "parameters": {
    "type": "object",
    "properties": {
      "reason": {"type": "string", "description": "Brief reason for completing (e.g. 'all files reviewed', 'no more issues found')."}
    },
    "required": ["reason"]
  }
}
```

### 3.4 AgentRuntime 接口定义

```python
class AgentRuntime:
    """Manage the multi-round tool-use review loop."""

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        trace_manager: TraceManager,
        budget_manager: BudgetManager,
        config: AgentRuntimeConfig,
    ) -> None: ...

    def run(
        self,
        *,
        snapshot: ReviewSnapshot,
        existing_findings: list[Finding],
        trace: ReviewTrace,
        review_id: str,
    ) -> AgentRuntimeResult:
        """Execute the full multi-round review loop and return collected findings."""


class AgentRuntimeConfig(BaseModel):
    max_rounds: int = 2              # 外层循环最大轮次
    max_tool_rounds: int = 15        # 内层循环最大 tool-use 轮次
    max_empty_rounds: int = 3        # 连续空响应轮次上限
    prompt_token_ratio: float = 0.8  # prompt 占 max_tokens 的比例上限
    grace_round_enabled: bool = True # 是否启用 grace round


class AgentRuntimeResult(BaseModel):
    findings: list[Finding]
    rounds_executed: int
    tool_calls_total: int
    comments_submitted: int
    stop_reason: str  # "task_done" | "max_rounds" | "budget_exhausted" | "empty_rounds"
    budget_snapshot: BudgetSnapshot
```

### 3.5 外层循环：已确认评论注入机制

参考阿里的设计，第 2 轮（及以后）把上一轮收集的评论注入 prompt：

```
Round 1 prompt:
  system: 你是代码审查助手...
  user: 审查以下 diff...
  (无已确认评论)

Round 2 prompt:
  system: 你是代码审查助手...
  user: 审查以下 diff...
  + 以下是上一轮已发现的问题，请基于这些问题深入挖掘相关问题，不要重复：
    - [file:line] summary1
    - [file:line] summary2
```

**提前停止**：如果上一轮没有新评论（`len(new_findings) == 0`），外层循环提前结束。

### 3.6 内层循环：消息累积机制

每轮内层循环维护一个 messages 列表，遵循 OpenAI function calling 协议：

```
messages = [
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  # 模型第一次响应
  {"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "function": {"name": "read_file", "arguments": "..."}}]},
  # 工具结果
  {"role": "tool", "tool_call_id": "call_1", "content": "..."},
  # 模型第二次响应
  {"role": "assistant", "content": null, "tool_calls": [{"id": "call_2", "function": {"name": "code_comment", "arguments": "..."}}]},
  # 控制工具结果（runtime 生成的确认）
  {"role": "tool", "tool_call_id": "call_2", "content": "Comment submitted: id=cmt_001"},
  # ... 继续循环
]
```

### 3.7 Grace Round 机制

当预算耗尽时，不直接硬停，进入 grace round：
1. 工具白名单限制为只有 `code_comment` 和 `task_done`（分析工具全部禁用）
2. 给模型发系统消息："预算即将耗尽，请提交你已经发现的所有问题，然后调用 task_done 结束。"
3. 只允许再跑 1 轮内层循环
4. 这一轮收集的评论正常输出

---

## 4. 核心二：声明式工具详细设计

### 4.1 设计目标

参考 [toolregistry](https://toolregistry.readthedocs.io/) 的纯声明式理念，但自己实现轻量版（不引入第三方依赖）：

1. **工具定义就是函数本身**：用 `@tool` 装饰器标记，不需要写 Tool 类
2. **Schema 自动生成**：从函数的类型注解自动生成 JSON Schema，不需要手动写 input_schema
3. **上下文参数自动注入**：`snapshot` / `provider` 等运行时上下文参数不暴露给 LLM，由 runtime 自动注入
4. **返回值自动转为 ToolResult**：函数返回 dict，自动包装为 ToolResult，不需要手动构造
5. **向后兼容**：规则引擎的 `ToolExecutor.run_tool(name, payload, snapshot=..., provider=...)` 接口不变

### 4.2 当前 vs 声明式对比

#### 当前版本（read_file.py，~60 行）

```python
class ReadFileInput(BaseModel):
    file_path: str

class ReadFileTool:
    meta = ToolSpec(
        name="read_file",
        description="Read one changed file at the immutable head sha.",
        input_schema={
            "type": "object",
            "required": ["file_path"],
            "properties": {"file_path": {"type": "string"}},
        },
        output_schema={...},
        execution_policy="provider_read_only",
        max_output_chars=12000,
        failure_behavior="return_error_result",
    )

    def run(self, payload: BaseModel, *, snapshot: ReviewSnapshot, provider=None) -> ToolResult:
        request = ReadFileInput.model_validate(payload)
        if provider is None:
            raise ToolExecutionError("...")
        if snapshot.head_sha is None:
            raise ToolExecutionError("...")
        content = provider.get_file_content(snapshot.repo, request.file_path, snapshot.head_sha)
        truncated_content, truncated = _truncate_text(content, self.meta.max_output_chars)
        return ToolResult(
            tool_name=self.meta.name,
            payload={"file_path": request.file_path, "content": truncated_content},
            truncated=truncated,
        )
```

#### 声明式版本（read_file.py，~15 行）

```python
@tool(description="Read one changed file at the immutable head sha.", max_output_chars=12000)
def read_file(file_path: str, *, snapshot: Snapshot, provider: Provider) -> dict:
    """Read one changed file at the immutable head sha."""
    if provider is None:
        raise ToolExecutionError("read_file requires a provider-backed execution context.")
    if snapshot.head_sha is None:
        raise ToolExecutionError("read_file requires snapshot.head_sha to be populated.")
    content = provider.get_file_content(snapshot.repo, file_path, snapshot.head_sha)
    truncated, is_truncated = _truncate(content, 12000)
    return {"file_path": file_path, "content": truncated, "truncated": is_truncated}
```

**减少了 75% 的样板代码**，且 schema 从类型注解自动生成，不会和实际参数不一致。

### 4.3 装饰器设计

```python
# tools/declarative.py
from __future__ import annotations
from functools import wraps
from typing import get_type_hints, Annotated, get_origin, get_args
import inspect

from codereviewer.domain.models import ReviewSnapshot
from codereviewer.domain.interfaces.scm import SCMProvider


# 上下文参数标记：这些参数不暴露给 LLM，由 runtime 注入
class _ContextMarker:
    pass

# 类型别名，用于标记上下文参数
Snapshot = Annotated[ReviewSnapshot, _ContextMarker()]
Provider = Annotated[SCMProvider | None, _ContextMarker()]


def tool(
    description: str = "",
    *,
    name: str | None = None,
    max_output_chars: int = 12000,
    failure_behavior: str = "return_error_result",
):
    """Decorator to register a function as a declarative review tool.

    The function's type annotations are automatically converted to JSON Schema.
    Parameters annotated with Snapshot or Provider (context markers) are injected
    by the runtime and not exposed to the LLM.

    The function should return a dict (automatically wrapped as ToolResult.payload)
    or raise a CodeReviewerError (automatically wrapped as ToolResult.error).
    """
    def decorator(func):
        sig = inspect.signature(func)
        hints = get_type_hints(func, include_extras=True)

        # 分离 LLM 可见参数和上下文参数
        llm_params: dict[str, dict] = {}
        context_params: set[str] = set()
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            hint = hints.get(param_name, param.annotation)
            if _is_context_param(hint):
                context_params.add(param_name)
                continue
            llm_params[param_name] = _python_type_to_json_schema(param_name, hint)
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        # 生成 JSON Schema
        schema = {
            "type": "object",
            "properties": llm_params,
            "required": required,
        }

        @wraps(func)
        def wrapper(**kwargs):
            return func(**kwargs)

        wrapper._is_tool = True
        wrapper._tool_name = name or func.__name__
        wrapper._tool_description = description or func.__doc__ or ""
        wrapper._tool_schema = schema
        wrapper._context_params = context_params
        wrapper._max_output_chars = max_output_chars
        wrapper._failure_behavior = failure_behavior
        wrapper._original_func = func
        return wrapper
    return decorator


def _is_context_param(hint) -> bool:
    """Check if a type annotation is marked as a context parameter."""
    if get_origin(hint) is Annotated:
        args = get_args(hint)
        return any(isinstance(arg, _ContextMarker) for arg in args[1:])
    return False


def _python_type_to_json_schema(param_name: str, hint) -> dict:
    """Convert a Python type annotation to JSON Schema."""
    # 处理 Optional / Union
    if get_origin(hint) is not None:
        origin = get_origin(hint)
        args = get_args(hint)
        if origin is dict:
            return {"type": "object"}
        if origin is list:
            item_schema = _python_type_to_json_schema(f"{param_name}[]", args[0]) if args else {}
            return {"type": "array", "items": item_schema}
        # Optional[X] = Union[X, None]
        if origin is type(None):  # noqa: E721
            return {"type": "null"}

    # 基础类型
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
    }
    if hint in type_map:
        return type_map[hint]

    # 默认 string
    return {"type": "string"}
```

### 4.4 ToolRegistry 改造

```python
# tools/registry.py
class ToolRegistry:
    """Register and resolve declarative tools by stable name."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, tool_func: Callable) -> Callable:
        """Register a declarative tool function (decorated with @tool)."""
        name = tool_func._tool_name
        if name in self._tools:
            raise ToolRegistrationError(f"tool '{name}' is already registered.")
        self._tools[name] = tool_func
        self._schemas[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": tool_func._tool_description,
                "parameters": tool_func._tool_schema,
            },
        }
        return tool_func

    def get(self, name: str) -> Callable:
        tool_func = self._tools.get(name)
        if tool_func is None:
            raise ToolExecutionError(f"tool '{name}' is not registered.")
        return tool_func

    def get_schema(self, name: str) -> dict:
        return self._schemas[name]

    def get_all_schemas(self) -> list[dict]:
        """Return all tool schemas in OpenAI function-calling format."""
        return list(self._schemas.values())

    def execute(
        self,
        name: str,
        *,
        arguments: dict,
        context: "ToolExecutionContext",
    ) -> ToolResult:
        """Execute a tool with LLM-provided arguments and runtime context.

        Context parameters (snapshot, provider) are automatically injected
        based on the tool's _context_params set.
        """
        tool_func = self.get(name)
        call_kwargs = dict(arguments)
        for ctx_param in tool_func._context_params:
            call_kwargs[ctx_param] = getattr(context, ctx_param)
        try:
            result = tool_func(**call_kwargs)
            if not isinstance(result, dict):
                result = {"result": result}
            return ToolResult(tool_name=name, payload=result)
        except CodeReviewerError as exc:
            return ToolResult(tool_name=name, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive safety net
            return ToolResult(tool_name=name, error=f"Unexpected tool failure: {exc}")

    def list_tools(self) -> list[str]:
        return sorted(self._tools)
```

### 4.5 ToolExecutionContext

```python
# domain/models.py
class ToolExecutionContext(BaseModel):
    """Runtime context injected into tool functions (not exposed to LLM)."""
    snapshot: ReviewSnapshot
    provider: SCMProvider | None = None
```

### 4.6 内置工具改造（全部改为声明式）

| 工具 | 当前行数 | 声明式行数 | 减少 |
|---|---|---|---|
| read_file | ~63 行 | ~15 行 | 76% |
| read_diff | ~74 行 | ~20 行 | 73% |
| list_changed_files | ~40 行 | ~10 行 | 75% |
| find_references | ~97 行 | ~35 行 | 64% |
| **合计** | **~274 行** | **~80 行** | **71%** |

### 4.7 向后兼容：ToolEngine 适配

规则引擎当前用 `ToolExecutor.run_tool(name, payload, snapshot=..., provider=...)` 接口，需要保持兼容：

```python
# services/tool_engine.py
class ToolEngine(ToolExecutor):
    def run_tool(self, name, payload, *, snapshot, provider=None):
        # 把 Pydantic payload 或 dict 转成 arguments dict
        if isinstance(payload, BaseModel):
            arguments = payload.model_dump()
        else:
            arguments = dict(payload)
        context = ToolExecutionContext(snapshot=snapshot, provider=provider)
        result = self._registry.execute(name, arguments=arguments, context=context)
        self._trace_message(f"Tool {name} {'completed' if result.error is None else 'failed'}.")
        return result
```

这样规则引擎不需要任何改动，新的 AgentRuntime 可以直接用 `ToolRegistry.execute()` 新接口。

### 4.8 工具注册方式（自动发现为主）

**推荐方式：目录自动发现**（新增工具只需加一个文件，不需要改注册代码）：

```python
# tools/builtin/__init__.py
from codereviewer.tools.registry import ToolRegistry
from codereviewer.tools.auto_discover import discover_and_register

def build_builtin_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    # 扫描当前目录下所有 .py 文件，自动注册 @tool 装饰的函数
    discover_and_register(registry, package=__package__, directory=__path__[0])
    return registry
```

**新增工具的完整流程**：
1. 在 `tools/builtin/` 下新建 `my_tool.py`
2. 写一个 `@tool` 装饰的函数
3. 完成——自动发现会在下次启动时注册它，不需要改 `__init__.py`

**手动注册 fallback**（特殊场景，如需要控制注册顺序或条件注册）：

```python
def build_builtin_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    # 先自动发现
    discover_and_register(registry, package=__package__, directory=__path__[0])
    # 再手动注册特殊工具（覆盖或补充）
    if some_condition:
        from .special_tool import special_tool
        registry.register(special_tool)
    return registry
```

### 4.9 自动发现机制实现

```python
# tools/auto_discover.py
import importlib
import pkgutil
from pathlib import Path
from typing import Callable

from codereviewer.tools.registry import ToolRegistry


def discover_and_register(
    registry: ToolRegistry,
    *,
    package: str,
    directory: str,
) -> int:
    """Scan a directory for Python modules and register all @tool-decorated functions.

    Returns the number of tools registered.
    """
    registered = 0
    dir_path = Path(directory)

    for module_info in pkgutil.iter_modules([str(dir_path)]):
        if module_info.name.startswith("_"):
            continue  # 跳过 __init__.py 和私有模块

        module_name = f"{package}.{module_info.name}"
        module = importlib.import_module(module_name)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if _is_tool_function(attr):
                registry.register(attr)
                registered += 1

    return registered


def _is_tool_function(obj: Callable) -> bool:
    """Check if an object is a @tool-decorated function."""
    return callable(obj) and getattr(obj, "_is_tool", False)
```

**设计要点**：
- 用 `pkgutil.iter_modules` 扫描目录，不依赖文件系统遍历
- 跳过 `_` 开头的模块（`__init__.py`、私有模块）
- 用 `_is_tool` 属性标记识别装饰后的函数，不依赖命名约定
- 自动发现和手动注册可以共存（先自动后手动，手动可覆盖）
- 注册失败（重名等）抛出 `ToolRegistrationError`，启动时即发现问题

---

## 5. 配套能力设计

### 5.1 CommentLocator（评论定位校验）

```python
class CommentLocator:
    """Validate that finding locations point to valid added lines in the diff."""

    def __init__(self, snapshot: ReviewSnapshot) -> None:
        self._added_lines_by_file: dict[str, set[int]] = _extract_added_lines(snapshot)

    def validate(self, findings: list[Finding]) -> list[Finding]:
        """Validate all findings and return them with location_valid flags set.
        Invalid-location findings are NOT removed, but their confidence is downgraded to REFERENCE."""
```

**校验规则**：
- `file` 不在 `changed_files` → `location_valid=False`
- `line` 为 null → `location_valid=False`（文件级评论）
- `line` 不在新增行集合 → `location_valid=False`
- 校验不通过：设置 `location_valid=False`，置信度强制降级为 `REFERENCE`，evidence 追加 `location_check_failed` 记录
- **不删除**定位无效的评论，只降级

### 5.2 Trace 增强

扩展 `TraceEvent` 增加 `details: dict` 字段，记录：
- `agent_round_start`：round 编号、降级级别、已确认评论数量
- `agent_round_end`：round 编号、新评论数量、工具调用总数、停止原因
- `tool_call`：工具名、参数摘要、结果摘要、耗时、是否成功
- `comment_submitted`：评论临时 ID、file/line、summary、severity

完整 messages 和响应继续通过 `write_artifact` 存储为独立文件（redacted）。

### 5.3 LLM Adapter 扩展

在 `LLMProvider` Protocol 中新增 `chat_with_tools` 方法，支持 function calling：

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # JSON string

class ToolChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = []
    tool_call_id: str | None = None

class ToolChatRequest(BaseModel):
    messages: list[ToolChatMessage]
    tools: list[dict]
    tool_choice: str = "auto"
    max_tokens: int | None = None
    temperature: float = 0.0

class ToolChatResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    finish_reason: str
```

`OpenAICompatibleLLMProvider` 实现 `chat_with_tools`，请求体增加 `tools` 和 `tool_choice`，响应解析 `tool_calls`。

---

## 6. 领域模型变更

### 6.1 新增模型

```python
class AgentLoopState(BaseModel):
    """Mutable state of the Agent Runtime loop."""
    round: int = 0
    tool_round: int = 0
    consecutive_empty_rounds: int = 0
    in_grace_round: bool = False
    messages: list[ToolChatMessage] = []
    collected_findings: list[Finding] = []
    stop_reason: str | None = None

class ToolCallRecord(BaseModel):
    """Record of one tool call during the agent loop."""
    call_id: str
    tool_name: str
    arguments: dict
    result_summary: str
    success: bool
    duration_ms: float
    round: int

class ToolExecutionContext(BaseModel):
    """Runtime context injected into tool functions."""
    snapshot: ReviewSnapshot
    provider: SCMProvider | None = None
```

（ToolChatMessage / ToolChatRequest / ToolChatResponse / ToolCall 见 5.3 节）

### 6.2 扩展现有模型

```python
class Finding(BaseModel):
    # ... 现有字段 ...
    location_valid: bool = True       # CommentLocator 校验结果
    trace_refs: list[str] = []        # 关联的 trace artifact ID
    agent_round: int | None = None    # 产生于第几轮循环

class TraceEvent(BaseModel):
    stage: ReviewStage
    message: str
    timestamp: datetime
    details: dict = Field(default_factory=dict)  # 新增：结构化详情
```

---

## 7. 实施步骤与优先级

### P0：核心两件事（必须完成）

| 步骤 | 内容 | 预估工时 | 依赖 | 验收标准 |
|---|---|---|---|---|
| 1 | 实现声明式工具装饰器（`tools/declarative.py`） | 2h | 无 | `@tool` 装饰器可用，类型注解自动生成 JSON Schema |
| 2 | 改造 ToolRegistry 支持声明式工具 | 1.5h | 步骤 1 | register/get_schema/get_all_schemas/execute 方法可用 |
| 3 | 实现工具自动发现（`tools/auto_discover.py`） | 1h | 步骤 2 | 扫描目录自动注册 `@tool` 函数，新增工具不需改注册代码 |
| 4 | 改造 ToolEngine 向后兼容规则引擎 | 1h | 步骤 2 | 规则引擎不需要改动，现有测试通过 |
| 5 | 把 4 个内置工具全部改为声明式函数 | 2h | 步骤 1 | 每个工具从 ~60 行降到 ~20 行，功能不变 |
| 6 | 扩展 LLM adapter 支持 function calling | 2h | 无 | `chat_with_tools` 方法可用，能解析 tool_calls |
| 7 | 实现 AgentRuntime 核心循环（外层 + 内层） | 4h | 步骤 3, 6 | 模型能调工具、提交评论、task_done 结束 |
| 8 | 接入控制工具（code_comment / task_done） | 1h | 步骤 7 | 控制工具由 runtime 处理，评论被收集 |
| 9 | 接入分析工具（委托声明式 ToolRegistry） | 1h | 步骤 5, 7 | read_file/read_diff/find_references 可被模型调用 |
| 10 | 接入预算控制（per-round + grace round） | 2h | 步骤 7 | 超预算时 grace round 输出已发现评论 |
| 11 | 接入 trace 记录（工具调用 + 评论提交） | 1h | 步骤 7 | trace 里能看到工具调用链和评论产生过程 |
| 12 | 改造 review_runner 的 FINDINGS_GENERATED 阶段 | 1h | 步骤 7-11 | Pipeline 端到端跑通，使用 AgentRuntime |
| 13 | 测试 + 文档 | 2h | 全部 | 单元测试通过，README 更新 |

**P0 小计：约 22.5h（约 2.5 天）**

### P1：配套能力（建议完成）

| 步骤 | 内容 | 预估工时 | 依赖 |
|---|---|---|---|
| 14 | 实现 CommentLocator（评论定位校验） | 1.5h | 无 |
| 15 | 接入 FINDINGS_VERIFIED 阶段 | 0.5h | 步骤 14 |
| 16 | 规则引擎扩展（加 3-5 条规则，修 print 误报） | 1h | 无 |

**P1 小计：约 3h**

### 总计

- P0（核心两件事）：~22.5h
- P0 + P1（推荐）：~25.5h（约 3 天）

---

## 8. 非目标

明确不做，写进文档避免范围蔓延：

| 非目标 | 原因 | 可能的 v3 方向 |
|---|---|---|
| Review Filter（独立 LLM 调用过滤错误评论） | v2 核心是 Agent + 声明式工具，Review Filter 是质量优化 | v3 质量提升 |
| 文件分组 + 并发执行 | 复杂度高，v2 先做单文件串行 | v3 性能优化 |
| Plan 阶段（大变更先做审查计划） | 阿里的可选优化，非核心 | v3 大变更优化 |
| Context compression（多轮 prompt 压缩） | 需要复杂的摘要策略 | v3 长对话优化 |
| 跨文件评论重定位 | 阿里的高级功能 | v3 定位精度提升 |
| 多 Agent 编排 | 超出 code reviewer 范围 | 架构演进 |
| Web UI | 超出 CLI 工具范围 | 产品化 |
| 直接引入 toolregistry 第三方库 | 自己实现轻量版，控制完全在手里，不增加依赖 | 如需更多功能可考虑迁移 |

---

## 9. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|---|---|---|---|
| 类型注解转 JSON Schema 覆盖不全（复杂类型如 Union/Enum） | 中 | 中 | 先支持基础类型（str/int/float/bool/list/dict/Optional），复杂类型降级为 string；单元测试覆盖 |
| LLM 不遵守 tool-use 协议（不调工具、乱调工具） | 中 | 高 | system prompt 明确约束；空轮上限强制终止；task_done 兜底；grace round |
| 无限循环（模型反复调同一个工具） | 中 | 中 | max_tool_rounds 硬限制；连续相同工具调用检测 |
| token 爆炸（messages 累积过大） | 中 | 中 | prompt_token_ratio 检查；max_rounds 限制；分析工具结果截断 |
| function calling 兼容性（不同 provider 支持不同） | 低 | 高 | 只测试 OpenAI 兼容端点；不支持时降级为单次 prompt（v1 模式） |
| 声明式工具改造引入回归 | 中 | 中 | 保持 ToolEngine 向后兼容；现有工具测试全部通过；逐个工具迁移并验证 |
| 上下文参数注入错误（snapshot/provider 没注入或注入错） | 低 | 中 | 用 Annotated 标记明确区分；单元测试覆盖每个工具的上下文注入 |

---

## 10. 验收 Checklist

### P0 验收项（核心两件事）

**声明式工具（G2）：**
- [ ] `@tool` 装饰器可用，能从类型注解自动生成 JSON Schema
- [ ] 上下文参数（Snapshot/Provider）不暴露在 schema 中，由 runtime 自动注入
- [ ] ToolRegistry 支持 register/get_schema/get_all_schemas/execute 方法
- [ ] `discover_and_register()` 能扫描目录自动注册 `@tool` 装饰的函数
- [ ] 新增工具只需在 `tools/builtin/` 下加一个文件，不需要改 `__init__.py` 或注册代码
- [ ] 自动发现跳过 `_` 开头的模块（`__init__.py`、私有模块）
- [ ] 自动发现和手动注册可以共存（先自动后手动，手动可覆盖）
- [ ] 重名工具注册时抛出 `ToolRegistrationError`，启动时即发现问题
- [ ] ToolEngine 向后兼容规则引擎（现有测试全部通过）
- [ ] 4 个内置工具全部改为声明式函数，每个减少 >= 60% 代码行数
- [ ] 工具返回 dict 自动包装为 ToolResult，异常自动包装为 ToolResult.error
- [ ] 新增工具只需写一个函数 + `@tool` 装饰器，不需要写类，不需要改注册代码

**Agent Runtime（G1）：**
- [ ] `OpenAICompatibleLLMProvider.chat_with_tools` 方法可用，支持 tools 参数和 tool_calls 响应
- [ ] `AgentRuntime.run()` 能执行多轮 tool-use 循环
- [ ] 模型能调用 read_file/read_diff/find_references/list_changed_files
- [ ] 模型能通过 `code_comment` 工具提交评论，评论被收集到结果中
- [ ] 模型能通过 `task_done` 工具结束循环
- [ ] 外层循环默认 2 轮，第 2 轮注入第 1 轮已确认评论
- [ ] 外层循环在无新评论时提前停止
- [ ] 预算每轮前检查，超预算时进入 grace round（只允许 code_comment/task_done）
- [ ] grace round 能输出已发现的评论，不硬停
- [ ] Trace 记录每轮工具调用（工具名、参数摘要、结果摘要、耗时）和评论提交
- [ ] 每条评论的 evidence 包含产生它的工具调用和 LLM 响应引用
- [ ] `review_runner.py` 的 FINDINGS_GENERATED 阶段使用 AgentRuntime
- [ ] Pipeline 端到端跑通（输入 PR URL → 输出 findings.json + report.md）
- [ ] Resume 功能在新架构下仍然可用
- [ ] 所有现有单元测试通过
- [ ] 新增模块有单元测试

### P1 验收项（配套）

- [ ] `CommentLocator.validate()` 验证 file/line，无效定位被标记 location_valid=False 并降级为 REFERENCE
- [ ] CommentLocator 在 FINDINGS_VERIFIED 阶段生效
- [ ] 规则引擎有 >= 5 条规则
- [ ] `print(` 不在 Python 脚本/CLI 文件中误报

### 文档验收项

- [ ] README.md 包含快速开始、架构说明、配置项、示例
- [ ] ARCHITECTURE.md 更新为 v2 架构
- [ ] 声明式工具使用文档（如何新增一个工具）
- [ ] Agent Runtime 设计文档（循环流程、工具分类、预算控制）

---

## 附录 A：和阿里 OpenCodeReview 的对应关系

| 阿里概念 | v2 对应 | 说明 |
|---|---|---|
| Plan 阶段 | ❌ 不做 | 非目标（v3） |
| 外层多轮（maxRounds） | ✅ AgentRuntime 外层循环 | 默认 2 轮，注入已确认评论 |
| 内层 tool-use 循环 | ✅ AgentRuntime 内层循环 | 控制工具 + 分析工具分离 |
| code_comment / task_done | ✅ 控制工具 | runtime 内部处理 |
| read_file / read_diff / code_search | ✅ 分析工具 | 声明式 ToolRegistry |
| Review Filter | ❌ 不做 | 非目标（v3） |
| 文件分组 + 并发 | ❌ 不做 | 非目标（v3） |
| 四层预算控制 | ✅ 复用 BudgetManager + per-round + grace round | |
| 评论定位校验（三层） | ⚠️ 只做第一层 | 同文件 diff 行号校验，跨文件重定位不做 |
| 评论去重 | ✅ FindingAggregator（v1 已有） | |
| 置信度独立判定 | ✅ EvidenceValidator（v1 已有） | |
| 工具定义方式 | ⭐ 声明式（v2 新增） | 比阿里的手动 ToolDef 更简洁 |

## 附录 B：v1 → v2 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `tools/declarative.py` | 🆕 新增 | `@tool` 装饰器 + 类型注解转 JSON Schema |
| `tools/auto_discover.py` | 🆕 新增 | 扫描目录自动注册 `@tool` 装饰的函数 |
| `services/agent_runtime.py` | 🆕 新增 | Agent Runtime 核心 |
| `services/comment_locator.py` | 🆕 新增 | 评论定位校验（P1） |
| `tools/registry.py` | ✏️ 改动 | 支持声明式工具注册、schema 生成、执行 |
| `services/tool_engine.py` | ✏️ 改动 | 适配新接口，保持向后兼容 |
| `tools/builtin/read_file.py` | ✏️ 重写 | 改为声明式函数 |
| `tools/builtin/read_diff.py` | ✏️ 重写 | 改为声明式函数 |
| `tools/builtin/list_changed_files.py` | ✏️ 重写 | 改为声明式函数 |
| `tools/builtin/find_references.py` | ✏️ 重写 | 改为声明式函数 |
| `tools/builtin/__init__.py` | ✏️ 改动 | 新的注册方式 |
| `adapters/llm/openai_compatible.py` | ✏️ 改动 | 支持 function calling |
| `services/review_runner.py` | ✏️ 改动 | 阶段 5 接入 AgentRuntime，阶段 6 接入 CommentLocator |
| `domain/models.py` | ✏️ 改动 | 新增 AgentLoopState/ToolCallRecord/ToolExecutionContext/ToolChat* ，扩展 Finding/TraceEvent |
| `domain/interfaces/llm.py` | ✏️ 改动 | 新增 chat_with_tools 方法 |
| `services/trace_manager.py` | ✏️ 改动 | 支持 details 字段 |
| `services/rule_engine.py` | ✏️ 改动（P1） | 扩展规则，修 print 误报 |
| `README.md` | 🆕 新增 | 项目说明 |
| `docs/ARCHITECTURE.md` | ✏️ 改动 | 更新为 v2 架构 |

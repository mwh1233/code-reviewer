# Agent Runtime 设计说明

## 目标

`AgentRuntime` 负责阶段 5 的单 Agent 多轮 tool-use 审查，把原先的单次 prompt-response 改造成：

- 模型主动调用只读工具
- 模型用 `code_comment` 提交候选 finding
- 模型用 `task_done` 结束当前轮次

## 关键文件

- `src/codereviewer/services/agent_runtime.py`
- `src/codereviewer/adapters/llm/openai_compatible.py`
- `src/codereviewer/services/review_runner.py`

## 工具分类

控制工具：

- `code_comment`
- `task_done`

分析工具：

- `read_diff`
- `read_file`
- `list_changed_files`
- `find_references`

控制工具由 `AgentRuntime` 内部直接处理；分析工具委托给 `ToolRegistry`。

## 循环结构

### 外层循环

- 默认最多 2 轮
- 第 2 轮会注入上一轮已确认 finding 摘要
- 如果某一轮没有新增 finding，则提前结束

### 内层循环

- 默认最多 15 个 tool round
- 每轮向模型发送 `messages + tools`
- 如果模型返回 `tool_calls`，逐个执行并把结果作为 `tool` 消息追加回对话
- 如果模型连续空响应达到上限，则以 `empty_rounds` 结束

## 预算控制

- 每次 LLM 调用前通过 `BudgetManager.plan_llm_call()` 做预算门禁
- 每次调用后记录真实 token / cost 使用量
- 若预算已阻断但当前轮已有 finding，可进入一次 grace round

### Grace Round

- 只保留 `code_comment` 和 `task_done`
- 不再允许分析工具
- 目标是让模型保守收尾，而不是继续扩展分析

## 证据与定位

- `code_comment` 产出的 finding 会绑定 `agent_tool_call` 证据
- 阶段 6 再通过 `CommentLocator` 校验 `file/line` 是否映射到同文件 diff 新增行
- 定位无效不会删除 finding，但会降级为 `reference`

## 当前边界

- 仍是单 Agent，不做多 Agent 编排
- 不执行用户仓库代码
- 不暴露任意 shell
- 不做跨文件评论重定位
- 不做上下文压缩，只靠预算、轮次和空响应上限控制增长

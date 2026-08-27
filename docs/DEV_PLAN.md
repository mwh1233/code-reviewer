# Code Review Agent DEV PLAN

## 1. 文档目的

本文档定义 Code Review Agent 第一版的开发计划，用于指导实现顺序、范围控制、验收标准和验证优先级。

本文档重点把 `SPEC.md` 和 `ARCHITECTURE.md` 拆解为可执行、可验证的垂直切片。

每个开发阶段都必须满足：

- 一次只解决一个清晰问题
- 能独立形成可验证产物
- 与 `ARCHITECTURE.md` 的 Pipeline 阶段保持映射关系
- 包含明确的验收标准和测试重点
- 明确列出本阶段不做什么，防止范围扩大

## 2. 开发总原则

### 2.1 先抽象共性，再落具体 Provider

第一版必须支持 GitHub 和 GitLab，因此先做 provider-neutral 抽象，再分别接入两个 SCM Provider。

### 2.2 先建立系统骨干，再补智能能力

优先级顺序：

1. 工程脚手架
2. 输入 / 快照抽象
3. GitHub / GitLab Provider
4. 状态机 / Checkpoint / Trace
5. 工具和规则
6. LLM + 基础预算
7. 证据、输出、发布、预算收尾

### 2.3 每个阶段必须可验证

每一刀完成后，必须至少回答：

- 做成了什么
- 哪些行为现在可观察
- 哪些失败场景已覆盖
- 用什么测试或检查验证过

### 2.4 严格范围控制

第一版开发过程中，以下能力始终不进入当前交付：

- 自动修改代码
- 自动 Merge
- Web UI
- 多 Agent 编排
- 执行用户仓库代码
- 多 Provider 并行路由

## 3. 里程碑总览

第一版按 8 个里程碑推进：

- `M0`：项目初始化脚手架
- `M1`：Provider-neutral 输入抽象 + Snapshot 骨架
- `M2`：GitHub Provider
- `M3`：GitLab Provider
- `M4`：Pipeline 状态机 + Checkpoint / Trace 基础能力
- `M5`：只读工具注册机制 + 规则检查链路
- `M6`：LLM 审查链路 + 基础预算控制
- `M7`：Evidence 校验 + 多输出通道 + 精细预算 + 收尾验证

## 4. 里程碑详细计划

### M0：项目初始化脚手架

**目标**

搭建最小可运行工程骨架，为后续所有实现提供稳定起点。

**对应架构阶段**

- 全局准备阶段

**范围**

- 初始化目录结构
- 建立基础配置入口
- 建立 CLI 空入口
- 建立空的 Pipeline 骨架
- 建立核心领域模型空壳
- 建立最小 artifacts 落盘规则

**验收标准**

- 项目可以通过统一入口启动
- 空 Pipeline 能正常执行到结束
- 能生成最小 review artifact 骨架或占位输出
- 核心目录结构与 `ARCHITECTURE.md` 一致

**测试重点**

- CLI 启动
- 配置加载
- 空流程 smoke test

**本阶段不做**

- 真实 GitHub / GitLab 调用
- 真实 Snapshot 生成
- Trace / Checkpoint 逻辑
- 工具 / 规则 / LLM

### M1：Provider-neutral 输入抽象 + Snapshot 骨架

**目标**

先建立不依赖具体 GitHub / GitLab 实现的统一输入和快照抽象。

**对应架构阶段**

- `input_validated`
- `snapshot_created`

**范围**

- 定义 `ReviewRequest`
- 定义 `ReviewSnapshot`
- 支持统一输入形态：
  - review URL
  - `repo + base_branch + head_branch`
- 定义 `SCMProvider` 接口和 `resolve_snapshot_target` 抽象
- 建立 Snapshot 构建骨架

**验收标准**

- 系统能接收 provider-neutral 输入并转成统一请求结构
- Snapshot 骨架可被构造
- 不同输入模式都能归一到统一快照来源定义

**测试重点**

- URL 输入归一化
- 分支比较输入归一化
- 无效输入拒绝

**本阶段不做**

- GitHub / GitLab 真实 API 访问
- 恢复逻辑
- 工具 / 规则 / LLM

### M2：GitHub Provider

**目标**

先打通 GitHub PR 全链路输入与快照获取。

**对应架构阶段**

- `input_validated`
- `snapshot_created`

**范围**

- 实现 `GitHubProvider`
- 支持 GitHub PR URL
- 支持 GitHub 分支比较模式
- 拉取 PR 元数据、Diff、Base / Head SHA
- 生成 GitHub `ReviewSnapshot`

**验收标准**

- 有效 GitHub PR URL 可生成不可变快照
- 有效 GitHub `repo + base_branch + head_branch` 可生成不可变快照
- `headSha` 被正确绑定

**测试重点**

- PR URL 解析
- GitHub 分支比较
- GitHub API 失败场景
- `headSha` 获取与绑定

**本阶段不做**

- GitLab
- Checkpoint / Trace 恢复
- 工具 / 规则 / LLM

### M3：GitLab Provider

**目标**

补齐 GitLab MR 输入与快照获取，满足题面 provider 覆盖要求。

**对应架构阶段**

- `input_validated`
- `snapshot_created`

**范围**

- 实现 `GitLabProvider`
- 支持 GitLab MR URL
- 支持 GitLab 分支比较模式
- 拉取 MR 元数据、Diff、Base / Head SHA
- 生成 GitLab `ReviewSnapshot`

**验收标准**

- 有效 GitLab MR URL 可生成不可变快照
- 有效 GitLab `repo + base_branch + head_branch` 可生成不可变快照
- GitHub / GitLab 两类 provider 均可通过统一接口接入

**测试重点**

- MR URL 解析
- GitLab 分支比较
- GitLab API 失败场景
- 双 provider 接口一致性

**本阶段不做**

- Checkpoint / Trace 恢复
- 工具 / 规则 / LLM

### M4：Pipeline 状态机 + Checkpoint / Trace 基础能力

**目标**

把主流程状态机、Trace 和 Checkpoint 绑定起来，建立系统骨干。

**对应架构阶段**

- `input_validated`
- `snapshot_created`
- `analysis_prepared`
- `deterministic_checks_done`
- `findings_generated`
- `findings_verified`
- `outputs_prepared`
- `publish_attempted`
- `completed`
- `failed`

**范围**

- 定义 `ReviewStage`
- 建立 Pipeline 状态流转
- 在稳定阶段结束后写入 Checkpoint
- 建立基础 Trace 事件模型
- 建立脱敏原始工件引用机制骨架
- 支持从已有 Checkpoint 恢复到下一步

**验收标准**

- 主流程阶段可以按顺序推进
- 每个稳定阶段结束后可落 Checkpoint
- Trace 中可看到关键阶段事件
- 可以从 Checkpoint 恢复到下一阶段

**测试重点**

- 阶段切换顺序
- Checkpoint 落点
- 恢复逻辑
- 失败阶段记录

**本阶段不做**

- 真正的只读工具能力
- 真正的规则检查
- 真正的 LLM 调用
- 精细预算降级策略

### M5：只读工具注册机制 + 规则检查链路

**目标**

建立显式工具注册机制，并在不依赖 LLM 的前提下产出第一批结构化 Findings。

**对应架构阶段**

- `analysis_prepared`
- `deterministic_checks_done`

**范围**

- 建立工具注册表
- 接入基础只读工具：
  - `read_diff`
  - `read_file`
  - `list_changed_files`
  - `find_references`
- 建立规则注册与执行机制
- 为规则型 Findings 绑定基础证据

**验收标准**

- 工具必须先注册后调用
- 工具返回结构化有界结果
- 不依赖 LLM 即可产出结构化候选 Findings
- 每条规则型候选 Finding 至少关联一条证据

**测试重点**

- 重复注册
- 工具成功 / 失败路径
- 工具输出截断
- 规则命中 / 无命中
- 证据绑定

**本阶段不做**

- 执行型工具
- `run_typecheck`
- `run_tests`
- LLM 审查
- Provider 评论发布

### M6：LLM 审查链路 + 基础预算控制

**目标**

建立 LLM 语义审查链路，并把预算控制作为模型调用门禁接入主流程。

**对应架构阶段**

- `findings_generated`

**范围**

- Prompt 组装
- 安全脱敏后发送模型
- 结构化解析 LLM 输出
- 模型调用前 Token / 成本预算检查
- 模型调用后 Token / 成本记录
- 超预算时停止执行

**验收标准**

- LLM 输出可以被解析为结构化候选 Findings
- Token 与成本使用会被记录到预算状态
- 超预算时模型调用被阻止
- Checkpoint 中能看到预算状态

**测试重点**

- 模型输出解析成功 / 失败
- 脱敏是否生效
- Token 计数是否记录
- 成本记录是否写入
- 超预算停止路径

**本阶段不做**

- 精细分段降级策略
- 最终输出发布

### M7：Evidence 校验 + 多输出通道 + 精细预算 + 收尾验证

**目标**

收敛最终 Findings，补齐 Markdown / JSON / Provider 评论输出，完成预算、恢复和发布前校验收尾。

**对应架构阶段**

- `findings_verified`
- `outputs_prepared`
- `publish_attempted`

**范围**

- 证据校验
- Finding 去重与聚合
- 置信度收敛
- Markdown 报告输出
- `findings.json` 输出
- GitHub / GitLab 评论载荷构造与发布
- 发布前 `headSha` 校验
- 精细预算策略：
  - 0%-60% 正常
  - 60%-85% 降级
  - 85%-100% 仅必要分析
  - 100% 停止
- 收尾集成验证

**验收标准**

- 最终 Findings 全部符合结构化契约
- 每条正式 Finding 至少包含一条证据
- Markdown 和 `findings.json` 都能成功落盘
- GitHub / GitLab 评论发布能力可用
- 发布前会重新校验 `headSha`
- 预算达到不同阈值时行为符合预期

**测试重点**

- 无证据结论过滤
- `high` / `reference` 置信度判断
- Markdown / JSON 输出正确性
- 评论发布成功 / 失败 / 跳过路径
- `headSha` 变化拒绝发布
- 60% / 85% / 100% 阈值行为

**本阶段不做**

- 自动 Merge
- 多 Agent
- 用户仓库代码执行

## 5. 验证顺序

每个里程碑完成后，都应优先执行与改动范围最匹配的最小验证：

1. 聚焦单元测试或集成测试
2. 变更范围测试
3. 类型检查和 Lint
4. 必要时执行更高层验证

## 6. 推荐实施顺序

推荐严格按以下顺序推进：

1. `M0`
2. `M1`
3. `M2`
4. `M3`
5. `M4`
6. `M5`
7. `M6`
8. `M7`

原因如下：

- `M0` 提供基础运行骨架
- `M1` 先收敛 provider-neutral 输入与快照抽象
- `M2` 和 `M3` 分别补齐 GitHub 与 GitLab
- `M4` 建立恢复和 trace 骨干
- `M5` 先不依赖 LLM 产出 Findings
- `M6` 接入 LLM 与基础预算门禁
- `M7` 完成输出发布、预算精细化和最终收尾

## 7. 里程碑完成定义

每个里程碑只有在同时满足以下条件时才算完成：

- 范围内代码已实现
- 验收标准全部满足
- 已执行与本阶段匹配的验证
- Diff 已自查
- 已明确记录剩余风险和未覆盖项

## 8. 第二阶段边界

当且仅当 `M0` 到 `M7` 全部完成并验证通过后，才进入第二阶段开发。第二阶段以 `docs/SPEC2.md` 为准，核心只聚焦两件事：

- 单 Agent `AgentRuntime` 多轮 tool-use 审查闭环
- 完全声明式工具注册与执行

第二阶段明确不做以下能力，避免范围蔓延：

- 多 Agent 编排
- 多 Provider 并行路由
- 受控沙箱中的 `run_typecheck` / `run_tests`
- Web UI
- 用户仓库代码执行

## 9. 第二阶段开发计划

### 9.1 第二阶段目标

第二阶段不是重做 MVP，而是在保留 8 阶段 Pipeline、Checkpoint、Trace、Budget 和 Security 主骨架不变的前提下，增强以下能力：

- 让 LLM 审查从单次 prompt-response 演进为多轮 tool-use
- 让工具从 class-based 样板代码演进为声明式定义
- 在阶段 5 和阶段 6 提升 findings 质量、定位有效性和可追溯性

### 9.2 第二阶段里程碑总览

- `P2-M1`：声明式工具基础设施
- `P2-M2`：内置只读工具迁移
- `P2-M3`：LLM function-calling 适配
- `P2-M4`：AgentRuntime 接入
- `P2-M5`：定位校验、阶段集成与回归收尾

### P2-M1：声明式工具基础设施

**目标**

建立 `@tool` 装饰器、schema 自动生成和新的 ToolRegistry 执行模型，为后续工具迁移和 AgentRuntime 做底层支撑。

**对应架构阶段**

- `deterministic_checks_done`
- `findings_generated`

**范围**

- 新增声明式工具装饰器
- 新增受控目录内的工具自动发现与注册
- 改造 `ToolRegistry` 支持函数式注册、schema 获取和上下文注入
- 保持 `ToolEngine` 对规则链路的向后兼容
- 新增 `ToolExecutionContext` 等基础领域模型

**验收标准**

- 新工具可通过一个函数加 `@tool` 完成定义
- 工具输入 schema 可由类型注解自动生成
- `discover_and_register` 可扫描受控目录并自动注册声明式工具
- 运行时上下文参数不会暴露给 LLM
- 现有规则引擎调用工具的接口不需要大改

**测试重点**

- schema 自动生成
- 自动发现跳过私有模块
- 重复注册拒绝
- 上下文注入正确性
- 工具异常到 `ToolResult` 的映射

**本阶段不做**

- 内置工具全面迁移
- LLM function calling
- AgentRuntime 主循环

### P2-M2：内置只读工具迁移

**目标**

把当前内置只读工具迁移到声明式注册体系，验证新工具机制能支撑规则链路和后续 LLM 链路。

**对应架构阶段**

- `analysis_prepared`
- `deterministic_checks_done`

**范围**

- 迁移 `read_file`
- 迁移 `read_diff`
- 迁移 `list_changed_files`
- 迁移 `find_references`
- 更新内置工具注册入口和 bounded output 策略

**验收标准**

- 4 个内置工具均通过声明式方式注册
- 内置工具注册入口不再依赖旧的 `*Tool` 类显式注册
- 工具输出仍然受长度和失败行为约束
- 规则链路在不依赖 LLM 的前提下继续可用
- 工具迁移后不引入任意执行能力

**测试重点**

- 每个工具的成功路径
- 不存在文件或无效参数时的失败路径
- 输出截断与 trace 摘要
- 规则链路回归

**本阶段不做**

- 新增高风险工具
- 全仓库扫描
- AgentRuntime 接入

### P2-M3：LLM function-calling 适配

**目标**

让 LLM Provider 支持 `tools` / `tool_calls` 协议，为单 Agent 多轮 tool-use 打通协议层。

**对应架构阶段**

- `findings_generated`

**范围**

- 扩展 `LLMProvider` 接口
- 扩展 OpenAI-compatible adapter 支持 function calling
- 新增 `ToolChatMessage`、`ToolCall`、`ToolChatRequest`、`ToolChatResponse`
- 处理无效 tool call、参数解析失败和 provider 不支持场景

**验收标准**

- Provider 可接收工具 schema 并解析 tool calls
- 工具调用输入输出可进入 trace
- provider 不支持时有明确降级或失败结果
- 预算记录继续覆盖工具化 LLM 调用

**测试重点**

- tool call 解析
- 非法 JSON 参数
- provider 响应无 tool call 的路径
- token 与成本记录回归

**本阶段不做**

- 复杂 prompt 压缩
- Review Filter
- 多 provider 路由

### P2-M4：AgentRuntime 接入

**目标**

在阶段 5 引入单 Agent 多轮 tool-use runtime，让模型能够主动读 diff、读文件、查引用、提交评论并结束循环。

**对应架构阶段**

- `findings_generated`

**范围**

- 新增 `services/agent_runtime.py`
- 定义控制工具 `code_comment` 和 `task_done`
- 实现外层多轮和内层 tool-use 循环
- 接入预算决策、grace round 和 trace 记录
- 在 review runner 的阶段 5 接入 AgentRuntime

**验收标准**

- 模型能够调用只读分析工具
- 模型能够通过 `code_comment` 产出候选 findings
- 模型能够通过 `task_done` 正常结束
- 每条候选 finding 都能关联产生它的工具调用或 LLM 响应引用
- 超预算时进入 grace round 而不是直接硬停
- run / resume 在新链路下仍然成立

**测试重点**

- 多轮消息累积
- 控制工具与分析工具分流
- finding 与 trace/evidence 关联
- 空响应终止
- 预算耗尽与 grace round
- resume 跳过已完成阶段

**本阶段不做**

- 多 Agent 编排
- 自动发布公开评论
- 用户仓库代码执行

### P2-M5：定位校验、阶段集成与回归收尾

**目标**

补齐阶段 6 的评论定位校验，并完成 Phase 2 全链路回归、文档收口与验收。

**对应架构阶段**

- `findings_generated`
- `findings_verified`
- `outputs_prepared`

**范围**

- 新增 `CommentLocator`
- 在阶段 6 接入定位有效性校验
- 将无效定位 findings 降级为 `reference`
- 扩展规则引擎覆盖并修正 `print(` 在 Python 脚本 / CLI 文件中的误报
- 校准 trace、checkpoint、report 输出与新字段
- 执行回归测试并更新相关文档
- 补齐 README、声明式工具使用说明和 Agent Runtime 设计说明

**验收标准**

- 无效 `file/line` 定位不会作为高置信度结果直接输出
- Phase 2 新增字段可落入 trace / checkpoint / outputs
- 规则引擎覆盖不少于 5 条规则，且 `print(` 误报得到修正
- 端到端 run / resume 可生成 `findings.json` 和 `report.md`
- README、声明式工具说明、Agent Runtime 设计说明与执行清单同步完成

**测试重点**

- 定位校验成功与失败路径
- findings 置信度降级
- `print(` 误报回归
- 输出层对新增字段的兼容
- 全链路回归

**本阶段不做**

- 跨文件评论重定位
- 文件分组并发执行
- Web UI

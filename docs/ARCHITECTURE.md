# Code Review Agent 架构设计

## 1. 文档目的

本文档定义 Code Review Agent 第一版的系统架构，用于约束模块职责、领域模型、目录结构、核心接口与执行 Pipeline。

本文档必须服务于以下目标：

- 支撑 `SPEC.md` 中确认的 MVP 范围与契约
- 保证系统可恢复、可追踪、有预算约束且安全
- 为后续实现提供稳定接口边界
- 为第二阶段扩展预留位置，但不提前引入不必要复杂度

## 2. 架构设计原则

### 2.1 贴题优先

第一版必须严格覆盖题面核心要求：

- GitHub PR 支持
- GitLab MR 支持
- 链接输入与 `repo + base_branch + head_branch` 输入
- Markdown 报告输出
- Provider 评论发布能力
- Checkpoint / 恢复
- 共享预算
- 可观测 Trace
- 显式工具注册

### 2.2 单主 Agent 优先

第一版只实现单主 Agent 的最小可靠闭环，不引入多 Agent 编排。

### 2.3 稳定接口优先于具体实现

`orchestrator` 只能依赖稳定接口，不能直接依赖具体 Provider SDK、具体工具实现或具体存储实现。

### 2.4 横切能力统一收口

以下能力必须通过统一模块接入：

- Token / 成本预算控制
- Checkpoint 持久化
- Trace 记录
- Secret 脱敏
- 输出前校验
- 发布前 `headSha` 校验

### 2.5 默认不信任输入

仓库内容、Diff、Issue 描述、评论和工具输出都视为不可信输入。任何进入模型、Trace 或持久化层的内容都必须经过安全处理和大小控制。

## 3. 整体分层架构

系统采用分层加编排的架构。核心思路是由 `orchestrator` 驱动主流程，其他模块通过接口提供能力。

### 3.1 分层视图

| 层级 | 职责 | 核心模块 |
|---|---|---|
| 接入层 | 输入解析、触发执行、参数校验 | CLI 入口、请求校验器 |
| 编排层 | 流程状态机、阶段调度、预算控制、Checkpoint 管理 | Pipeline 编排器、预算管理器、Checkpoint 管理器 |
| 能力层 | Provider 访问、快照、工具、规则、LLM、证据、安全、输出 | SCM 适配器、快照构建、工具引擎、规则引擎、LLM 引擎、证据验证、评论发布器 |
| 持久化层 | 状态与工件持久化 | Checkpoint 存储、Trace 存储、Artifact 存储 |
| 领域模型层 | 核心实体定义，跨全层共享 | 领域模型、枚举、接口契约 |

### 3.2 模块列表

- `providers`：GitHub / GitLab 访问适配与输入解析
- `snapshot`：构建不可变 Review 快照
- `orchestrator`：驱动 Review 状态机与阶段流转
- `llm`：封装模型调用、Prompt 组装和结构化输出解析
- `tools`：显式注册的只读工具能力
- `rules`：确定性规则检查能力
- `evidence`：证据引用、Finding 校验和置信度确认
- `budget`：共享 Token / 成本预算控制与降级策略
- `checkpoint`：阶段性持久化与恢复
- `trace`：工具、模型和关键动作的追踪记录
- `security`：Secret 脱敏、输入清洗和执行策略门禁
- `output`：渲染 Markdown、写出 JSON、发布 Provider 评论

## 4. 核心 Pipeline 阶段

一次完整 Review 划分为 8 个稳定执行阶段和 2 个终态。稳定执行阶段是恢复的最小单元，每个稳定阶段结束后都必须保存 Checkpoint。

### 阶段1：输入解析与校验

- 输入：GitHub PR URL / GitLab MR URL / `repo + base_branch + head_branch`
- 输出：结构化 `ReviewRequest`
- 职责：统一输入格式、参数完整性校验、生成唯一 Review ID
- Checkpoint：`input_validated`

### 阶段2：快照生成

- 输入：`ReviewRequest`
- 输出：不可变 `ReviewSnapshot`
- 职责：调用 SCM Provider 拉取元数据、Base/Head SHA、完整 Diff；生成不可变审查快照
- Checkpoint：`snapshot_created`

### 阶段3：Diff 预处理与安全扫描

- 输入：`ReviewSnapshot`
- 输出：结构化 `DiffChunk` 列表
- 职责：过滤二进制/超大文件、Diff 分片、语言识别、路径归类；执行敏感信息初筛
- Checkpoint：`analysis_prepared`

### 阶段4：确定性规则检查

- 输入：`DiffChunk` 列表和只读工具结果
- 输出：规则型候选 `Finding` 列表
- 职责：执行无需 LLM 的确定性规则检查
- Checkpoint：`deterministic_checks_done`

### 阶段5：LLM 语义审查

- 输入：脱敏后的 `DiffChunk` 列表
- 输出：LLM 型候选 `Finding` 列表
- 前置：预算校验 + 安全脱敏
- 职责：调用 LLM Provider 执行语义级代码审查，解析为结构化 Finding
- Checkpoint：`findings_generated`

### 阶段6：结果聚合与证据验证

- 输入：规则型 + LLM 型候选 Findings
- 输出：最终结构化 `Finding` 列表
- 职责：去重、合并、关联证据链、校准置信度、过滤无证据结论
- Checkpoint：`findings_verified`

### 阶段7：输出准备

- 输入：最终 Findings + Review 元数据
- 输出：Markdown 报告、`findings.json`、待发布评论载荷
- 职责：渲染本地工件，构造 Provider 评论发布载荷
- Checkpoint：`outputs_prepared`

### 阶段8：结果发布

- 输入：待发布评论载荷
- 输出：发布结果或跳过结果
- 职责：在显式启用且通过发布前校验后，发布 GitHub / GitLab 评论
- Checkpoint：`publish_attempted`

### 终态

- `completed`：正常完成
- `failed`：明确失败，记录失败阶段、已保留 Findings、是否可恢复

## 5. 领域模型

所有核心实体为全层共享的结构化契约，字段定义与 `SPEC.md` 对齐。

### 5.1 核心实体

#### ReviewRequest

- `provider`
- `repo`
- `review_url` 可选
- `change_number` 可选
- `base_branch` 可选
- `head_branch` 可选
- `requested_at`

#### ReviewSnapshot

- `review_id`
- `provider`
- `repo`
- `base_sha`
- `head_sha`
- `input_hash`
- `review_metadata`
- `changed_files`
- `diff_text`
- `created_at`

#### DiffChunk

- `file_path`
- `start_line`
- `end_line`
- `content`
- `language`

#### ReviewContext

- `snapshot`
- `budget_state`
- `trace_id`
- `current_stage`
- `collected_findings`
- `next_action`
- `output_targets`

#### Finding

- `id`
- `summary`
- `severity`
- `confidence`
- `file`
- `line`
- `explanation`
- `evidence`
- `suggested_fix` 可选
- `trace_id`
- `source_type`

#### EvidenceRef

- `source_type`
- `source_id`
- `file`
- `line_range`
- `excerpt`
- `verified`

#### BudgetState

- `budget_limit_tokens`
- `budget_limit_cost`
- `estimated_tokens_used`
- `actual_tokens_used`
- `estimated_cost_used`
- `actual_cost_used`
- `phase`
- `degrade_level`
- `stop_reason` 可选

#### ReviewCheckpoint

- `review_id`
- `provider`
- `input_hash`
- `repo`
- `base_sha`
- `head_sha`
- `completed_stages`
- `findings`
- `trace_id`
- `budget_state`
- `next_action`
- `updated_at`
- `terminal_status`

#### TraceArtifactRef

- `artifact_type`
- `artifact_id`
- `storage_ref`
- `redacted`

#### ReviewTrace

- `trace_id`
- `review_id`
- `events`
- `artifact_refs`
- `created_at`
- `updated_at`

#### ToolSpec

- `name`
- `description`
- `input_schema`
- `output_schema`
- `execution_policy`
- `max_output_size`
- `failure_behavior`

#### ToolResult

- `tool_name`
- `payload`
- `truncated`
- `error` 可选

#### RuleSpec

- `name`
- `description`
- `input_scope`
- `output_schema`
- `default_confidence`
- `failure_behavior`

#### CommentPayload

- `provider`
- `review_id`
- `target_id`
- `comments`
- `head_sha`

### 5.2 核心枚举

- `Severity`：critical / high / medium / low
- `Confidence`：high / reference
- `ReviewStage`：对应 Pipeline 8 个稳定阶段 + `completed` / `failed`
- `FindingSource`：rule / llm / hybrid
- `OutputTarget`：markdown / findings_json / provider_comments

## 6. 模块职责与依赖规则

### 6.1 providers（SCM 适配器层）

**职责：**

- 解析 GitHub PR URL、GitLab MR URL、`repo + base_branch + head_branch`
- 调用 GitHub / GitLab API 获取元数据、变更文件列表、Diff 和 Commit 信息
- 将外部输入转换为内部统一输入对象

**不负责：**

- Review 流程编排
- Token / 成本预算控制
- Finding 生成
- 报告渲染

**实现要求：**

- `GitHubProvider`
- `GitLabProvider`

### 6.2 snapshot（快照管理器）

**职责：**

- 基于 Provider 返回结果生成不可变 `ReviewSnapshot`
- 固化 `base_sha`、`head_sha`、仓库标识、输入摘要和 Diff 内容
- 为后续 Checkpoint、Trace 和输出提供稳定引用对象

### 6.3 orchestrator（Pipeline 编排器）

**职责：**

- 驱动 Review 生命周期
- 控制状态机阶段流转
- 在关键节点调用 `budget`、`trace`、`checkpoint`、`tools`、`rules`、`llm`、`evidence` 和 `output`
- 统一处理成功、失败、中断和恢复

**依赖规则：**

- 只能依赖稳定接口
- 不得直接依赖具体 Provider SDK 或具体文件路径

### 6.4 llm（LLM 引擎）

**职责：**

- 组装发送给模型的安全输入
- 调用单一 LLM Provider 的兼容接口
- 解析模型输出为结构化候选 Findings
- 记录 Token 与成本使用量

### 6.5 tools（工具引擎与注册中心）

**职责：**

- 通过显式注册表暴露受控工具能力
- 提供只读分析所需能力，如 `read_diff`、`read_file`、`list_changed_files`、`find_references`
- 统一工具输入输出结构、Trace 记录和失败行为

**约束：**

- 工具必须注册后才能被编排层调用
- 工具能力白名单制，禁止动态生成任意执行命令

### 6.6 rules（确定性规则检查器）

**职责：**

- 基于快照、DiffChunk 和只读工具结果执行确定性规则检查
- 产出规则型候选 Findings
- 为每条规则型 Finding 绑定可追溯证据

### 6.7 evidence（证据验证模块）

**职责：**

- 校验候选 Finding 是否拥有足够证据
- 生成 `EvidenceRef`
- 判定 `confidence` 为 `high` 或 `reference`
- 过滤无法定位或无法证明的结论

### 6.8 budget（预算管理器）

**职责：**

- 维护单次 Review 共享预算
- 记录模型调用的预计与实际 Token / 成本消耗
- 执行阈值判断和模型降级策略

### 6.9 checkpoint（Checkpoint 管理器）

**职责：**

- 在稳定阶段后保存 Checkpoint
- 恢复执行上下文、预算状态和下一步动作
- 校验输入哈希、仓库标识和 `head_sha`

### 6.10 trace（Trace 管理器）

**职责：**

- 记录关键执行事件
- 记录工具调用和模型调用摘要
- 为 Prompt、发送内容、模型回复、输出载荷建立脱敏原始工件引用
- 建立 Finding 与输入证据、工具、Prompt 的关联关系

### 6.11 security（安全模块）

**职责：**

- 执行 Secret 检测与脱敏
- 控制发送给模型的内容范围和大小
- 执行“不运行用户仓库代码”的策略门禁
- 在发布前再次进行安全检查

### 6.12 output（输出模块）

**职责：**

- 渲染 Markdown 报告
- 写出 `findings.json`
- 构造并发布 GitHub / GitLab 评论
- 记录发布结果或跳过原因

**约束：**

- 输出前必须经过安全检查
- Provider 评论发布前必须重新校验 `headSha`
- 是否真正发布由显式配置与人工批准控制

## 7. 核心扩展接口

### 7.1 SCMProvider 接口

```text
interface SCMProvider:
    def parse_input(request: ReviewRequest) -> NormalizedRequest
    def resolve_snapshot_target(request: NormalizedRequest) -> SnapshotSource
    def get_change_metadata(source: SnapshotSource) -> ReviewMeta
    def get_diff(source: SnapshotSource) -> RawDiff
    def get_file_content(repo, path, sha) -> str
    def get_commit_sha(repo, branch) -> str
    def publish_comments(payload: CommentPayload) -> PublishResult
```

### 7.2 ReviewTool 接口

```text
interface ReviewTool:
    meta: ToolSpec
    def run(input_payload) -> ToolResult
```

### 7.3 ReviewRule 接口

```text
interface ReviewRule:
    meta: RuleSpec
    def evaluate(context: ReviewContext, tool_results) -> list[Finding]
```

### 7.4 LLMProvider 接口

```text
interface LLMProvider:
    def chat(messages, config) -> LLMResponse
    def count_tokens(text) -> int
    def estimate_cost(token_count, model) -> float
```

### 7.5 Store 接口

```text
interface CheckpointStore:
    def save(checkpoint: ReviewCheckpoint)
    def load(review_id) -> ReviewCheckpoint | None

interface TraceStore:
    def save(trace: ReviewTrace)
    def load(trace_id) -> ReviewTrace | None

interface ArtifactStore:
    def write_report(review_id, content: str)
    def write_findings(review_id, findings: list[Finding])
    def write_trace_artifact(trace_id, artifact) -> TraceArtifactRef
```

## 8. 完整数据流

```text
CLI输入
  → Input Resolver → ReviewRequest [Checkpoint: input_validated]
  → SCM Provider → ReviewSnapshot [Checkpoint: snapshot_created]
  → Diff Preprocessor + Security初筛 → DiffChunk列表 [Checkpoint: analysis_prepared]
  → Rule Engine + Read-only Tools → 规则型Findings [Checkpoint: deterministic_checks_done]
  → Security脱敏 + Budget校验 → LLM Provider → LLM型候选Findings [Checkpoint: findings_generated]
  → Evidence验证 + Finding聚合 → 最终Findings [Checkpoint: findings_verified]
  → Output Renderer → Markdown + findings.json + CommentPayload [Checkpoint: outputs_prepared]
  → Publish Controller + HeadSha校验 → Provider评论发布或跳过 [Checkpoint: publish_attempted]
  → Mark review completed [Terminal: completed]
```

## 9. Budget、Trace、Checkpoint 的协同

### 9.1 Budget 接入点

- 模型调用前：Token / 成本预估和是否允许继续
- 模型调用后：记录实际使用量
- 阶段结束时：将预算状态写入 Checkpoint

### 9.2 Trace 接入点

Trace 至少覆盖以下事件：

- Review 初始化
- 输入校验
- 快照创建
- 工具调用
- 模型调用
- Evidence 校验
- 输出准备
- 发布尝试
- 失败和中断

### 9.3 Checkpoint 接入点

以下阶段后必须落 Checkpoint：

- `input_validated`
- `snapshot_created`
- `analysis_prepared`
- `deterministic_checks_done`
- `findings_generated`
- `findings_verified`
- `outputs_prepared`
- `publish_attempted`
- `failed`

## 10. 安全边界

### 10.1 输入安全

所有 Provider 数据、工具结果和仓库内容都经过 `security` 清洗后才能进入：

- LLM
- Trace 工件
- 输出产物
- Provider 评论发布载荷

### 10.2 执行安全

第一版严格禁止执行用户仓库代码，因此架构上：

- 不提供通用 Shell 工具
- 不允许模型生成命令再交给系统执行
- 不允许“为验证结论”而直接运行仓库代码

### 10.3 输出安全

输出层只接收结构化 Findings 和安全摘要，不直接处理未清洗的原始模型文本。

### 10.4 快照一致性安全

- 所有审查基于固定 Head SHA 的不可变快照
- 恢复执行、渲染输出、发布评论前必须重新校验 Head SHA
- 代码已变更时，拒绝沿用旧审查结果

## 11. 失败与恢复设计

### 11.1 失败分类

第一版至少区分：

- 输入无效
- Provider 调用失败
- Snapshot 创建失败
- 工具执行失败
- 模型调用失败
- 输出渲染失败
- 评论发布失败
- Checkpoint 持久化失败
- `headSha` 校验失败

### 11.2 恢复原则

恢复只能发生在已写入稳定 Checkpoint 的阶段边界上。

系统恢复时：

1. 加载 Checkpoint
2. 验证输入哈希和 `headSha`
3. 恢复 Token / 成本预算
4. 恢复 Trace 上下文
5. 从 `next_action` 继续

## 12. 存储抽象与部署演进

### 12.1 第一版存储实现

第一版默认使用本地文件存储：

- `checkpoint.json`
- `trace.json`
- `findings.json`
- `report.md`
- 脱敏 trace 工件

### 12.2 存储抽象要求

系统必须通过存储接口访问持久化层，而不是在业务流程中直接拼接本地路径。

### 12.3 演进方向

未来可以将这些接口替换为：对象存储、数据库、云函数可访问的远程存储、分布式任务系统共享存储。

## 13. 推荐目录结构

```text
src/
  codereviewer/
    app/
      cli.py
      pipeline.py
    domain/
      models.py
      enums.py
      interfaces/
        scm.py
        llm.py
        tool.py
        store.py
    adapters/
      scm/
        github.py
        gitlab.py
      llm/
        openai_compatible.py
      storage/
        file_store.py
    services/
      input_resolver.py
      snapshot_builder.py
      diff_preprocessor.py
      tool_engine.py
      rule_engine.py
      evidence_validator.py
      finding_aggregator.py
      budget_manager.py
      security.py
      checkpoint_manager.py
      trace_manager.py
      publish_controller.py
    tools/
      registry.py
      builtin/
    reporters/
      markdown.py
      json_output.py
      comment_publisher.py
    config.py

tests/
  unit/
  integration/

docs/
  SPEC.md
  ARCHITECTURE.md
  DEV_PLAN.md
  CHECKLIST.md

artifacts/
  reviews/
    {review_id}/
      checkpoint.json
      findings.json
      report.md
      trace.json
      trace_artifacts/
```

## 14. 第二阶段目标

第二阶段不推翻 MVP 架构，而是在现有 8 阶段 Pipeline、Checkpoint、Trace、Budget 和 Security 骨架上做增量增强。第二阶段只聚焦以下目标：

- 单 Agent `AgentRuntime` 多轮 tool-use 审查闭环
- 完全声明式工具注册与执行
- 评论定位校验与更细粒度 trace
- LLM function calling 协议适配

第二阶段明确不做以下能力：

- 多 Agent 编排
- 多 Provider 并行路由
- 受控沙箱中的 `run_typecheck` / `run_tests`
- 用户仓库代码执行
- Web UI

## 15. 第二阶段增量架构

### 15.1 演进原则

- 保持 8 阶段 Pipeline 名称和阶段边界不变
- 重点增强 `findings_generated` 和 `findings_verified`
- 保持单主 Agent，不引入多 Agent 编排
- `orchestrator` 仍然只依赖稳定接口，不直接依赖具体工具实现
- 工具继续显式注册，但从 class-based 迁移为声明式定义

### 15.2 Pipeline 影响范围

第二阶段对现有 Pipeline 的影响如下：

- 阶段 1 到阶段 3：保持不变
- 阶段 4：规则引擎继续存在，但底层工具接口切换到声明式 ToolRegistry 兼容层
- 阶段 5：从“单次 LLM 审查”演进为 `AgentRuntime` 驱动的多轮 tool-use 审查
- 阶段 6：在证据校验和 finding 聚合之前增加 `CommentLocator` 定位有效性校验
- 阶段 7 到阶段 8：对外行为保持不变，但输出与 trace 增加新字段和引用

### 15.3 新增与改动模块

| 类型 | 模块 | 职责 |
|---|---|---|
| 新增 | `services/agent_runtime.py` | 管理外层多轮和内层 tool-use 循环 |
| 新增 | `tools/declarative.py` | 提供 `@tool` 装饰器和 schema 自动生成 |
| 新增 | `services/comment_locator.py` | 校验 finding 的 file/line 是否指向有效 diff 新增行 |
| 改动 | `tools/registry.py` | 从 class-based 注册演进为声明式函数注册 |
| 改动 | `services/tool_engine.py` | 适配新的 ToolRegistry，并保持规则链路兼容 |
| 改动 | `adapters/llm/openai_compatible.py` | 支持 `tools` / `tool_calls` 协议 |
| 改动 | `services/review_runner.py` | 在阶段 5 接入 AgentRuntime，在阶段 6 接入 CommentLocator |
| 改动 | `services/trace_manager.py` | 支持更细粒度的工具调用和评论提交细节 |

### 15.4 AgentRuntime 边界

`AgentRuntime` 是第二阶段的执行内核，但它仍然处于单主 Agent 架构内，不是多 Agent 编排器。

其职责包括：

- 组装 system prompt、diff 摘要、既有 findings 和工具 schema
- 驱动外层多轮循环
- 驱动内层 tool-use 循环
- 处理控制工具 `code_comment` 和 `task_done`
- 将分析工具调用委托给声明式 ToolRegistry
- 接入预算检查、grace round、trace 记录和 stop reason

其不负责：

- 直接发布评论
- 修改用户代码
- 执行任意 shell
- 绕过 checkpoint、budget、security 和 trace 约束

### 15.5 声明式工具架构

第二阶段中的工具系统采用“显式注册 + 声明式定义”的方式：

- 工具定义就是带 `@tool` 的函数本身
- 工具元数据由函数签名、类型注解和装饰器参数生成
- `snapshot`、`provider` 等运行时上下文通过 `ToolExecutionContext` 注入
- 工具仍然必须有稳定名称、输入约束、失败行为和有界输出
- 新增工具不允许要求修改 Agent 主循环

这意味着 `orchestrator` 和 `AgentRuntime` 只依赖 `ToolRegistry` 的稳定接口，而不依赖某个具体工具实现细节。

### 15.6 第二阶段领域模型增量

第二阶段需要在现有领域模型上新增以下结构化契约：

- `ToolExecutionContext`
- `ToolCall`
- `ToolChatMessage`
- `ToolChatRequest`
- `ToolChatResponse`
- `AgentLoopState`
- `ToolCallRecord`

同时需要扩展以下既有模型：

- `Finding`
  - 增加 `location_valid`
  - 增加 `trace_refs`
  - 增加 `agent_round`
- `TraceEvent`
  - 增加结构化 `details`

### 15.7 Trace、Checkpoint 与 Budget 的新增要求

第二阶段仍然沿用 MVP 的三项横切约束，但需要补充更细粒度的记录：

- Trace 需要记录每轮工具调用、评论提交、stop reason 和 round 摘要
- Checkpoint 需要保存 AgentRuntime 相关状态或至少保存阶段结果与下一步动作
- Budget 需要在每次工具化 LLM 调用前后继续记录估算值和实际值
- Resume 仍然只能从稳定阶段边界恢复，不能静默重放已完成调用

### 15.8 安全边界保持不变

第二阶段虽然引入 tool-use，但安全边界不放松：

- 默认仍不执行用户仓库代码
- 默认仍不向模型暴露任意 shell
- 所有发给模型的 diff、文件内容和工具输出都要先脱敏和截断
- Secret 仍然不能进入 prompt、trace、checkpoint、report 或评论发布载荷

## 16. 架构总结

第一版架构的核心不是“尽可能复杂”，而是“用最小但稳定的模块集合跑通严格贴题的可靠闭环”。

架构判断标准如下：

- 是否能覆盖 GitHub 和 GitLab
- 是否能支持链接与 `repo + base_branch + head_branch`
- 是否能围绕不可变快照组织所有分析
- 是否能以单主 Agent 跑完完整流程
- 是否能在阶段边界恢复
- 是否能让每条 Finding 追溯到证据和 trace 工件
- 是否能在不修改主循环的前提下扩展工具和 Provider

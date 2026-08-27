# Code Review Agent SPEC

## 1. 文档目的

本文档定义 Code Review Agent 第一版产品规格，作为后续架构设计、开发计划、测试验收和交付说明的依据。

本文档重点回答：

- 第一版解决什么问题
- 第一版支持哪些输入与输出
- 系统必须满足哪些恢复、预算、可观测、安全和扩展要求
- 哪些能力明确不在第一版范围内

## 2. 产品背景

研发流程中的 Code Review 是高价值但高负担的环节。目标是构建一个可靠的 Code Review Agent，接收 GitHub Pull Request 或 GitLab Merge Request 相关输入，生成带证据支撑的审查结果，并按配置输出为：

- Provider 评论
- 本地 Markdown 报告
- 结构化 `findings.json`

系统必须满足以下核心要求：

- 可恢复：断网、重启或进程中断后可以恢复执行
- 有预算：每次 Review 使用共享预算，并在预算不足时降级或停止
- 可观测：每条评论或 Finding 能追溯到输入、工具、Prompt、模型输出和验证证据
- 有证据：所有结论必须基于已采集并可引用的证据
- 安全：不得将 Secret 暴露给 LLM，不得执行用户仓库中的任意代码
- 可扩展：新增工具通过显式注册接入，不要求修改 Agent 主循环

## 3. 产品目标

### 3.1 MVP 目标

第一版产品目标如下：

- 支持针对 GitHub Pull Request 进行只读审查
- 支持针对 GitLab Merge Request 进行只读审查
- 支持以链接或 `repo + base_branch + head_branch` 作为输入
- 生成结构化 Findings
- 输出本地 Markdown 审查报告
- 输出结构化 `findings.json`
- 支持将审查结果发布到 GitHub / GitLab 评论系统
- 记录完整且可追溯的 Trace
- 支持 Review 过程的 Checkpoint 和恢复
- 支持共享 Token 与成本预算控制

### 3.2 非目标

第一版明确不实现以下能力：

- 自动修改代码
- 自动 Merge
- Web UI
- 多 Agent 编排
- 执行用户仓库内测试、脚本或任意 Shell 命令
- 无限制的全仓库扫描
- 多 Provider 并行路由

## 4. 目标用户与使用场景

### 4.1 目标用户

- 需要辅助完成 PR / MR 审查的开发者
- 需要生成可归档审查报告的团队
- 需要在受控预算和安全边界内使用 LLM 的工程负责人

### 4.2 典型场景

- 对 GitHub PR 生成本地 Markdown 审查报告
- 对 GitLab MR 直接发布审查评论
- 在中途中断后恢复未完成的 Review
- 在预算紧张时降级模型或停止分析

## 5. MVP 范围

### 5.1 支持的审查对象

第一版支持以下两类对象：

- GitHub Pull Request
- GitLab Merge Request

### 5.2 分析范围

第一版仅支持只读分析，包括：

- PR / MR 元数据
- PR / MR Diff
- 变更文件列表
- 通过受控只读工具读取的文件内容
- 静态规则或模式匹配得到的附加证据

第一版默认不执行用户仓库代码，因此不包含：

- 测试运行
- Typecheck 执行
- 构建执行
- 任意仓库脚本执行

## 6. 输入定义

系统必须至少支持以下输入形式：

### 6.1 GitHub PR URL

示例：

```text
https://github.com/{owner}/{repo}/pull/{number}
```

### 6.2 GitLab MR URL

示例：

```text
https://gitlab.com/{group}/{project}/-/merge_requests/{number}
```

### 6.3 repo + base_branch + head_branch

示例：

```text
provider=github | gitlab
repo=owner/name
base_branch=main
head_branch=feature/my-change
```

说明：

- 分支模式必须显式给出 `provider`、`base_branch` 和 `head_branch`
- 系统应基于这两个分支生成待审查变更快照

### 6.4 附加便捷输入

第一版可以额外支持如下便捷输入，但它不是题面主输入：

```text
provider=github | gitlab
repo=owner/name
change_number=123
```

### 6.5 输入校验要求

系统必须校验：

- 输入是否能唯一定位一次 Review 目标
- Provider、仓库、链接或分支参数是否完整
- 是否成功解析出 Base SHA 和 Head SHA
- 是否能生成不可变快照标识

无效输入必须返回明确失败结果，不得静默降级为其他行为。

## 7. 输出定义

系统必须支持以下三类输出能力：

### 7.1 Markdown 报告

用于人工阅读和归档的本地 Markdown 审查报告，应包含：

- Review 基本信息
- 审查范围
- 审查结论摘要
- Findings 列表
- 每条 Finding 的证据引用
- Budget、Trace、Checkpoint 摘要
- 未完成项或中断原因

### 7.2 Findings JSON

结构化 `findings.json` 既是中间结果，也是正式落盘产物，用于：

- 恢复与重试
- 审计与追踪
- 后续系统集成
- 与 Markdown 渲染解耦

### 7.3 Provider 评论发布

系统必须支持将最终审查结果转换为 GitHub PR 评论或 GitLab MR 评论。

说明：

- 是否真正发布由显式配置与人工批准决定
- 系统不得在未授权情况下自动公开发布评论
- 发布前必须重新校验 `headSha`

## 8. Finding 契约

LLM 或规则系统产出的审查结论，必须先解析为结构化 Finding，才能进入渲染或发布阶段。

每条 Finding 至少包含以下字段：

- `summary`
- `severity`
- `confidence`
- `file`
- `line`
- `explanation`
- `evidence`
- `suggested_fix` 可选

### 8.1 severity 分级

第一版采用四档严重程度：

- `critical`
- `high`
- `medium`
- `low`

### 8.2 confidence 分级

第一版采用两档置信度：

- `high`：由代码、Diff、规则、静态分析或其他可靠信号直接支持
- `reference`：问题具有合理性，但缺少充分直接证据

### 8.3 发布约束

- 未经验证的模型推测不得作为确定性结论输出
- 每条 Finding 至少包含一条证据引用
- 无法定位到文件或上下文的结论不得作为正式 Finding 发布

## 9. 证据要求

### 9.1 合法证据来源

第一版允许的证据来源包括：

- 固定快照中的 Diff 行
- 通过注册只读工具读取的文件内容
- 静态规则或模式匹配结果
- 已验证的依赖契约
- Provider 返回的受信元数据

第一版默认不包含以下证据来源：

- 运行用户仓库测试结果
- 运行用户仓库 Typecheck 结果
- 任意 Shell 命令执行结果

### 9.2 证据可追溯性

系统必须能够回答：

- 这是哪一次 Review
- 审查了哪个仓库和哪个 Commit
- 使用了哪些工具
- 哪些 Diff 或文件内容被发送给模型
- 使用了哪个模型和 Prompt
- 哪些证据支持该 Finding
- 证据是否经过独立验证

## 10. Trace 与可观测性

系统必须为每次 Review 记录可追溯 Trace，至少覆盖：

- Review 标识
- 时间戳
- 使用的输入
- 调用的工具
- 工具输入输出摘要
- 发送给模型的内容引用
- Prompt 引用
- 模型标识与调用参数摘要
- 模型回复引用
- 结构化 Findings 生成结果
- 失败信息和中断原因

说明：

- Trace 中应保存脱敏后的原始工件或其稳定引用，不能只保留抽象结论
- Trace 中不得出现 Secret

## 11. 快照与 Commit 安全

每次 Review 都必须绑定不可变的 `headSha`。

系统必须：

1. 在创建 Review 时记录 `baseSha` 和 `headSha`
2. 在恢复、渲染输出或发布评论前重新校验当前 `headSha`
3. 如果目标代码已变化，则拒绝将旧结论视为当前有效结果
4. 明确提示用户需要基于新版本重新发起 Review

同一个 Commit 的 Checkpoint 不能静默应用到另一个 Commit。

## 12. Checkpoint 与恢复

### 12.1 目标

系统必须支持在稳定阶段后保存 Checkpoint，并在中断后恢复执行，而不丢失已完成成果和预算状态。

### 12.2 Checkpoint 最小字段

Checkpoint 至少包含：

- `review_id`
- 输入内容哈希
- 仓库标识
- `provider`
- `base_sha`
- `head_sha`
- 已完成阶段
- 已收集 Findings
- `trace_id`
- Token 预算状态
- 成本预算状态
- 下一步动作
- 最后更新时间
- 终止或失败状态

### 12.3 第一版存储策略

- 第一版默认使用本地文件存储 Checkpoint
- 存储格式优先采用可读、易调试的数据格式
- 第一版实现可以选择 JSON 文件作为默认落地形式

### 12.4 演进要求

虽然第一版采用本地文件存储，但架构上必须预留可替换存储接口，以支持未来：

- 对象存储
- 数据库存储
- 云上部署
- 分布式执行场景

主流程不得与本地磁盘路径强耦合。

### 12.5 恢复要求

恢复时必须：

1. 读取 Checkpoint
2. 校验输入内容哈希
3. 校验仓库标识与 `headSha`
4. 恢复已消耗的 Token 与成本预算
5. 跳过已完成阶段
6. 从记录的下一步动作继续

不得在未明确说明的情况下重置预算或重复已完成的模型调用。

## 13. 预算要求

### 13.1 预算模型

每次 Review 只有一个共享预算。

预算至少包含两类维度：

- Token 预算
- 成本预算

所有模型调用、工具执行和未来可能引入的子 Agent 都必须共享同一 Review 预算。

### 13.2 第一版预算策略

第一版以 Token 控制为主执行机制，同时必须显式支持成本预算字段和记录。

建议阶段策略：

- 0% - 60%：使用正常质量模型
- 60% - 85%：切换到低成本模型
- 85% - 100%：只执行必要分析
- 100%：停止执行并保留当前结果

### 13.3 超预算行为

预算耗尽前，系统应优先尝试降级；若仍无法继续，则停止执行，并保留当前 Findings、Trace 与 Checkpoint。

系统不得静默提高预算。

## 14. 安全约束

### 14.1 不可信输入原则

以下内容全部视为不可信输入：

- 仓库内容
- Pull Request / Merge Request Diff
- Issue 描述
- 评论内容
- 工具输出

### 14.2 Secret 保护

发送内容给 LLM 前，系统必须：

- 检测并脱敏 API Key
- 检测并脱敏 Access Token
- 检测并脱敏私钥
- 检测并脱敏账号凭据
- 排除 `.env` 和 Secret 配置内容
- 限制发送内容大小

Secret 绝不能出现在：

- Prompt
- 模型回复
- Markdown 报告
- Provider 评论
- Trace
- Checkpoint
- 控制台日志
- 错误消息

### 14.3 执行限制

第一版默认禁止执行用户仓库代码。

这意味着系统不得：

- 运行仓库测试
- 运行仓库 Typecheck
- 执行仓库脚本
- 暴露任意 Shell 工具给模型

## 15. Provider 与模型配置

### 15.1 Provider 范围

第一版至少包含：

- 一个 GitHub SCM Provider
- 一个 GitLab SCM Provider
- 一个已配置好的 LLM Provider

### 15.2 抽象要求

SCM Provider 与 LLM Provider 都必须按兼容接口方式设计，不应将主流程逻辑写死到某一家厂商 SDK。

配置项至少应包括：

- `model`
- `api_key`
- `base_url` 可选
- `max_total_tokens`
- `max_total_cost`
- 输出目标配置

## 16. 工具扩展要求

所有工具都必须显式注册。

新增工具不能要求修改 Agent 主循环。

每个工具至少应定义：

- 稳定工具名
- 能力描述
- 输入 Schema
- 输出 Schema 或有界结果结构
- 执行策略
- 最大输出大小
- Trace 信息
- 失败行为

优先工具类型包括：

- `read_diff`
- `read_file`
- `list_changed_files`
- `find_references`
- `run_typecheck`
- `run_tests`

说明：

- 虽然第一版默认不执行 `run_typecheck` 和 `run_tests`，但接口和注册机制可以提前设计
- 工具能力暴露必须受控，禁止向模型暴露任意 Shell

## 17. 失败行为

每个操作都必须产生以下两类结果之一：

- 成功结果
- 明确的非执行或失败结果

失败信息至少应说明：

- 哪个操作失败
- 哪个阶段失败
- 已有 Findings 是否保留
- 是否可以恢复
- 操作者下一步应该做什么

禁止使用空报告、通用成功消息或静默重试掩盖失败。

## 18. 成功标准

当满足以下条件时，可认为 MVP 达到预期：

- 能基于 GitHub PR 输入创建不可变快照
- 能基于 GitLab MR 输入创建不可变快照
- 能基于 `repo + base_branch + head_branch` 创建不可变快照
- 能在只读模式下完成一次审查
- 能输出结构化 Findings
- 能输出 Markdown 报告
- 能发布 Provider 评论
- 能保存可追溯 Trace
- 能保存并恢复 Checkpoint
- 能对 Token 与成本预算进行记录、降级和停止控制
- 能保证 Secret 不进入 Prompt、输出或持久化结果

## 19. 验收口径

MVP 验收至少应覆盖以下行为：

- 无效输入被明确拒绝
- 有效 GitHub / GitLab 链接输入可生成快照
- 有效 `repo + base_branch + head_branch` 输入可生成快照
- Findings 满足结构化契约
- 每条 Finding 含证据引用
- 中断后可恢复
- `headSha` 变化时拒绝沿用旧结果
- 预算耗尽时先降级，再停止
- Markdown 和 `findings.json` 都能成功落盘
- Provider 评论发布前会校验 `headSha`
- 不执行用户仓库代码
- Secret 被正确脱敏

## 20. 后续迭代方向

本规格确认后，后续文档应继续明确：

- `ARCHITECTURE.md`：模块边界、接口抽象、数据流和阶段划分
- `DEV_PLAN.md`：按垂直切片拆分实现顺序与验证计划

可能的后续演进方向包括：

- 多 Provider 并行路由
- 云上或分布式存储
- 受控沙箱中的 Typecheck / Test 执行
- 更细粒度的证据验证和规则引擎
- 多 Agent 编排

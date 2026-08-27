# Code Review Agent CHECKLIST

## 1. 文档说明

本文档用于跟踪 Code Review Agent 第一版的开发执行、单元测试、集成验证和最终验收。

本文档不是设计文档，不重复描述产品规格和架构，而是作为以下文档的执行门禁：

- `SPEC.md`
- `ARCHITECTURE.md`
- `DEV_PLAN.md`

使用方式：

- 每开始一个里程碑前，先确认进入条件
- 每完成一个里程碑后，更新开发项、测试项、验收项和风险项
- 未满足当前里程碑的完成条件前，不进入下一里程碑

## 2. 全局进入条件

- [x] `SPEC.md` 已确认
- [x] `ARCHITECTURE.md` 已确认
- [x] `DEV_PLAN.md` 已确认
- [x] 当前开发切片已获得人工批准
- [x] 当前切片范围已明确，不包含未批准扩展
- [x] 默认不执行用户仓库代码
- [x] Provider 评论发布必须受显式配置和人工批准控制
- [x] 所有验证命令与结果都需要记录

## 3. 通用记录模板

每个里程碑完成后，至少补充以下信息：

- 实际执行命令：
- 测试/检查结果：
- 发现的问题：
- 剩余风险：
- 是否允许进入下一里程碑：

## 4. 里程碑检查清单

### M0 项目初始化脚手架

**开发项**

- [x] 已建立基础目录结构
- [x] 已建立配置入口
- [x] 已建立 CLI 空入口
- [x] 已建立空 Pipeline 骨架
- [x] 已建立核心领域模型空壳
- [x] 已建立最小 artifacts 落盘规则

**单元测试项**

- [x] 已添加 CLI / 配置 / 空流程的最小测试
- [x] 空流程 smoke test 已存在

**集成/验收项**

- [x] 项目可通过统一入口启动
- [x] 空 Pipeline 可执行到结束
- [x] 能生成最小 artifact 骨架或占位输出
- [x] 当前实现未越界到 GitHub / GitLab / LLM / 工具执行

**风险/未覆盖项**

- [x] 已记录脚手架中尚未实现的真实能力
- [x] 已确认没有过度脚手架化

**执行记录**

- 实际执行命令：`pytest tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py`
- 测试/检查结果：2 passed
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --artifact-root artifacts`
- 测试/检查结果：CLI 正常退出并生成占位工件
- 发现的问题：无阻塞问题
- 剩余风险：当前仅为 M0 骨架，尚未接入 Provider、Snapshot 真逻辑、Checkpoint/Trace、工具、规则、LLM
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M0 完成
- [x] 允许进入 M1

### M1 Provider-neutral 输入抽象 + Snapshot 骨架

**开发项**

- [x] 已建立统一 `ReviewRequest`
- [x] 已建立统一 `ReviewSnapshot`
- [x] 已支持 review URL 输入归一化
- [x] 已支持 `repo + base_branch + head_branch` 输入归一化
- [x] 已建立 `SCMProvider` 接口与 `resolve_snapshot_target`

**单元测试项**

- [x] URL 输入归一化测试已覆盖
- [x] 分支比较输入归一化测试已覆盖
- [x] 无效输入测试已覆盖

**集成/验收项**

- [x] 不同输入形式可归一为统一内部结构
- [x] Snapshot 骨架可被构造

**风险/未覆盖项**

- [x] 已记录 provider-specific 细节尚未落地部分

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py`
- 测试/检查结果：7 passed
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://github.com/owner/repo/pull/123 --artifact-root artifacts`
- 测试/检查结果：CLI 正常输出 GitHub review URL 的归一化请求与 Snapshot 骨架 JSON
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --provider github --repo owner/repo --base-branch main --head-branch feature/x --artifact-root artifacts`
- 测试/检查结果：CLI 正常输出分支比较输入的归一化请求与 Snapshot 骨架 JSON
- 发现的问题：无阻塞问题
- 剩余风险：当前仅完成 provider-neutral 输入与 Snapshot 骨架，尚未接入真实 GitHub/GitLab API，因此 `base_sha` / `head_sha` 仍为空，也未验证远端仓库存在性
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M1 完成
- [x] 允许进入 M2

### M2 GitHub Provider

**开发项**

- [x] 已实现 `GitHubProvider`
- [x] 已支持 GitHub PR URL
- [x] 已支持 GitHub 分支比较模式
- [x] 已生成 GitHub `ReviewSnapshot`
- [x] 已固化 `base_sha` / `head_sha`

**单元测试项**

- [x] GitHub PR URL 解析测试已覆盖
- [x] GitHub 分支比较测试已覆盖
- [x] GitHub API 失败测试已覆盖
- [x] `headSha` 获取与绑定测试已覆盖

**集成/验收项**

- [x] 有效 GitHub 输入可生成不可变快照
- [x] 无效 GitHub 输入返回明确失败结果

**风险/未覆盖项**

- [x] 已记录 GitHub API 边界与限制

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_github_provider.py tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py`
- 测试/检查结果：12 passed
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_github_provider.py tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py tests/unit/test_snapshot_builder.py tests/unit/test_input_resolver.py`
- 测试/检查结果：16 passed；已补充 compare 空 `commits` 回退、Authorization header、`URLError`、timeout 映射测试
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：成功生成 GitHub PR 的不可变快照；已获取 `base_sha=4023ed64df320c6a2af10f40c5ebad9f5dc997c6`、`head_sha=861777bcc3ef6de9434637de9de8781469772e28`，并落地本地 artifact
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --provider github --repo mwh1233/travelassistant --base-branch master --head-branch mwh-dev --artifact-root artifacts`
- 测试/检查结果：成功生成 GitHub 分支比较模式的不可变快照，并与 PR 路径得到一致的 `base_sha` / `head_sha`
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/999999 --artifact-root artifacts`
- 测试/检查结果：CLI 明确返回 `GitHub API request failed with HTTP 404 ...`，无静默降级
- 实际执行命令：`if ($env:GITHUB_TOKEN) { 'present' } else { 'missing' }`
- 测试/检查结果：`GITHUB_TOKEN` 缺失，无法执行 GitHub 测试评论写入
- 实际执行命令：`gh --version`
- 测试/检查结果：当前环境未安装 `gh` CLI，无法通过已登录 CLI 凭据替代 API token
- 实际执行命令：使用 GitHub REST API 向 `mwh1233/travelassistant#1` 发起 issue comment 创建请求
- 测试/检查结果：请求返回 `HTTP 403`，错误信息为 `Resource not accessible by personal access token`
- 实际执行命令：读取失败响应头中的权限提示
- 测试/检查结果：GitHub 返回 `X-Accepted-GitHub-Permissions: issues=write; pull_requests=write` 评论写入成功
- 发现的问题：真实 GitHub compare API 返回字段与初始假设不完全一致；已修复为从 `commits[-1].sha` 提取分支比较的 `head_sha`，并补充回归测试
- 剩余风险：尚未覆盖 GitHub 私有仓库、鉴权失败、rate limit 和超大 diff 截断场景；当前 Snapshot 会保留完整 diff 文本，后续需在预处理阶段增加大小控制；
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M2 完成
- [x] 允许进入 M3

### M3 GitLab Provider

**开发项**

- [x] 已实现 `GitLabProvider`
- [x] 已支持 GitLab MR URL
- [x] 已支持 GitLab 分支比较模式
- [x] 已生成 GitLab `ReviewSnapshot`
- [x] 已固化 `base_sha` / `head_sha`

**单元测试项**

- [x] GitLab MR URL 解析测试已覆盖
- [x] GitLab 分支比较测试已覆盖
- [x] GitLab API 失败测试已覆盖
- [x] 双 provider 接口一致性测试已覆盖

**集成/验收项**

- [x] 有效 GitLab 输入可生成不可变快照
- [x] GitHub / GitLab 都能通过统一接口接入

**风险/未覆盖项**

- [x] 已记录 GitLab API 边界与限制

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_gitlab_provider.py tests/unit/test_scm_provider_factory.py tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_github_provider.py`
- 测试/检查结果：26 passed
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://gitlab.com/gitlab-org/cli/-/merge_requests/3788 --artifact-root artifacts`
- 测试/检查结果：成功生成公开 GitLab MR 的不可变快照；已获取 `base_sha=854380580a36e0e0d05f13ceefcc49a04bcbddad`、`head_sha=3666606b03a099bba8228baa298f42ba37409d36`
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --provider gitlab --repo gitlab-org/cli --base-branch main --head-branch 1-add-functionality-to-merge-merge-request --artifact-root artifacts`
- 测试/检查结果：成功生成公开 GitLab 分支比较模式的不可变快照；已获取 `base_sha=854380580a36e0e0d05f13ceefcc49a04bcbddad`、`head_sha=d8624041cd28c3c7b732d210f9fabcc2ccd5b81e`
- 实际执行命令：`if ($env:GITLAB_TOKEN) { 'present' } else { 'missing' }`
- 测试/检查结果：`GITLAB_TOKEN` 缺失
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://gitlab.com/test6800935/testmr/-/merge_requests/1 --artifact-root artifacts`
- 测试/检查结果：返回 `GitLab API request failed with HTTP 404 ...`；结合 `GITLAB_TOKEN` 缺失，当前更可能是目标项目非公开或 API 访问受限
- 发现的问题：GitLab compare API 默认语义不会直接返回期望的分支差异；已修复为显式传入 `straight=true`，并通过公开项目 live 验证
- 剩余风险：尚未覆盖私有 GitLab 项目、鉴权失败、rate limit、超大 diff 截断和 GitLab 评论写入场景；当前私有 MR live 验证仍需有效 `GITLAB_TOKEN`
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M3 完成
- [x] 允许进入 M4

### M4 Pipeline 状态机 + Checkpoint / Trace 基础能力

**开发项**

- [x] 已定义 `ReviewStage`
- [x] 已建立主流程状态流转
- [x] 已在稳定阶段结束后落 Checkpoint
- [x] 已建立基础 Trace 事件模型
- [x] 已建立 trace 工件引用骨架
- [x] 已提供恢复入口

**单元测试项**

- [x] 状态流转测试已覆盖
- [x] Checkpoint 落点测试已覆盖
- [x] 恢复逻辑测试已覆盖
- [x] 失败阶段记录测试已覆盖

**集成/验收项**

- [x] 主流程可按阶段顺序推进
- [x] 可从 Checkpoint 恢复到下一阶段
- [x] Trace 中可看到关键阶段事件

**风险/未覆盖项**

- [x] 已记录当前恢复逻辑边界限制
- [x] 已记录 Trace 工件持久化暂未覆盖项

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_snapshot_builder.py tests/unit/test_checkpoint_manager.py tests/unit/test_trace_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_scm_provider_factory.py`
- 测试/检查结果：32 passed
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：成功生成 `review-8c0bad82`，并在同一目录下落地 `checkpoint.json`、`trace.json`、`placeholder.txt`
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --resume-review-id review-8c0bad82 --artifact-root artifacts`
- 测试/检查结果：成功从已有 Checkpoint 恢复；CLI 返回 `stage=completed`，Trace 追加了恢复事件
- 发现的问题：早期实现里 `review_id` 在 snapshot 前后不一致，可能导致同一次 review 的 trace/checkpoint 分裂到不同目录；现已修复为基于同一输入哈希生成并在 runner/provider 侧统一
- 剩余风险：当前 M4 的恢复仍是“基于占位阶段继续推进”，尚未接入后续真实工具、LLM、证据验证和发布链路时的细粒度恢复
- 剩余风险：Trace 当前仅持久化阶段事件，`trace_artifacts/` 的真实脱敏工件写入会在后续里程碑补齐
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M4 完成
- [x] 允许进入 M5

### M5 只读工具注册机制 + 规则检查链路

**开发项**

- [x] 已建立工具注册表
- [x] 已实现 `read_diff`
- [x] 已实现 `read_file`
- [x] 已实现 `list_changed_files`
- [x] 已实现 `find_references`
- [x] 已建立规则注册与执行机制
- [x] 规则型候选 Findings 可生成
- [x] 规则型候选 Findings 可绑定基础证据

**单元测试项**

- [x] 工具注册测试已覆盖
- [x] 重复注册测试已覆盖
- [x] 工具成功 / 失败路径测试已覆盖
- [x] 工具输出截断测试已覆盖
- [x] 规则命中 / 无命中测试已覆盖
- [x] 证据绑定测试已覆盖

**集成/验收项**

- [x] 工具必须注册后才能调用
- [x] 不依赖 LLM 即可产出结构化候选 Findings
- [x] 每条规则型候选 Finding 至少有一条证据

**风险/未覆盖项**

- [x] 已记录工具能力边界
- [x] 已确认未引入任意执行能力

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py`
- 测试/检查结果：40 passed
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：成功生成 `review-4078da3e`；`checkpoint.json` 包含 `analysis_prepared` / `deterministic_checks_done` 阶段与 `findings` 字段，当前公开样例命中 0 条规则型 findings
- 实际执行命令：`$env:PYTHONPATH='src'; python -m codereviewer.app.cli --resume-review-id review-4078da3e --artifact-root artifacts`
- 测试/检查结果：成功从已有 checkpoint 恢复；CLI 返回 `stage=completed`，未重复执行已完成阶段
- 发现的问题：M5 接入后工具 trace 最初被挂到 `analysis_prepared`，已修正为归属 `deterministic_checks_done`
- 剩余风险：`find_references` 第一版只在 `changed_files` 范围内做字面量搜索，不做全仓扫描，也不做语义级引用分析
- 剩余风险：当前 deterministic 规则仅覆盖“敏感文件名变更”和“新增调试语句”两类保守规则，更多正确性/安全性规则仍在后续里程碑补齐
- 剩余风险：二进制 diff 与超复杂文本 diff 目前只做跳过或截断保护，不做更细粒度证据抽取
- 是否允许进入下一里程碑：是

**完成判定**

- [x] M5 完成
- [x] 允许进入 M6

### M6 LLM 审查链路 + 基础预算控制

**开发项**

- [x] 已实现 Prompt 组装
- [x] 已接入安全脱敏后模型调用
- [x] 已实现结构化输出解析
- [x] 已实现模型调用前 Token / 成本预算检查
- [x] 已实现模型调用后 Token / 成本记录
- [x] 已实现超预算停止

**单元测试项**

- [x] 模型输出解析成功路径测试已覆盖
- [x] 模型输出解析失败路径测试已覆盖
- [x] 脱敏测试已覆盖
- [x] Token 计数测试已覆盖
- [x] 成本记录测试已覆盖
- [x] 超预算阻止调用测试已覆盖

**集成/验收项**

- [x] LLM 输出可转为结构化候选 Findings
- [x] Budget 状态会写入 Checkpoint
- [x] 超预算时会停止而不是静默继续

**风险/未覆盖项**

- [x] 已记录当前预算实现仅为基础版
- [x] 已记录模型输出不稳定性风险

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py`
- 测试/检查结果：11 passed；覆盖 LLM 结构化解析、脱敏、预算记录、恢复流程，以及超预算失败后写入 `FAILED` checkpoint
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py`
- 测试/检查结果：47 passed；确认 M6 改动未回归 M2-M5 已有行为
- 实际执行命令：`if ($env:LLM_API_KEY) { 'present' } else { 'missing' }`
- 测试/检查结果：`missing`；当前环境缺少 `LLM_API_KEY`，未执行真实 LLM live 验证
- 发现的问题：初版 M6 缺少“预算超限时持久化 FAILED checkpoint”的显式回归保护；现已补充 smoke test 锁定该行为
- 剩余风险：当前成本估算仍为 provider 内的保守估算，不是最终精确计费模型；精细分级降级策略留在 M7
- 剩余风险：LLM findings 当前仍使用 `verified=False` 的占位证据，正式证据校验、聚合与置信度收敛留在 M7
- 剩余风险：未配置 `LLM_API_KEY` 时无法完成真实 provider 联调，只能依赖 stub + 本地测试验证
- 是否允许进入下一里程碑：是
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_llm_reviewer.py tests/unit/test_budget_manager.py tests/unit/test_security.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：15 passed；补齐 OpenAI-compatible LLM adapter 的成功、HTTP 错误、超时和无效 JSON 回归测试
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py`
- 测试/检查结果：51 passed；确认切换到底层 `requests` 客户端后未回归已有行为
- 实际执行命令：`$env:PYTHONPATH='src'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：DeepSeek live 验证成功；生成 `review-51b7753e`，`checkpoint.json` 记录 `findings_generated -> completed` 全链路，最终产出 2 条 LLM findings，`budget.token_used=16426`，`budget.cost_used=0.040618`
- 发现的问题：基于 `urllib` 的原始实现无法稳定承载 DeepSeek 大 prompt 请求；已改为 `requests` 并拆分 connect/read timeout，read timeout 设有 120 秒保底窗口以适配真实 review 负载
- 剩余风险：当前 read timeout 策略是保守兼容值，不是按 provider/model 细化调优；后续如接入更多 Provider，可能需要在配置层继续细分
- 剩余风险：用户本轮提供的 live key 已暴露在对话上下文中，建议旋转后再用于后续联调或长期使用

**完成判定**

- [x] M6 完成
- [x] 允许进入 M7

### M7 Evidence 校验 + 多输出通道 + 精细预算 + 收尾验证

**开发项**

- [x] 已实现 Evidence 校验
- [x] 已实现 Finding 去重与聚合
- [x] 已实现 `high` / `reference` 收敛逻辑
- [x] 已实现 Markdown 报告输出
- [x] 已实现 `findings.json` 输出
- [x] 已实现 GitHub 评论发布能力
- [x] 已实现 GitLab 评论发布能力
- [x] 已实现发布前 `headSha` 校验
- [x] 已实现 0%-60% / 60%-85% / 85%-100% / 100% 预算策略
- [x] 已完成集成级收尾验证

**单元测试项**

- [x] 无证据结论过滤测试已覆盖
- [x] 规则型 / LLM 型 Finding 聚合测试已覆盖
- [x] 置信度判断测试已覆盖
- [x] Markdown / JSON 输出测试已覆盖
- [x] 评论发布成功 / 失败 / 跳过测试已覆盖
- [x] `headSha` 变化拒绝发布测试已覆盖
- [x] 60% / 85% / 100% 阈值测试已覆盖

**集成/验收项**

- [x] 最终 Findings 满足结构化契约
- [x] 每条正式 Finding 至少包含一条证据
- [x] Markdown 和 JSON 都能成功落盘
- [x] GitHub / GitLab 评论发布能力可用
- [x] 发布前会重新校验 `headSha`
- [x] 不同预算阈值行为符合预期

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：11 passed；覆盖无证据过滤、置信度收敛、重复 finding 聚合，以及 `findings_verified` 阶段在 run/resume 中的真实落点
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py`
- 测试/检查结果：57 passed；确认 M7 第一刀未回归 M0-M6 已有行为
- 实际执行命令：`$env:PYTHONPATH='src'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：live 验证成功；生成 `review-ab84ed16`，`findings_verified` 阶段已真实执行，最终 checkpoint 保留 1 条带证据的正式 finding，置信度为 `reference`
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：8 passed；覆盖 `findings.json` 写出、Markdown 报告渲染，以及 run/resume 两条主路径中的 `outputs_prepared` 落点
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py`
- 测试/检查结果：59 passed；确认 `outputs_prepared` 实阶段与新增 reporters 未回归既有行为
- 实际执行命令：`$env:PYTHONPATH='src'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：live 验证成功；生成 `review-3961b71a`，`checkpoint.json` 包含 `outputs_prepared`，并实际落地 `report.md` 与 `findings.json`，最终产出 2 条正式 findings
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：37 passed；覆盖发布开关、评论正文渲染、GitHub/GitLab 发布适配、`headSha` 变化拒绝发布，以及 run/resume 中真实 `publish_attempted` 阶段
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py`
- 测试/检查结果：70 passed；确认评论发布能力接入后未回归 M0-M7 已有行为
- 实际执行命令：`$env:PYTHONPATH='src'; $env:GITHUB_TOKEN='***'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --publish --artifact-root artifacts`
- 测试/检查结果：GitHub live 发布成功；生成 `review-77c14090`，trace 中 `publish_attempted` 记录 `comment_id=5425931341`，发布前使用的 `head_sha=861777bcc3ef6de9434637de9de8781469772e28`
- 实际执行命令：`$env:PYTHONPATH='src'; $env:GITLAB_TOKEN='***'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; python -m codereviewer.app.cli --review-url https://gitlab.com/test6800935/testmr/-/merge_requests/1 --publish --artifact-root artifacts`
- 测试/检查结果：GitLab live 流程成功；生成 `review-dfaa63b0`，本次最终 findings 为 0，`publish_attempted` 显式记录 `Publish skipped: no final findings to publish.`
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：17 passed；覆盖 60% / 85% / 100% 阈值切换、调用前 budget stop、调用后实际超额 stop，以及 resume 时 budget stopped 的跳过路径
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py`
- 测试/检查结果：76 passed；确认精细预算策略接入后未回归 M0-M7 既有行为
- 实际执行命令：`$env:PYTHONPATH='src'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MAX_TOTAL_TOKENS='100'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：live 验证成功；生成 `review-cef8e860`，trace 记录 `Budget decision before LLM call: level=stopped` 与 `LLM review skipped due to budget policy`，checkpoint 记录 `budget.degrade_level='stopped'`、`budget.stop_reason='token budget exceeded before LLM call.'`，且未产生新的 LLM findings
- 实际执行命令：`$env:PYTHONPATH='src'; $env:LLM_API_KEY='***'; $env:LLM_BASE_URL='https://api.deepseek.com'; $env:LLM_MODEL='deepseek-v4-flash'; $env:LLM_MAX_TOTAL_TOKENS='11000'; python -m codereviewer.app.cli --review-url https://github.com/mwh1233/travelassistant/pull/1 --artifact-root artifacts`
- 测试/检查结果：live 验证成功；生成 `review-d957f738`，本次调用先按 `normal` 预算放行，再因真实 provider token 使用量超出上限而在调用后记录 `budget.stop_reason='token budget exceeded after LLM call.'`，并保留当前 findings 完成后续阶段
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_gitlab_provider.py tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py`
- 测试/检查结果：17 passed；补充锁定 GitLab HTTP 403 响应体细节透传，确保 fine-grained token 缺权限时能在错误信息中直接看到所需权限
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：9 passed；确认 GitLab 错误细节增强未回归现有 pipeline / resume 行为
- 实际执行命令：使用真实 `GitLabProvider + PublishController + review_url snapshot` 对 `https://gitlab.com/test6800935/testmr/-/merge_requests/1` 执行 note 创建探针
- 测试/检查结果：真实 GitLab note 创建仍返回 `HTTP 403`；当前代码已明确暴露 `error=insufficient_granular_scope`，并指出该 fine-grained token 缺少项目权限 `[Work Item: Create]`
- 实际执行命令：使用更新后的 GitLab token 通过真实 `GitLabProvider + PublishController + review_url snapshot` 对 `https://gitlab.com/test6800935/testmr/-/merge_requests/1` 再次执行 note 创建探针，并随后查询 MR notes 列表
- 测试/检查结果：GitLab 真实评论发布成功；`PublishController` 返回 `published=true`、`provider_comment_id=3739267687`、`published_head_sha=b8df286c5caf9b8b80f12c721d85299206eb6df7`，随后只读确认该 note 已真实存在于 MR notes 列表中
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_security.py tests/unit/test_trace_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：16 passed；覆盖 prompt 脱敏、checkpoint 持久化脱敏、trace artifact 落盘与引用、输出/评论脱敏，以及恢复路径未回归
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py tests/unit/test_llm_reviewer.py tests/unit/test_checkpoint_manager.py`
- 测试/检查结果：9 passed；确认输出发布、LLM prompt 组装与 checkpoint 存储在引入脱敏后未回归
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py tests/unit/test_checkpoint_manager.py tests/unit/test_trace_manager.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_github_provider.py tests/unit/test_gitlab_provider.py tests/unit/test_cli.py tests/unit/test_input_resolver.py tests/unit/test_snapshot_builder.py tests/unit/test_scm_provider_factory.py tests/unit/test_security.py tests/unit/test_budget_manager.py tests/unit/test_llm_reviewer.py tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_evidence_validator.py tests/unit/test_finding_aggregator.py tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py`
- 测试/检查结果：82 passed；确认引入脱敏持久化与 trace artifact 后，M0-M7 既有行为未回归
- 发现的问题：真实 PR 上多个 LLM 候选 findings 在 `findings_verified` 后被过滤/聚合为 1 条，说明本阶段已经接管“候选 finding -> 正式 finding”的收敛逻辑
- 发现的问题：真实 live run 中 `budget.token_used=23372` 高于 `token_limit=20000`，但当前仍允许本次调用完成且 `stop_reason` 为空；这说明“调用前估算门禁”已生效，但“调用后实际超额收敛”和分级降级策略仍待后续 M7 切片补齐
- 发现的问题：GitLab CLI 全链路当前仍缺少“自动生成 final findings 后再自动 publish 成功”的端到端证据；本轮确认的是 GitLab 发布接口与 `PublishController` 真实可用
- 发现的问题：DeepSeek 真实返回 token 与本地估算存在明显偏差；当前已把“调用后实际超额”收敛到 trace/checkpoint，但 prompt 缩减仍是基于字符长度的近似策略
- 发现的问题：早先 GitLab fine-grained token 的实际授权不足曾阻塞真实 note 创建；现已通过新 token 完成真实发布验证，但也说明发布链路对 token scope 边界较敏感
- 是否允许继续后续 M7 切片：是

**风险/未覆盖项**

- [x] 已记录评论发布策略的人工控制边界
- [x] 已记录收尾验证仍未覆盖的场景
- [x] 已确认第一版未越界到第二阶段能力
- [x] 已记录精细预算当前采用 prompt 缩减而非多模型切换
- [x] 已记录真实 provider token 估算偏差风险
- [x] 已记录 GitLab 发布链路对 token scope 边界敏感

**完成判定**

- [x] M7 完成
- [x] 允许进入 MVP 总验收

## 5. MVP 总验收清单

- [x] GitHub PR URL 可生成不可变快照
- [x] GitLab MR URL 可生成不可变快照
- [x] `repo + base_branch + head_branch` 可生成不可变快照
- [x] 只读分析链路可运行
- [x] 结构化 Findings 可生成
- [x] 每条正式 Finding 至少有一条证据引用
- [x] Markdown 报告可落盘
- [x] `findings.json` 可落盘
- [x] GitHub 评论发布能力可用
- [x] GitLab 评论发布能力可用
- [x] 发布前 `headSha` 会重新校验
- [x] Checkpoint 可保存与恢复
- [x] Trace 可追溯关键执行过程
- [x] Trace 中可定位脱敏原始工件引用
- [x] Token 预算可记录
- [x] 成本预算可记录
- [x] Budget 超限时可停止
- [x] Budget 达到阈值时可降级
- [x] Secret 不进入 Prompt
- [x] Secret 不进入输出
- [x] Secret 不进入 Trace / Checkpoint
- [x] 不执行用户仓库代码
- [x] 未引入自动 Merge / 多 Agent / 用户仓库代码执行等第二阶段能力

## 6. 最终放行条件

- [x] `M0` 到 `M7` 均已完成
- [x] 所有关键测试与检查已执行并记录
- [x] 已知风险已明确记录
- [x] 未验证假设已明确记录
- [x] MVP 总验收清单全部满足
- [x] 允许进入下一阶段开发或交付

## 7. Phase 2 进入条件

- [x] `docs/SPEC2.md` 已确认
- [x] `docs/ARCHITECTURE.md` 已同步第二阶段增量架构
- [x] `docs/DEV_PLAN.md` 已同步第二阶段里程碑
- [x] 当前切片范围已获得人工批准
- [x] 默认仍不执行用户仓库代码
- [x] 默认仍不引入多 Agent 编排
- [x] 第二阶段开发继续沿用 MVP 的 Checkpoint / Trace / Budget / Security 边界

## 8. Phase 2 执行清单

### P2-M1 声明式工具基础设施

**开发项**

- [x] 新增 `@tool` 装饰器
- [x] 新增类型注解到 JSON Schema 的自动生成
- [x] 新增受控目录内的自动发现与注册
- [x] 改造 `ToolRegistry` 支持函数式注册
- [x] 新增 `ToolExecutionContext`
- [x] 保持 `ToolEngine` 对规则链路的向后兼容

**单元测试项**

- [x] schema 自动生成测试
- [x] 自动发现跳过私有模块测试
- [x] 重复注册测试
- [x] 上下文注入测试
- [x] 工具异常映射测试

**集成/验收项**

- [x] 新工具无需定义 class 即可注册
- [x] `discover_and_register()` 能扫描受控目录自动注册声明式工具
- [x] 新增工具文件无需修改 `__init__.py` 或主流程注册代码
- [x] 现有规则链路在兼容层下继续可运行
- [x] 运行时上下文参数不会暴露到 schema

**风险/未覆盖项**

- [x] 已记录当前 schema 生成能力的边界
- [x] 已记录自动发现与手动注册共存时的边界
- [x] 已记录与旧工具接口共存时的兼容风险

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_declarative_tools.py tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py`
- 测试/检查结果：17 passed；覆盖 schema 自动生成、自动发现跳过私有模块、重复注册拒绝、上下文注入、异常映射，以及规则链路兼容回归
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：10 passed；确认声明式工具基础设施接入后 pipeline / resume 未回归
- 发现的问题：本轮未发现新的阻塞问题
- 剩余风险：schema 自动生成当前主要依赖 Pydantic `TypeAdapter`，复杂注解仍可能退化为较宽松 schema；自动发现与手动注册虽然可共存，但当前尚未增加专门回归来锁定覆盖顺序； registry 仍保留 legacy class tool 与声明式 tool 双栈兼容，后续切换到 Phase 2 主链路时仍需持续关注兼容边界
- 是否允许进入下一里程碑：是

### P2-M2 内置只读工具迁移

**开发项**

- [x] 迁移 `read_file`
- [x] 迁移 `read_diff`
- [x] 迁移 `list_changed_files`
- [x] 迁移 `find_references`
- [x] 更新内置工具注册入口

**单元测试项**

- [x] `read_file` 成功/失败路径测试
- [x] `read_diff` 成功/失败路径测试
- [x] `list_changed_files` 测试
- [x] `find_references` 测试
- [x] 输出截断与 trace 摘要测试

**集成/验收项**

- [x] 4 个工具均通过声明式方式注册
- [x] 内置工具注册入口不再依赖旧的 `*Tool` 类显式注册
- [x] 工具迁移后规则链路无回归
- [x] 工具仍然保持只读、受控和有界输出

**风险/未覆盖项**

- [x] 已记录 `find_references` 搜索范围边界
- [x] 已记录超大文件或复杂 diff 的工具输出限制

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_declarative_tools.py tests/unit/test_tool_registry.py tests/unit/test_builtin_tools.py tests/unit/test_rule_engine.py`
- 测试/检查结果：17 passed；覆盖 `read_file` 成功/失败、`read_diff` 成功/失败、`list_changed_files`、`find_references`、输出截断与 trace 摘要，以及内置 registry 仅暴露 4 个声明式只读工具
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：10 passed；确认内置只读工具迁移后规则链路、pipeline 与 resume 均无回归
- 发现的问题：迁移初期存在 builtin `__init__.py` 仍引用旧 `*Tool` 类的断裂状态，本轮已修复并通过测试锁定
- 剩余风险：`find_references` 当前只在 `changed_files` 范围内做字面量搜索，不做全仓或语义级引用分析；超大文件或复杂 diff 仍以截断或跳过为主，不提供更细粒度结果
- 是否允许进入下一里程碑：是

### P2-M3 LLM function-calling 适配

**开发项**

- [x] 扩展 `LLMProvider` 协议
- [x] 扩展 OpenAI-compatible adapter 支持 `tools` / `tool_calls`
- [x] 新增 `ToolChatMessage` / `ToolCall` / `ToolChatRequest` / `ToolChatResponse`
- [x] 处理 tool call 参数解析失败
- [x] 处理 provider 不支持 function calling 的降级或失败路径

**单元测试项**

- [x] tool call 解析测试
- [x] 非法 JSON 参数测试
- [x] 无 tool call 响应路径测试
- [x] token / 成本记录回归测试

**集成/验收项**

- [x] provider 能接收工具 schema
- [x] provider 能返回并解析 tool call
- [x] trace 能记录工具化 LLM 调用摘要

**风险/未覆盖项**

- [x] 已记录 provider 兼容性边界
- [x] 已记录 function calling 失败时的可恢复行为

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_llm_reviewer.py tests/unit/test_trace_manager.py`
- 测试/检查结果：14 passed；覆盖 tool schema 请求体构造、tool call 解析、非法 JSON arguments、无 tool call 纯文本响应、HTTP 400 失败路径、token / 成本字段回归，以及 trace 结构化 details 持久化
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：10 passed；确认扩展 `LLMProvider` 协议和 OpenAI-compatible adapter 后，现有 M6/M7 pipeline / resume 旧链路未回归
- 发现的问题：本轮未发现新的阻塞问题
- 剩余风险：当前只对 OpenAI-compatible 接口完成了 function-calling 适配，尚未验证不同兼容 provider 对 `tool_calls` 字段细节的差异； tool chat 目前只完成协议层和 trace 结构能力，真正的多轮 tool-use 消费仍待 `P2-M4` 接入 `AgentRuntime`
- 是否允许进入下一里程碑：是

### P2-M4 AgentRuntime 接入

**开发项**

- [x] 新增 `services/agent_runtime.py`
- [x] 实现 `code_comment`
- [x] 实现 `task_done`
- [x] 实现外层多轮和内层 tool-use 循环
- [x] 接入预算控制和 grace round
- [x] 接入阶段 5 的 trace 记录
- [x] 在阶段 5 接入 AgentRuntime

**单元测试项**

- [x] 多轮消息累积测试
- [x] 控制工具分流测试
- [x] 分析工具调用测试
- [x] 空响应终止测试
- [x] grace round 测试
- [x] resume 测试

**集成/验收项**

- [x] 模型可调用只读分析工具
- [x] 模型可提交结构化候选 findings
- [x] 模型可通过 `task_done` 结束循环
- [x] 每条候选 finding 都能关联产生它的工具调用或 LLM 响应引用
- [x] run / resume 在新链路下可用

**风险/未覆盖项**

- [x] 已记录 prompt 膨胀与循环控制风险
- [x] 已记录超预算后保守收尾策略边界

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_agent_runtime.py tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py`
- 测试/检查结果：14 passed；覆盖分析工具调用、`code_comment` / `task_done` 控制工具分流、grace round 仅保留控制工具、连续空响应触发 `empty_rounds` 终止，以及第 2 轮注入上一轮 finding 摘要的消息累积行为；同时确认 `run / resume` 新链路未回归
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_trace_manager.py`
- 测试/检查结果：11 passed；确认 `chat_with_tools` 协议层与 `TraceManager.details` 递归脱敏仍与 `AgentRuntime` 接入兼容
- 发现的问题：补测过程中仅发现测试代码误把 `config` 作为字典传入 `AgentRuntime`；已改为显式 `AgentRuntimeConfig`，未暴露新的生产逻辑缺口
- 剩余风险：`AgentRuntime` 当前仍采用“消息全量累积 + 固定轮次/空响应/tool round 上限”控制循环，后续真实复杂 PR 上仍需关注 prompt 膨胀与重复工具调用成本；grace round 当前只保证在预算挡住后允许一次仅控制工具的保守收尾，不负责进一步压缩上下文或重规划分析范围；finding 目前主要通过 `agent_tool_call` 证据引用关联控制工具调用，定位有效性校验仍待 `P2-M5` 的 `CommentLocator`
- 是否允许进入下一里程碑：是

### P2-M5 定位校验、阶段集成与回归收尾

**开发项**

- [x] 新增 `CommentLocator`
- [x] 在阶段 6 接入定位校验
- [x] 无效定位 findings 降级为 `reference`
- [x] 更新 trace / checkpoint / output 兼容新增字段
- [x] 完成第二阶段回归验证

**单元测试项**

- [x] 定位有效测试
- [x] 定位无效降级测试
- [x] `print(` 误报回归测试
- [x] 输出层新增字段兼容测试
- [x] run / resume 端到端回归测试

**集成/验收项**

- [x] 无效 `file/line` 不会直接作为高置信度结果输出
- [x] `findings.json` 与 `report.md` 可落地
- [x] 第二阶段新增 trace / checkpoint 字段可被持久化
- [x] 规则引擎覆盖不少于 5 条规则，且 `print(` 误报得到修正
- [x] README、声明式工具说明、Agent Runtime 设计说明与执行清单已同步收口

**风险/未覆盖项**

- [x] 已记录仅做同文件 diff 行号校验的边界
- [x] 已记录未实现的跨文件重定位与并发优化

**执行记录**

- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_comment_locator.py tests/unit/test_evidence_validator.py tests/unit/test_rule_engine.py tests/unit/test_json_output.py tests/unit/test_markdown_reporter.py`
- 测试/检查结果：13 passed；覆盖 `CommentLocator` 有效/无效定位校验、`location_valid` 对置信度的影响、规则引擎不少于 5 条规则、`print(` 误报修复，以及 `findings.json` / `report.md` 对新增字段的兼容
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_pipeline_smoke.py tests/unit/test_resume_flow.py tests/unit/test_agent_runtime.py`
- 测试/检查结果：14 passed；确认阶段 6 接入定位校验后，`run / resume`、`AgentRuntime`、checkpoint 持久化与输出落地链路均未回归，并验证无效定位 finding 会在 pipeline 结果中降级
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_security.py tests/unit/test_trace_manager.py tests/unit/test_finding_aggregator.py tests/unit/test_publish_controller.py tests/unit/test_comment_reporter.py`
- 测试/检查结果：14 passed；确认新增 `location_valid` 字段、阶段 6 集成和规则扩展未破坏 security、trace、聚合和发布链路
- 实际执行命令：`$env:PYTHONPATH='src'; pytest tests/unit/test_openai_compatible_llm_provider.py tests/unit/test_declarative_tools.py tests/unit/test_builtin_tools.py tests/unit/test_tool_registry.py`
- 测试/检查结果：23 passed；确认 Phase 2 既有的 function calling、声明式工具注册和内置只读工具链路未回归
- 发现的问题：本轮发现 `Finding` 契约中尚缺 `location_valid` 字段，已按最小范围补齐；同时核对到仓库缺少 `README.md`、声明式工具说明和 `AgentRuntime` 设计说明，现已补齐对应文档
- 剩余风险：`CommentLocator` 当前只做“同文件 diff 新增行”校验，未实现跨文件重定位；规则引擎虽然已扩到 5 条，但仍偏保守，后续仍需继续按真实误报/漏报反馈迭代；`AgentRuntime` 的上下文增长问题目前仍依赖预算与轮次上限控制，尚未做上下文压缩
- 是否允许结束 Phase 2：是

## 9. Phase 2 总验收清单

- [x] 声明式工具注册已接入主流程
- [x] 新增工具不需要修改主循环
- [x] LLM 支持 function calling
- [x] 单 Agent tool-use 审查链路可运行
- [x] 评论定位校验可运行
- [x] run / resume 在 Phase 2 新链路下可用
- [x] `findings.json` 和 `report.md` 兼容新增字段
- [x] trace / checkpoint 可追踪工具调用与新增状态
- [x] README、声明式工具说明和 Agent Runtime 设计说明已完成
- [x] 默认仍未引入多 Agent、用户仓库代码执行和任意 shell

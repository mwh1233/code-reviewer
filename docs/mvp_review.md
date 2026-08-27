# MVP Code Review（修正版）

> 对 bytedance-codereviewer v1（MVP 版本）的完整代码审查，用于指导 spec2 迭代。
> 审查时间：2026-08-26
> 审查范围：src/ 全部源码 + tests/ 测试结构 + artifacts/ 运行产物
>
> **修正说明**：初版 review 基于旧版本代码，误判了后 3 阶段、置信度判定、去重、预算降级、trace artifact、security 脱敏等能力。本版本基于当前完整代码修正。

---

## 一、整体评价

**工程化完善，核心 Agent 能力缺失。**

这是一个能跑通全流程、工程化程度较高的 MVP。8 阶段 Pipeline 全部有真实实现，横切能力（预算降级、trace artifact、security 脱敏、置信度独立判定、去重、发布）非常完善。但最核心的"LLM 主动调工具深入审查"能力没有做——LLM 仍然是单次 prompt-response，工具系统只有规则引擎在用。

| 维度 | 评分 | 说明 |
|---|---|---|
| 基础设施/横切能力 | 90 分 | 预算四级降级、trace artifact 持久化、输出全字段脱敏、置信度独立判定、评论去重、发布控制，全部落地 |
| 核心审查能力 | 50 分 | 8 阶段全跑通，输出完整，但 LLM 是单次 prompt-response，没有 tool-use 循环，模型不能主动获取上下文 |
| 整体完成度 | 70 分 | 是一个工程化的代码审查脚本，不是有 Agent 能力的代码审查系统 |

**和阿里项目的差距**：不是"代差"，是"核心能力层"的差距。工程化层面你已经做得不错，甚至某些方面更规范；差距集中在 Agent tool-use 循环这一层——阿里的模型能主动调工具逐步深入审查，你的模型只能看一眼 diff 就输出结论。

---

## 二、做得好的地方（10 项）

### 1. DDD 分层清晰

`domain / adapters / services / tools / reporters / app` 六层，职责分明，没有跨层调用。`domain/interfaces/` 里的 Protocol 抽象（`LLMProvider` / `SCMProvider` / `ToolExecutor` / `ReviewRule` / `ReviewTool`）设计到位。

### 2. 8 阶段 Pipeline 全部有真实实现

没有 placeholder。每个阶段都有对应的 `_run_xxx` 方法：
- `INPUT_VALIDATED` → 输入校验
- `SNAPSHOT_CREATED` → 不可变快照
- `ANALYSIS_PREPARED` → diff 分析
- `DETERMINISTIC_CHECKS_DONE` → 规则引擎
- `FINDINGS_GENERATED` → LLM 审查
- `FINDINGS_VERIFIED` → EvidenceValidator + FindingAggregator
- `OUTPUTS_PREPARED` → findings.json + report.md
- `PUBLISH_ATTEMPTED` → PublishController

### 3. 预算四级降级机制

`BudgetManager.plan_llm_call` 实现了预决策 + 四级降级：
- `normal`（12000 chars）：正常审查
- `degraded`（6000 chars）：优先高信号 finding
- `essential_only`（2500 chars）：只关注正确性/安全问题
- `stopped`（0 chars）：跳过 LLM 调用

有 `projected_ratio` / `actual_ratio` 计算，有 `BudgetDecision` 模型，调用前和调用后都会更新降级级别。

### 4. Trace artifact 持久化

`TraceManager.write_artifact` 会把 `llm_prompt` 和 `llm_response` 持久化到独立文件（redacted），`ReviewTrace.artifact_refs` 记录引用。不是只记"阶段完成"的文本日志，而是有完整的 prompt/response 可追溯。

### 5. Security 全链路脱敏

- 输入侧：`build_llm_diff_excerpt` 跳过 .env 文件，`redact_text` 替换 token
- 输出侧：`sanitize_findings` / `sanitize_snapshot` / `sanitize_finding` 对 summary/explanation/suggested_fix/evidence.excerpt 全字段脱敏
- Trace 侧：`append_event` 和 `write_artifact` 都会 `redact_text`

### 6. 置信度独立判定

`EvidenceValidator.validate` 基于 `evidence.verified` 独立判定 confidence：
- 有任意 verified evidence → `Confidence.HIGH`
- 没有 verified evidence → `Confidence.REFERENCE`

不是模型自报，是基于证据类型的独立判定。规则引擎产生的 finding 有 `verified=True` 的 evidence，所以规则命中的 finding 会被标记为 HIGH。

### 7. 评论去重 + 合并

`FindingAggregator.aggregate` 按 `(file, line, summary)` 去重：
- 重复 finding 合并 evidence，保留更强的那个（按 verified_count / total_evidence / confidence / source / severity 排序）
- 不同来源的重复 finding 标记为 `FindingSource.HYBRID`
- evidence 去重（按 source_type/source_id/file/line/excerpt/verified）

### 8. 发布控制 + head SHA 校验

`PublishController.publish`：
- publish 开关控制（配置项）
- 只支持 review_url 输入
- 空 findings 不发布
- **head SHA 校验**：发布前重新获取当前 head SHA，和 snapshot.head_sha 对比，不一致则拒绝发布（防止发布到已变更的 PR）
- 发布前 `sanitize_findings` 脱敏

### 9. Resume 支持全部 8 阶段

`resume()` 方法能从任意阶段恢复，串行 if 链覆盖了 ANALYSIS_PREPARED → DETERMINISTIC_CHECKS_DONE → FINDINGS_GENERATED → FINDINGS_VERIFIED → OUTPUTS_PREPARED → PUBLISH_ATTEMPTED → COMPLETED 的全部路径。

### 10. 错误处理规范

自定义异常体系（`CodeReviewerError` 基类 + `LLMProviderError` / `BudgetExceededError` / `ToolExecutionError` / `PublishError` / `LLMResponseParseError`），每个阶段都有 try/except + `_record_failed_stage`，工具执行失败有 `failure_behavior` 策略。

---

## 三、核心问题（按严重程度排序）

### 🔴 P0-1：LLM 审查是单次 prompt-response，没有 tool-use 循环

**文件**：`services/llm_reviewer.py`（152 行）

当前的 LLM 审查就是：

```
build_prompt(snapshot) → provider.review(prompt) → parse_findings(raw_content)
```

模型**不能主动调工具**，不能 read_file 获取完整文件上下文，不能 read_diff 看具体变更，不能 find_references 查调用关系。它只能看到塞进去的 diff 文本（还被截断到 12000 字符），然后一次性输出 JSON。

**和阿里的差距**：阿里是"模型在循环里反复调工具 → 逐步深入 → 提交评论 → task_done"，当前是"模型看一眼 → 输出结论"。这是"Agent"和"脚本"的本质区别，也是和阿里项目最核心的差距。

**影响**：面试官一看 `llm_reviewer.py` 就知道核心 Agent 能力没做。这是"避重就轻"指控的最大来源。

---

### 🔴 P0-2：工具系统是"死的"

**文件**：`tools/builtin/`（5 个工具）+ `services/tool_engine.py`

有 5 个内置工具：`read_file` / `read_diff` / `list_changed_files` / `find_references`。但这些工具**只有规则引擎在用**，LLM 审查完全不用。

`ToolEngine` 只在 `_run_deterministic_checks` 里实例化，`_run_llm_findings_generated` 里根本没有 ToolEngine。

**影响**：设计了一个很好的工具系统，但它是个"展示品"不是"日用品"。面试官会问"这些工具什么时候被调用？"——答案是"只有规则引擎调了 list_changed_files 和 read_diff"。

---

### 🟡 P1-1：评论没有定位校验

**文件**：`services/llm_reviewer.py` 的 `parse_findings` + `services/evidence_validator.py`

LLM 返回的 `file` / `line` 直接用，`EvidenceValidator` 只检查有没有 evidence，不验证：
- file 是否在 changed_files 里
- line 是否在 diff 的新增行范围内
- line 是否对应实际的代码行（而不是 diff 的上下文行或删除行）

阿里项目有三层定位校验（同文件解析 → 跨文件重定位 → LLM 辅助重定位），当前是零层。

**影响**：可能出现评论指向错误行号的情况，降低评论的可信度和可采纳率。

---

### 🟡 P1-2：LLM adapter 不支持 function calling

**文件**：`adapters/llm/openai_compatible.py`（132 行）

用 `urllib.request` 手写 HTTP 请求，只支持普通 chat completion，不支持：
- `tools` 参数（function calling / tool-use）
- `tool_calls` 响应解析
- 流式输出
- 重试机制

这是实现 Agent 循环的前置障碍——要做 tool-use 循环，必须先扩展这个 adapter。

---

### 🟡 P1-3：规则引擎只有 2 条规则，`print(` 会误报

**文件**：`services/rule_engine.py`

- `SecretLikeFilenameRule`：检测 .env / .pem / .key 等文件名——合理
- `DebugStatementRule`：检测 console.log / pdb.set_trace / debugger / **print**——`print(` 在 Python 脚本/CLI 工具里是正常的，会误报

只有 2 条规则，面试官要求"high 置信度来源指向规则测试"，当前规则数量和质量都撑不起这个要求。

---

### 🟠 P2-1：review_runner 太长（863 行），参数重复

**文件**：`services/review_runner.py`

每个 `_run_xxx` 方法的参数列表几乎一样：

```python
def _run_llm_findings_generated(
    self, *, review_id, input_hash, request, snapshot, trace,
    completed_stages, findings, budget
) -> tuple[list[Finding], BudgetSnapshot]:
```

8-9 个参数，每次调用都传一遍。可以用一个 `ReviewContext` dataclass 封装，减少重复。

`run()` 方法本身有 135 行，resume 有 151 行，都是串行的阶段调用，可以抽象成一个 stage executor。

---

### 🟠 P2-2：没有 README.md

项目根目录没有 README，面试官拿到项目不知道：
- 怎么安装和运行
- 架构是什么
- 支持哪些配置
- 有哪些示例

`pyproject.toml` 只有 471 字节，可能也缺少项目描述和依赖说明。

---

### 🟠 P2-3：Resume 逻辑用串行 if 而非状态机

**文件**：`services/review_runner.py` 的 `resume()` 方法

用串行 `if` 链（不是 `elif`），通过修改 `checkpoint.next_stage` 来驱动下一个 if 命中。逻辑上能跑通，但很脆弱：
- 如果某个阶段执行失败但 next_stage 已经被改了，状态会不一致
- 新增阶段需要在两个地方（run + resume）都加 if 链
- 可读性差，不容易看出阶段流转关系

可以改成基于 `next_stage` 的 dispatch 循环或状态机。

---

### 🟠 P2-4：Security token 模式只有 4 种

**文件**：`services/security.py`

只匹配：
- `ghp_` / `github_pat_`（GitHub token）
- `glpat-`（GitLab token）
- `sk-`（OpenAI key）
- `-----BEGIN PRIVATE KEY-----`（私钥）

不会检测：
- 代码里硬编码的密码（`password = "xxx"`）
- AWS access key（`AKIA` 开头）
- 通用 API key 模式
- JWT token
- 数据库连接字符串

---

## 四、测试和文档

### 测试

- 20 个测试文件，覆盖面广（budget/checkpoint/llm_reviewer/rule_engine/security/trace/cli/resume_flow 等）。
- 没有集成测试（端到端跑一个真实 PR）。
- 没有 LLM mock 测试 tool-use 场景（因为目前没有 tool-use）。

### 文档

- 文档很全（SPEC / ARCHITECTURE / DEV_PLAN / CHECKLIST / AGENTS / mvp_review）。
- 没有 README.md。
- 文档和实现基本一致（8 阶段都有真实实现，不像初版 review 误判的那样有 placeholder）。

---

## 五、问题汇总表

| 级别 | 问题 | 影响 | 修复成本 |
|---|---|---|---|
| 🔴 P0 | LLM 无 tool-use 循环 | 核心 Agent 能力缺失，"避重就轻"最大来源 | 高（6-8h） |
| 🔴 P0 | 工具系统是"死的" | 设计了但 LLM 不用，面试官会质疑 | 低（Agent 循环里接入即可） |
| 🟡 P1 | 评论无定位校验 | 评论可能指向错误行号 | 低（验证 file/line 是否在 diff 新增行） |
| 🟡 P1 | LLM adapter 不支持 function calling | Agent 循环的前置障碍 | 中（扩展 adapter） |
| 🟡 P1 | 规则引擎只有 2 条且 print 误报 | high 置信度来源不足 | 低（加 3-5 条规则，修 print 误报） |
| 🟠 P2 | review_runner 太长参数重复 | 代码可维护性 | 低（重构为 context 对象） |
| 🟠 P2 | 没有 README.md | 面试官上手成本高 | 低（写一个） |
| 🟠 P2 | Resume 串行 if 脆弱 | 边界情况可能状态不一致 | 低（改状态机） |
| 🟠 P2 | Security token 模式少 | 可能漏脱敏 | 低（加几种模式） |

---

## 六、下一步建议（spec2 优先级）

### 核心结论

**不需要推倒重来。** 工程化基础已经很好了，只需要补上最核心的 Agent tool-use 循环，项目就从"工程化的代码审查脚本"升级为"有 Agent 能力的代码审查系统"。

### P0 必做（补上核心 Agent 能力）

#### 1. Agent Runtime（tool-use 循环）

新建 `services/agent_runtime.py`，把 LLM 审查从单次 prompt 改成多轮 tool-use 循环。

- 扩展 `adapters/llm/openai_compatible.py` 支持 function calling（`tools` 参数 + `tool_calls` 响应解析）。
- 定义控制工具 schema：`code_comment`（提交评论）/ `task_done`（完成）。
- 接入现有工具：`read_file` / `read_diff` / `list_changed_files` / `find_references`（工具系统从"死的"变"活的"）。
- 接入预算：每轮检查 + grace round（预算耗尽后最后一轮只允许提交评论）。
- 接入 trace：记录每轮 prompt/response/工具调用（扩展 write_artifact）。

#### 2. 评论定位校验

在 `FINDINGS_VERIFIED` 阶段（或 Agent 循环内）增加定位校验：
- 验证 LLM 返回的 file 是否在 changed_files 里。
- 验证 line 是否在 diff 的新增行范围内。
- 无效定位的 finding 降级为 REFERENCE 或标记为定位失败。

### P1 应做（提升质量和展示效果）

#### 3. Review Filter（评论过滤）

参考阿里，独立 LLM 调用过滤事实错误的评论。实现成本不高，效果显著。

#### 4. 规则引擎扩展

加 3-5 条有价值的规则（TODO/FIXME、大函数、异常吞没等），修 `print(` 误报（只在非脚本文件里检测，或加白名单）。

#### 5. Trace Viewer 静态 HTML

把 trace.json + artifact 渲染成可交互的 HTML 页面，展示每轮 LLM 调用、工具调用、评论产生过程。

#### 6. README.md

项目根目录加 README，写清楚快速开始、架构、配置、示例。

### P2 可选（时间充裕再做）

7. **review_runner 重构**：封装 ReviewContext，减少参数重复。
8. **Resume 状态机改造**：串行 if 改成基于 next_stage 的 dispatch 循环。
9. **Security 增强**：加几种 token 模式（AWS key、JWT、密码硬编码等）。

### 明确非目标（写进 spec2）

避免面试官觉得"什么都想做但什么都没做深"：
- 多 Agent 编排。
- 文件分组 + 并发执行。
- Plan 阶段（大变更先做审查计划）。
- Context compression（多轮 prompt 压缩）。
- 跨文件评论重定位。
- Web UI。

---

## 七、给面试官的叙事

> "v1 我重点做了工程化基础设施——8 阶段 Pipeline、预算四级降级、trace artifact 持久化、全链路 security 脱敏、置信度独立判定、评论去重、发布控制，把'能跑'和'可观测'打牢。v2（spec2）我聚焦核心 Agent 能力，做了 tool-use 循环、评论定位校验和 Trace Viewer，让模型能主动调工具深入审查，把'脚本'升级为'Agent'。"

这个叙事把"核心 Agent 能力 v1 没做"从"缺点"变成了"分阶段迭代的策略"——v1 打工程化基础，v2 补核心 Agent 能力。关键是 v2 要真的把 Agent 循环做出来。

---

## 附录：关键文件索引

| 文件 | 行数 | 状态 | 核心问题 |
|---|---|---|---|
| `services/review_runner.py` | 863 | ✅ 完整实现 | 太长，参数重复，resume 串行 if |
| `services/llm_reviewer.py` | 152 | ⚠️ 核心缺失 | 单次 prompt-response，无 tool-use |
| `services/evidence_validator.py` | 29 | ✅ 完整实现 | 只检查 evidence 存在，不校验定位 |
| `services/finding_aggregator.py` | 99 | ✅ 完整实现 | — |
| `services/budget_manager.py` | 154 | ✅ 完整实现 | 无 per-round（因无多轮循环） |
| `services/trace_manager.py` | 66 | ✅ 完整实现 | 工具调用未记录到 trace |
| `services/security.py` | 107 | ✅ 完整实现 | token 模式只有 4 种 |
| `services/rule_engine.py` | ~220 | ⚠️ 不足 | 只有 2 条规则，print 误报 |
| `services/tool_engine.py` | 72 | ⚠️ 未充分利用 | 只在 deterministic checks 用，LLM 不用 |
| `services/publish_controller.py` | 75 | ✅ 完整实现 | — |
| `adapters/llm/openai_compatible.py` | 132 | ⚠️ 需扩展 | 不支持 function calling |
| `tools/builtin/` | 5 个工具 | ⚠️ 未充分利用 | LLM 不用，只有规则引擎用 |
| `reporters/` | 3 个文件 | ✅ 完整实现 | — |
| `domain/models.py` | ~210 | ✅ 完整 | — |

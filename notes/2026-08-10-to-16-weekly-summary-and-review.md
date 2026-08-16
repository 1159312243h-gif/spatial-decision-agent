# 2026-08-10 至 2026-08-16 周总结与知识抽查

> 项目：建设项目选址与国土空间合规审查 Agent 学习仓库
>
> 结论依据：`progress.md`、本周 Git 提交、自动化测试结果和真实接口运行结果

## 1. 本周总体结论

本周主线从“能原生调用模型 API”推进到“能通过 LangGraph 运行受控的多工具 Agent 最小图”。

核心演进：

```text
原生 Responses API
  -> 上下文滑动窗口
  -> Prompt 与 Pydantic 结构化输出
  -> Function Calling
  -> 安全计算器
  -> 三工具 ToolRegistry
  -> LangGraph State / Node / Edge
  -> 模型、工具、结果回传和结束条件的最小图
```

自动化测试由周初的 12 项增长到 53 项。真实模型已经验证：

- 原生聊天；
- 上下文记忆；
- 选址任务分解；
- 计算器工具调用；
- 日期工具调用；
- 项目类型查询；
- LangGraph 日期工具完整链路。

本周完成的是 Agent 技术底座，不是完整的空间合规业务系统。GIS、政策 RAG、RuleEngine、业务 Skill 和正式报告闭环仍未实现。

## 2. 本周完成项

### 2.1 模型 API 与上下文

- 使用 OpenAI Python SDK 调用公司 Responses 兼容接口；
- 配置从环境变量读取，真实 `.env` 被 Git 忽略；
- `.env.example` 只保留占位符；
- 实现最小聊天函数；
- 实现按完整问答轮数裁剪的 `ConversationContext`；
- 验证模型可以记住滑动窗口中的候选地块编号；
- 完成物流园选址需求的 5 步任务分解。

### 2.2 Prompt 与结构化输出

- 学习 Prompt 模板、Zero-shot、Few-shot 和输出约束；
- 整理 Tokenizer 与 Decode 相关概念；
- 定义 `SiteSelectionRequirement` Pydantic 模型；
- 使用 `extra="forbid"` 拒绝未声明字段；
- 覆盖合法 JSON、非法 JSON、缺字段、错误类型和额外字段五类测试。

### 2.3 Function Calling 与安全工具

- 理解并实现 Function Calling 六步链路；
- 实现不使用 `eval()` 的四则运算工具；
- 使用 JSON Schema 向模型描述工具；
- 使用 Pydantic 在应用侧重新校验参数；
- 实现工具结果回传和最终回答生成；
- 记录工具状态、耗时和错误类型；
- 对未知工具、非法参数、除零和空输入进行安全处理。

### 2.4 ToolRegistry 与多工具路由

- 实现 `ToolDefinition` 与 `ToolRegistry`；
- 统一注册 `calculator`、`current_date`、`project_type_profile`；
- 从参数模型生成 Tool Schema；
- 统一执行、白名单、超时和错误映射；
- 保持原有 `run_tool_calling()` 调用方式兼容；
- 真实模型成功选择日期和物流园项目类型工具。

### 2.5 Transformer 基础

- 整理 Token Embedding、位置编码、Self-Attention、Multi-Head Attention、FFN、残差连接和归一化；
- 理解 Q、K、V 和缩放点积注意力；
- 理解 Attention 负责 Token 间信息交互，FFN 负责逐 Token 特征加工；
- 整理 10 张知识卡、5 条评测题和参考答案。

这里完成的是资料整理和理解记录。8 月 14 日没有完成独立闭卷作答，录音任务已取消，不能写成已完成。

### 2.6 Agent、ReAct 与 LangGraph

- 整理 Agent 的 Perception、Brain、Action，以及 Planning、Memory、Tools；
- 区分 Function Calling、ReAct、ToolRegistry 与 LangGraph；
- 安装并确认 LangGraph `1.2.11`；
- 定义包含消息、待执行调用、工具结果、错误、计数和状态的 `AgentState`；
- 使用 reducer 追加 `messages` 与 `tool_results`；
- 实现 input、model、tool、final 四个节点；
- 实现普通回答、工具请求和循环上限条件路由；
- LangGraph 工具节点复用现有 ToolRegistry；
- 覆盖普通对话、正常工具、未知工具、非法参数和循环上限；
- 全量测试 53 项通过；
- 真实模型通过 LangGraph 完成日期工具调用。

## 3. 本周 Git 记录

本周已推送的主要提交：

| 提交 | 内容 |
|---|---|
| `eff9860` | 原生 LLM API 练习 |
| `5407420` | LLM 与 Prompt 工程文档 |
| `5bf6e29` | 选址需求 Pydantic Schema |
| `9b594f5` | 计算器 Function Calling 循环 |
| `383c03a` | Schema 校验与工具执行记录 |
| `142b7d1` | 多工具 Registry 与路由 |

LangGraph 相关代码和文档当前尚未提交，将在本次复盘结束后统一提交。

## 4. 本周测试增长

| 阶段 | 全量测试结果 |
|---|---:|
| 周初 FastAPI 基线 | 12 passed |
| Function Calling 完成 | 22 passed |
| Schema 与执行记录 | 28 passed |
| ToolRegistry 完成 | 38 passed |
| LangGraph 最小图完成 | 53 passed |

当前保留 1 条 Starlette `TestClient` 依赖弃用 warning，不影响现有测试通过，但后续需要单独处理兼容升级。

## 5. 未完成项

### 5.1 本周计划内但没有完整验收

- 计划中的 ACM 大厂真题没有 AC 记录；
- Hot100/CodeFun 算法题没有完整的独立完成与 AC 记录；
- Transformer、Embedding、Attention 没有完成独立闭卷作答；
- 当前知识卡抽查尚未进行，本文件中的参考答案不等于已抽查；
- 没有形成单独的 5 条以上本周 AI 代码审查记录。

### 5.2 技术主线仍未完成

- `ConversationContext` 没有专门的自动化测试；
- 滑动窗口仍按对话轮数，不按真实 Token 数；
- Pydantic 结构化输出尚未接入真实模型返回文本；
- 尚未实现结构化解析失败后的有限重试；
- FastAPI `/chat` 尚未接入真实聊天函数、ToolRegistry 或 LangGraph；
- 尚未实现 checkpoint、跨请求会话恢复和人工审批；
- 尚未实现持久化工具审计和跨进程取消。

### 5.3 空间合规业务仍未完成

- `ProjectRequest`、`ProjectType`、`ProjectProfile`、`DatasetManifest` 领域合同；
- PlanningIntentAgent；
- ProjectTypeRouter 与 ProfileRegistry；
- ProjectIntakeSkill；
- GeoPandas/PyProj 空间数据验证；
- CRS、字段和几何有效性强制校验节点；
- GIS Tool、政策 RAG 和 RuleEngine；
- 空间合规固定 DAG；
- 项目报告生成和人工复核闭环。

## 6. 本周遇到的三个主要问题

### 问题 1：模型接口兼容性不能凭文档假设

现象：普通 HTTP Responses 请求使用 `previous_response_id` 时返回 400，提示该字段只支持 Responses WebSocket v2。

处理：第二次请求显式带回用户消息、`function_call` 和 `function_call_output`。

经验：兼容 OpenAI 格式不代表支持所有能力。必须用最小真实请求验证当前端点的字段和行为。

### 问题 2：模型生成的工具参数不能直接执行

风险：模型可能返回未知工具、非法 JSON、缺字段、额外字段或错误类型。

处理：使用 ToolRegistry 白名单、JSON 解析和 Pydantic 二次校验；错误转换为安全 Observation。

经验：Tool Schema 是生成提示，不是安全边界。应用程序才是最终执行边界。

### 问题 3：循环、超时和状态必须显式控制

风险：模型可能不断请求工具；线程超时返回后，底层工作可能仍在运行；状态更新不清晰可能重复执行调用。

处理：LangGraph State 保存调用次数和待执行调用，条件路由在执行前检查上限；`pending_tool_calls` 执行后覆盖为空。

经验：Agent 不只是 LLM 加工具，还必须有状态、终止条件、错误处理和可观察记录。

## 7. 下周入口

建议下周不要立刻进入复杂 GIS 分析，先建立选址业务输入合同和固定前置校验。

优先顺序：

1. 定义 `ProjectRequest`、`ProjectType`、`ProjectProfile`、`DatasetManifest`；
2. 使用 Pydantic/枚举拦截非法请求、未知项目类型和缺候选地块；
3. 实现 PlanningIntentAgent、ProjectTypeRouter、ProfileRegistry、ProjectIntakeSkill；
4. 将这些模块接入不含 RAG/GIS 的最小业务图；
5. 再学习 CRS、投影和几何有效性，建立 `spatial/validate.py`；
6. 让缺 CRS、无效几何和缺字段在进入分析节点前失败；
7. 后续再加入 GIS Tool、政策 RAG、RuleEngine 和报告节点。

工程补课可以穿插进行：

- 为 `ConversationContext` 增加测试；
- 处理现有 Starlette warning；
- 修正 LangGraph `input -> model` 固定边对畸形直接调用的边界；
- 设计 checkpoint 和会话隔离；
- 保持算法题与 Agent 主线分时完成。

## 8. 十张闭卷知识卡

使用方法：先只看“正面”，不翻资料，用自己的话回答。每题 0 至 2 分：核心意思正确得 1 分，能说明边界或举例再得 1 分。总分 20 分，达到 16 分视为本轮通过。

### 卡片 1：Token 与上下文窗口

**正面：** Token 是什么？上下文窗口限制的是什么？

**评分点：** 文本处理单位；输入与输出共同占用容量；不是简单字符数。

**参考答案：** Token 是 tokenizer 将文本编码后的基本处理单位，可以是字、词片段、标点或字节片段。上下文窗口限制一次请求中模型能够处理的 Token 总量，通常包括系统指令、历史消息、当前输入、工具消息以及需要生成的输出空间。

### 卡片 2：Prompt 模板与 Few-shot

**正面：** Prompt 模板和 Few-shot 分别解决什么问题？

**评分点：** 稳定规则与动态输入分离；少量标准示例；不能保证正确。

**参考答案：** Prompt 模板固定角色、任务、输入边界、约束和输出协议，并把动态用户内容填入指定位置。Few-shot 在任务说明之外加入少量标准输入输出示例，帮助模型学习字段映射和格式。它们提高稳定性，但不能代替程序校验和真实业务计算。

### 卡片 3：结构化输出的两层校验

**正面：** 为什么模型返回 JSON 后仍要 Pydantic？

**评分点：** JSON 语法与业务字段是两层；模型输出不可信；执行前校验。

**参考答案：** JSON 解析只能证明语法有效，不能证明必填字段存在、类型正确、数值范围合法或没有额外字段。模型输出属于外部不可信输入，因此应用必须使用 Pydantic 做字段级验证，再允许进入业务逻辑。

### 卡片 4：Function Calling 六步

**正面：** 完整 Function Calling 链路是哪六步？

**评分点：** 用户请求、模型选工具、参数校验、程序执行、结果回传、最终回答。

**参考答案：** 用户提出请求；应用把工具描述发给模型；模型返回工具名和 JSON 参数；应用执行白名单和参数校验后调用函数；应用把工具结果作为 `function_call_output` 回传模型；模型依据真实结果生成最终自然语言回答。

### 卡片 5：Tool、Skill 与 Function Calling

**正面：** Tool、Skill、Function Calling 有什么区别？

**评分点：** 动作、业务方法、协议机制三层；不能相互替代。

**参考答案：** Tool 是一个可执行的确定性动作，例如计算日期或空间叠加；Skill 描述一类业务任务如何组合规则、步骤和工具完成；Function Calling 是模型与应用之间结构化传递工具名称和参数的机制。Function Calling 不执行工具，ToolRegistry 也不是 Skill。

### 卡片 6：ToolRegistry 的安全职责

**正面：** ToolRegistry 为什么是执行边界？

**评分点：** 白名单、Schema、Pydantic、执行、超时/错误；模型不能直接调用函数。

**参考答案：** ToolRegistry 保存允许执行的工具定义，向模型提供 Schema，并在应用侧完成工具名白名单、参数解析、Pydantic 校验、调用、超时和错误映射。模型只能提出请求，是否执行以及如何执行由 Registry 决定。

### 卡片 7：Embedding 与 Attention

**正面：** Token Embedding 和 Attention 的职责有什么不同？

**评分点：** 离散 ID 到向量；Token 间信息交互；初始向量不等于上下文语义。

**参考答案：** Token Embedding 将离散 Token ID 映射为连续向量，提供模型可计算的初始表示。Attention 让每个 Token 根据 Q 与其他 Token 的 K 计算相关度，并加权汇总 V，从而融合上下文。上下文化表示是多层 Transformer 处理后的结果，不是初始 Embedding 本身。

### 卡片 8：Agent、Function Calling 与 ReAct

**正面：** 一次 Function Calling 为什么不一定是 Agent？ReAct 增加了什么？

**评分点：** 一次协议交互；目标、状态、循环和终止；Action/Observation。

**参考答案：** Function Calling 只是提出和回传一次工具调用的协议机制，可以调用一次后结束。Agent 围绕目标维护状态，能够规划或路由动作、观察结果并决定继续还是终止。ReAct 强调 Reasoning、Action、Observation 的循环，使模型能依据外部结果更新下一步。

### 卡片 9：LangGraph State、Node、Edge

**正面：** State、Node、Edge 如何组成一张图？

**评分点：** 共享数据、单步处理、执行方向；条件 Edge 依据 State 路由。

**参考答案：** State 是图中共享的数据合同；Node 读取当前 State，完成一个职责并返回增量更新；Edge 定义固定的执行方向，条件 Edge 根据 State 选择下一节点。编译后，从 START 以初始 State 执行，最终进入 END。

### 卡片 10：Reducer 与循环上限

**正面：** 为什么 `messages` 使用 reducer，而 `pending_tool_calls` 不使用？循环上限应何时检查？

**评分点：** 历史追加与当前待办覆盖；避免重复执行；执行前检查副作用。

**参考答案：** `messages` 和 `tool_results` 是历史记录，节点返回的新列表需要通过 `operator.add` 追加到旧值。`pending_tool_calls` 是当前待办，执行后必须覆盖为空，否则会重复调用。循环上限应在工具执行前根据已执行数加本轮待执行数检查，防止超限工具产生副作用。

## 9. 抽查记录

- 当前状态：本次跳过
- 作答情况：未进行闭卷作答
- 总分：未评分
- 错题：未记录
- 是否通过：未验收，不能计入本周完成项

## 10. 周总结验收状态

- [x] 完成项已整理；
- [x] 未完成项已整理；
- [x] 三个主要问题已整理；
- [x] 下周入口已明确；
- [x] 十张知识卡题目、评分点和参考答案已建立；
- [ ] 完成闭卷作答（本次跳过）；
- [ ] 完成评分与错题纠正（本次跳过）；
- [x] 将“本次跳过、未验收”写入本文件和 `progress.md`。

# 2026-08-12 前辈 Prompt 工程资料整理与项目化修订

## 1. 整理目标

这份笔记对前辈资料中的通用 Prompt 模板、结构化输出、Few-shot、CoT、自洽性和其他提示技巧进行整理，并转换为适合“建设项目选址与国土空间合规审查 Agent”的工程规范。

需要先明确三个边界：

- 前辈资料是学习参考，不代表其中所有代码都适用于当前模型和接口。
- 当前项目使用公司模型提供的 **Responses 兼容接口**；资料中的 `chat.completions` 和 `client.beta.chat.completions.parse()` 示例不能直接照抄。
- Prompt 只能引导模型，不能代替 Pydantic 校验、GIS 空间计算、政策数据和确定性规则。

---

## 2. 通用 Prompt 的组成要素

前辈资料提出了引导语、上下文、任务描述、输出格式、限制条件、示例和结束语。结合当前项目，可以整理为八个部分。

### 2.1 角色与任务指令

告诉模型它承担什么职责，以及本次必须完成什么任务。

```text
你是一名建设项目选址需求抽取助手。
请从用户输入中提取项目类型、占地面积、候选地块和审查事项。
```

角色不是越专业、越长越好。关键是定义**职责和边界**，例如：

- 可以抽取用户明确提供的信息。
- 可以标记缺失字段。
- 不得编造坐标、规划版本或审查结果。
- 不得代替主管部门作出法定结论。

### 2.2 背景上下文

提供完成任务所需的背景，而不是把所有资料都塞进 Prompt。

当前项目中可能需要：

- 项目所属地区。
- 项目类型候选集合。
- 候选地块编号。
- 已上传数据的名称和质量状态。
- 当前启用的规则包版本。
- 用户希望得到的输出类型。

背景必须来自可信数据源。模型自己生成的“背景知识”不能自动视为事实。

### 2.3 输入数据

用户数据应该放在清晰的边界符中，使系统规则和待处理文本分开：

```text
<user_requirement>
计划建设一个占地 30 公顷的物流园……
</user_requirement>
```

边界符能帮助模型识别输入范围，但不能从根本上消除 Prompt Injection。程序仍需限制工具权限、校验字段和隔离用户数据。

### 2.4 任务描述

任务要具体、可测试：

```text
提取以下四个字段：
1. project_type
2. land_area_hectares
3. candidate_sites
4. review_items
```

“分析一下选址需求”过于宽泛；“提取四个字段并按 JSON 返回”才容易验收。

### 2.5 要求与约束

约束应描述可观察的行为：

- 只使用用户明确提供的信息。
- 未提供的面积返回 `null`。
- 未提供的候选地块返回空列表。
- 只使用规定字段。
- 不输出 Markdown 代码围栏。
- 不给出合规或不合规的最终结论。

不应迷信“必须”“一定”等强势词汇。文字更强硬不等于模型一定执行；真正的硬约束应由 schema、Pydantic、权限和业务代码实现。

### 2.6 输出格式或输出协议

“请输出 JSON”只是格式指示，更完整的输出协议还应规定：

- 字段名称。
- 字段类型。
- 必填和可选字段。
- 枚举范围。
- 缺失信息的表达方式。
- 是否允许额外字段。
- 失败时如何返回。

### 2.7 示例

示例用于展示字段映射和边界处理。示例必须与 Pydantic 模型完全一致，不能在示例中使用模型实际不接受的字段。

### 2.8 结束标记

结束标记不是每个 Prompt 都必须有。只有在多段输入、连续示例或文本边界不清时才有价值。

例如：

```text
<end_user_requirement>
```

---

## 3. 项目版通用 Prompt 模板

```text
# 角色
你是建设项目选址需求抽取助手。

# 任务
从用户需求中提取以下字段：
- project_type：建设项目类型；
- land_area_hectares：占地面积，单位为公顷；
- candidate_sites：候选地块编号或名称列表；
- review_items：用户要求比较或核查的事项列表。

# 输入
<user_requirement>
{requirement}
</user_requirement>

# 约束
1. 只提取用户明确提供的信息，不得补造缺失数据；
2. 未提供占地面积时，land_area_hectares 返回 null；
3. 未提供候选地块或审查事项时，对应字段返回空列表；
4. 不进行 GIS 面积计算，不作出合规或不合规结论；
5. 只返回一个 JSON 对象；
6. 不使用 Markdown 代码围栏，不输出额外解释；
7. 不增加未定义字段。

# 输出结构
{
  "project_type": "string",
  "land_area_hectares": 0.0,
  "candidate_sites": ["string"],
  "review_items": ["string"]
}
```

注意：输出结构中的数值只是类型示意。真实输出应来自用户信息；没有面积时必须使用 `null`，不能使用 `0` 冒充未知值。

---

## 4. Zero-shot、One-shot 与 Few-shot

### 4.1 Zero-shot

**Zero-shot Prompting，零样本提示**：只提供任务、规则和输出格式，不提供示例。

适合：

- 字段含义清楚。
- 模型已经能够稳定完成任务。
- 希望减少 Token 消耗。

风险：

- 模型可能对枚举映射或缺失值处理理解不一致。

### 4.2 One-shot

**One-shot Prompting，单样本提示**：提供一个完整的输入输出示例。

适合展示最核心的标准格式，但一个例子通常不足以覆盖边界。

### 4.3 Few-shot

**Few-shot Prompting，少样本提示**：提供少量输入输出对，使模型模仿字段、格式和判断边界。

项目示例：

```text
# 示例 1
输入：建设一个占地 20 公顷的商场，候选地块为 C01，比较交通条件。
输出：
{
  "project_type": "shopping_mall",
  "land_area_hectares": 20.0,
  "candidate_sites": ["C01"],
  "review_items": ["交通条件"]
}

# 示例 2
输入：拟建物流园，需要检查生态保护红线，候选地块尚未确定。
输出：
{
  "project_type": "logistics_park",
  "land_area_hectares": null,
  "candidate_sites": [],
  "review_items": ["生态保护红线"]
}
```

第二个示例比第一个更重要，因为它展示了**不编造缺失信息**。

### 4.4 示例设计原则

- 优先覆盖容易犯错的边界，而不是堆重复正常样例。
- 示例输出必须能通过当前 Pydantic 模型。
- 不要在示例中包含未经证实的政策结论。
- 不要在 Prompt 中放 API Key、账号、密码或真实个人隐私。
- 用固定测试集评估 Zero-shot 与 Few-shot 的效果，而不是凭感觉判断。

---

## 5. 结构化输出的三层含义

前辈资料把 Pydantic 解析和“强制 JSON”并列介绍。工程上需要把它们拆成三个层次。

### 5.1 Prompt 要求 JSON

```text
只返回 JSON，不要输出解释。
```

这是最弱的一层。模型仍可能返回代码围栏、单引号、额外文字或错误类型。

### 5.2 JSON 模式

某些模型接口提供 JSON mode，目标是让返回内容成为可解析 JSON。

但要注意：

> 合法 JSON 不等于符合业务 schema。

模型仍可能漏字段、增加字段或返回错误类型。

### 5.3 Schema 约束与 Pydantic 校验

更强的接口可以根据 schema 约束输出；程序端仍应使用 Pydantic 建立最终边界。

当前项目模型骨架：

```python
class SiteSelectionRequirement(BaseModel):
    project_type: NonEmptyString
    land_area_hectares: float | None
    candidate_sites: list[NonEmptyString]
    review_items: list[NonEmptyString]
```

Pydantic 可以检查：

- 必填字段是否存在。
- 面积是否为数字并且大于 0。
- 候选地块是否为列表。
- 列表中的字符串是否为空。
- 是否出现未声明的额外字段。

### 5.4 当前接口不能直接照抄前辈代码

前辈资料使用：

```python
client.beta.chat.completions.parse(...)
```

当前项目使用：

```python
client.responses.create(...)
```

两者的请求参数、响应字段和结构化输出能力不能混用。公司 Responses 兼容接口是否支持原生 schema 约束，需要单独验证。在确认前，采用稳妥流程：

```text
Prompt 要求 JSON
→ 读取 response.output_text
→ JSON/Pydantic 解析
→ 成功后进入业务逻辑
→ 失败则明确报错或有限重试
```

---

## 6. 非法 JSON 与失败边界

### 6.1 非法 JSON

常见情况：

- 使用单引号。
- 属性名没有双引号。
- 结尾多逗号。
- JSON 前后出现解释文字。
- 使用 Markdown 代码围栏。
- 输出被截断。

### 6.2 合法 JSON 但 schema 不合法

```json
{
  "project_type": "logistics_park",
  "land_area_hectares": -30,
  "candidate_sites": "A01",
  "review_items": []
}
```

它可能是合法 JSON，但面积为负数，`candidate_sites` 也不是列表，因此必须被 Pydantic 拒绝。

### 6.3 处理原则

- 禁止使用 `eval()` 解析模型输出。
- 不用大量字符串替换静默修补错误。
- 不把未校验的数据传给 GIS、数据库或规则引擎。
- 解析失败应返回可理解的错误类型。
- 重试必须限制次数，并说明需要重新按 schema 输出。
- 日志只记录必要错误摘要，不记录 API Key 和敏感原文。

---

## 7. CoT：Chain-of-Thought

### 7.1 全称与中文名

- **CoT**：Chain-of-Thought，**思维链**。
- **Zero-shot CoT**：零样本思维链提示。
- **Auto-CoT**：Automatic Chain-of-Thought，自动思维链示例构建方法。

### 7.2 前辈资料中的思想

资料建议通过“逐步思考”或提供带推理步骤的示例，引导模型处理多步问题；Auto-CoT 则通过聚类和代表性采样构造多样的推理演示。

### 7.3 项目化修订

当前合规 Agent 不应要求模型输出完整、自由展开的内部思考过程，也不应把“思考过程”作为 JSON 必填字段。

更适合输出的是可审计的**简洁依据**：

- `missing_fields`：缺少哪些数据。
- `evidence_refs`：引用了哪些政策页码或数据版本。
- `checks_performed`：执行了哪些工具检查。
- `decision_summary`：面向用户的简短说明。

这些是可验证的业务证据，不是模型隐藏推理的逐字展开。

推荐写法：

```text
请先在内部检查字段是否完整，最终只返回约定 JSON。
在 decision_summary 中用 1-2 句话说明结论依据，
不要输出详细思维过程。
```

---

## 8. Self-Consistency：自洽性

### 8.1 含义

**Self-Consistency，自洽性方法**：对同一问题生成多个候选推理或答案，再通过投票或一致性规则选择结果。

### 8.2 优点

- 可以降低单次随机生成造成的偶然错误。
- 对存在明确答案的推理题可能有效。

### 8.3 当前项目的限制

- 多次调用会增加延迟和 Token 成本。
- 多个模型回答一致，不代表事实正确。
- 如果多个回答基于同一个错误政策或错误空间数据，一致性也无法纠错。
- 合规结果不能采用简单多数投票代替规则引擎。

在当前项目中，自洽性可以用于低风险的任务拆分或解释生成实验，不应用于决定控制线是否相交、面积是多少或最终是否合规。

---

## 9. Generated Knowledge 与 RAG

### 9.1 Generated Knowledge Prompting

生成知识提示通常先让模型生成与问题有关的知识，再把这些内容加入后续 Prompt。

风险是：模型生成的知识仍可能是幻觉，不能自动成为可信外部知识。

### 9.2 RAG

- **RAG**：Retrieval-Augmented Generation，**检索增强生成**。
- 它从外部知识库检索相关文档片段，再把片段交给模型生成回答。

对于当前项目，政策知识应优先来自可追溯资料：

- 文件名称。
- 发布机关。
- 生效时间。
- 适用地区。
- 页码或条款。
- 数据或规则版本。

LLM 负责摘要和解释，不能把自己生成的政策内容当作检索证据。

---

## 10. 其他提示技巧的修订

### 10.1 具体、简洁、可测试

不推荐：

```text
分析这个建设项目。
```

推荐：

```text
从用户输入中提取四个字段，并只返回符合约定结构的 JSON。
```

### 10.2 必要时给步骤，但不设机械上限

“一般任务不要超过 3 个步骤”不是通用定律。应该根据职责边界、可测试性和失败恢复拆分任务。

当前项目可以拆成：

```text
需求抽取
→ 数据检查
→ GIS 叠加
→ 规则判定
→ 候选地比较
→ 报告生成
```

每一步由独立合同约束，比把所有工作塞进一个超长 Prompt 更可靠。

### 10.3 正向指令与禁止项结合

正向指令通常更清晰：

```text
缺少候选地块时返回空列表。
```

但安全边界仍应明确写禁止项：

```text
不得编造坐标；不得代替法定审批；不得调用未授权工具。
```

因此不是“永远不要说不要”，而是优先写清期望行为，同时保留必要禁止规则。

### 10.4 使用清晰分区

可以使用 Markdown 标题、XML 风格标签或其他稳定边界：

```text
# 角色
# 任务
# 输入
# 约束
# 输出结构
```

符号本身不是关键，关键是结构一致、输入边界明确。

### 10.5 反馈优化必须转为评测

不要只修改 Prompt 后人工看一次结果。应收集：

- 正常样例。
- 字段缺失样例。
- 歧义项目类型样例。
- 多候选地样例。
- Prompt Injection 样例。
- 非法 JSON 和错误类型样例。

每次修改 Prompt 后运行同一套测试，比较解析成功率、字段准确率、拒绝编造率和失败类型。

---

## 11. 前辈资料中不能直接沿用的内容

### 11.1 明文 API Key

示例代码包含明文密钥。密钥必须通过环境变量读取，不能复制到代码、笔记、`.env.example`、日志或 Git 历史中。

### 11.2 用户资料模型中的敏感字段

示例 `UserProfile` 包含 `password`、验证码和个人联系方式。真实项目不应让 LLM 提取或回显明文密码、验证码等认证信息。

### 11.3 为兼容而全部使用字符串

“UUID、日期和枚举全部使用字符串”不是普遍最佳实践。应按业务合同选择准确类型；只有在特定模型或 schema 功能确实不支持时，才做兼容性降级，并在程序端再次校验。

### 11.4 输出“思考过程”

不把完整思维链作为用户输出或审计证据。项目需要的是数据来源、执行步骤、工具回执、规则编号和简洁结论依据。

### 11.5 JSON 模式等于 schema 校验

JSON 模式最多保证或促进 JSON 语法，不能自动保证字段符合 Pydantic 模型。

### 11.6 接口代码跨端点复制

Chat Completions、Responses API、第三方兼容接口的参数和返回结构可能不同。必须以当前端点实际行为为准。

---

## 12. 与当前 Pydantic 骨架对齐的 Few-shot 模板

```python
REQUIREMENT_EXTRACTION_PROMPT = """
# 角色
你是建设项目选址需求抽取助手。

# 任务
从用户需求中提取 project_type、land_area_hectares、
candidate_sites 和 review_items。

# 示例 1
<example_input>
建设一个占地 20 公顷的商场，候选地块为 C01，比较交通条件。
</example_input>
<example_output>
{{
  "project_type": "shopping_mall",
  "land_area_hectares": 20.0,
  "candidate_sites": ["C01"],
  "review_items": ["交通条件"]
}}
</example_output>

# 示例 2
<example_input>
拟建物流园，需要检查生态保护红线，候选地块尚未确定。
</example_input>
<example_output>
{{
  "project_type": "logistics_park",
  "land_area_hectares": null,
  "candidate_sites": [],
  "review_items": ["生态保护红线"]
}}
</example_output>

# 当前输入
<user_requirement>
{requirement}
</user_requirement>

# 约束
1. 只提取当前输入明确提供的信息；
2. 不得编造坐标、面积、政策版本或合规结论；
3. 只返回一个 JSON 对象；
4. 不输出 Markdown 围栏或额外解释；
5. 不增加未定义字段。
"""
```

Python `str.format()` 会把单层 `{}` 当作变量占位符，因此示例 JSON 使用 `{{` 和 `}}` 转义。最终发给模型时仍会显示为普通花括号。

---

## 13. 明天的实现顺序

1. 将 Prompt 模板放入独立模块，避免散落在业务函数中。
2. 编写纯函数 `build_requirement_prompt(requirement)`。
3. 调用现有 `chat()` 获取模型文本。
4. 使用 `SiteSelectionRequirement.model_validate_json()` 解析。
5. 分别捕获非法 JSON 和 Pydantic 字段校验错误。
6. 先写离线测试，不调用真实 API。
7. 测试通过后，再用一条非敏感真实请求验证公司接口。
8. 不接 Function Call、GIS 工具或 FastAPI `/chat`，避免扩大当天范围。

---

## 14. 最低验收总结

- **Prompt 模板**：固定角色、任务、上下文、约束和输出协议，只替换动态输入。
- **Zero-shot**：没有示例；**Few-shot**：提供少量标准输入输出对。
- **结构化输出**：不仅要像 JSON，还必须通过 JSON 解析和 Pydantic 校验。
- **非法 JSON**：语法无法解析；**校验失败**：JSON 合法但字段或类型不符合 schema。
- **CoT**：可以引导复杂推理，但当前项目不输出完整内部思维链，只输出可验证依据。
- **自洽性**：多次生成的一致答案不等于事实正确，不能替代 GIS 与规则引擎。
- **RAG**：检索可追溯外部资料；模型自行生成的知识不能自动当作证据。
- **密钥安全**：所有示例都必须使用环境变量和占位符，禁止明文密钥进入代码和 Git。

## 15. 参考资料

前辈资料中列出的论文与延伸阅读：

- Few-shot：https://arxiv.org/pdf/2302.13971
- Few-shot：https://arxiv.org/pdf/2109.01652
- Chain-of-Thought：https://arxiv.org/pdf/2201.11903
- Self-Consistency：https://arxiv.org/pdf/2203.11171
- Prompting Guide：https://www.promptingguide.ai/zh

本次尝试访问 OpenAI Docs 的 Prompt Engineering 页面时返回 403，因此没有据此确认当前公司接口的具体结构化输出参数。接口能力仍应以公司端点的实际测试结果为准。

# 版本化 RuleEngine 与政策证据

> 项目：建设项目选址与国土空间合规审查 Agent

## 一、为什么需要 RuleEngine

空间分析只能产生事实，例如：

```text
候选地块 A01 与生态保护空间图层相交 1 个要素。
```

这条事实不能自动变成：

```text
候选地块 A01 不合规。
```

从空间事实到政策结论，还需要明确回答：

- 依据的是哪份政策、哪个版本和哪一条款。
- 规则适用于哪个行政区、项目类型和时间范围。
- 哪个空间观察触发了规则。
- 规则命中后的结论等级是什么。
- 数据和规则更新后，旧结果能否复现。

因此系统在 GIS 层与最终结果之间增加确定性 RuleEngine：

```text
ConstraintObservation
-> RuleDefinition
-> RuleEngine
-> PolicyFinding
-> PolicyEvidence
```

LLM 可以解释已经生成的结构化证据，但不能代替 RuleEngine 判断规则是否命中，也不能自行补造法规依据。

## 二、核心契约

### 2.1 PolicyReference

`PolicyReference` 保存规则引用的政策来源：

- `policy_id`：系统中的稳定政策标识。
- `title`：政策文件标题。
- `issuing_authority`：发布机关。
- `document_number`：文号，可为空。
- `clause`：具体条款。
- `version`：政策版本。
- `jurisdiction`：适用行政区。
- `source_uri`：来源地址或内部档案标识。

规则不能只保存一段结论文字。没有来源、条款和版本，就无法审查结论，也无法在政策更新后重放历史任务。

### 2.2 RuleDefinition

`RuleDefinition` 是版本化、可执行的确定性规则，主要字段包括：

- `rule_id`：跨版本稳定的规则标识。
- `version`：规则实现版本。
- `applicable_project_types`：适用项目类型白名单。
- `constraint_id`：需要读取的空间观察标识。
- `expected_triggered`：规则期望的观察布尔值。
- `outcome`：规则命中后的结论等级。
- `message`：规则命中后的人工可读说明。
- `policy`：完整政策来源。
- `valid_from/valid_to`：规则有效日期范围。
- `enabled`：是否启用。

规则按 `ProjectRequest.requested_at` 的日期选择版本。同一个 `rule_id` 在同一天最多只能有一个有效版本；如果多个版本的有效期重叠，引擎会拒绝执行，避免因为列表顺序不同而得到不同结果。

### 2.3 RuleOutcome

当前结论等级包括：

- `notice`：提示事项。
- `review_required`：需要人工或主管部门复核。
- `restricted`：存在限制条件。
- `prohibited`：规则明确映射为禁止情形。

枚举中没有自动 `approved` 或 `compliant`。未命中某一条限制规则，只能说明该规则条件没有命中，不能证明项目整体合规。

### 2.4 PolicyFinding

`PolicyFinding` 只记录已经命中的规则，并保存完整血缘：

- 地块标识。
- 规则标识与规则版本。
- 约束观察标识及实际值、期望值。
- 结论等级和说明。
- 政策标识、标题、版本、条款、发布机关和行政区。
- 来源 URI。
- 观察数据集标识、数据版本和分析 CRS。

模型会校验实际观察值必须等于规则期望值，防止把未命中的规则错误包装成 `PolicyFinding`。

### 2.5 PolicyEvidence

为了兼容已有接口，`PolicyEvidence` 保留：

- `policy_ids`
- `findings: list[str]`
- `notes`

同时新增：

- `evaluated_rule_ids`：采用 `rule_id@version` 记录实际评估的规则版本。
- `rule_findings`：结构化规则命中列表。

字符串 `findings` 便于展示，`rule_findings` 用于审计、API 输出和后续生成最终结果。模型还会校验政策标识、规则版本和候选地块引用的一致性。

## 三、规则执行流程

`evaluate_policy_rules()` 的执行步骤如下：

1. 读取项目类型和请求日期。
2. 过滤未启用、不适用或不在有效期内的规则。
3. 检查同一 `rule_id` 是否存在多个同时有效版本。
4. 为每个候选地块取得 `GISEvidence.READY` 证据。
5. 按 `constraint_id` 索引空间观察并检查重复项。
6. 检查每条有效规则所需的观察是否完整。
7. 比较 `observation.triggered` 与 `rule.expected_triggered`。
8. 为命中规则生成结构化 `PolicyFinding`。
9. 为地块生成新的 `PolicyEvidence` 并回写新的 `AgentState`。

引擎不修改输入状态。重复运行会替换地块原有的政策证据，不会不断追加重复结果。

## 四、阻断策略

以下情况抛出 `RuleEvaluationBlockedError`：

- 没有适用于当前项目类型和请求日期的有效规则。
- 某候选地块没有 GIS 证据。
- GIS 证据状态为 `MISSING` 或 `INVALID`。
- 有效规则引用的 `ConstraintObservation` 缺失。
- 同一地块存在重复 GIS 证据或重复约束观察。

以下规则配置问题抛出 `RuleConfigurationError`：

- 同一个 `rule_id` 在请求日期存在多个有效版本。

Pydantic 会在执行前拒绝：

- 空规则标识、版本、政策来源或条款。
- 未知项目类型或未知结论等级。
- 重复的适用项目类型。
- `valid_to` 早于 `valid_from`。
- 契约之外的多余字段。

这些阻断条件的共同目标是：信息不足时停止，不生成看似完整但无法证明的政策结论。

## 五、未命中规则的语义

当所有适用规则都完成评估但没有命中时：

- `PolicyEvidence.status` 为 `READY`，表示规则计算已经完成。
- `evaluated_rule_ids` 保留实际评估范围。
- `rule_findings` 和 `findings` 为空。
- `notes` 明确记录“未命中规则不等于整体合规”。

`READY` 表示证据处理完成，不表示项目合规。最终合规结论还取决于规则覆盖范围、数据完整性、行政区配置以及是否需要人工审查。

## 六、当前实现与真实业务规则的边界

当前测试使用 `POLICY-DEMO-001` 等合成政策和规则，只验证规则引擎机制，不代表任何真实法规内容。

录入真实规则前必须完成：

- 确认权威政策来源和现行有效版本。
- 明确适用行政区和项目类型。
- 由规划或法律专业人员复核条款到机器条件的映射。
- 建立规则变更审批、版本发布和历史追溯流程。
- 用已人工判定的真实案例建立回归测试集。

不能把示例规则、模型常识或网络摘要直接发布为生产合规规则。

## 七、测试验收

新增 15 项测试，覆盖：

- 规则日期范围和项目类型校验。
- 未知结论等级拦截。
- 命中规则生成完整证据血缘。
- 未命中规则不输出合规结论。
- 显式匹配 `triggered=False` 的规则。
- 项目类型和请求日期过滤。
- 无适用规则、缺少观察和 GIS 未就绪时阻断。
- 重叠有效版本拦截。
- 根据请求日期选择唯一规则版本。
- 重复运行不累积结果。
- 输入状态保持不变。

RuleEngine 定向组合测试为 `42 passed`，项目全量测试为 `147 passed, 1 existing warning`。现有 warning 来自 FastAPI 测试依赖的 Starlette/httpx 兼容性提示，与 RuleEngine 无关。

## 八、下一步

下一阶段不应立刻批量录入真实法规，而应先完成一个端到端最小业务图：

```text
ProjectIntakeSkill
-> POI 查询
-> GIS 数据校验
-> GIS 指标
-> 空间约束观察
-> RuleEngine
-> AnalysisResult
```

在该图中，硬约束政策证据与 POI 软评分必须保持分离，最终输出同时展示数据版本、规则版本、警告和待人工复核事项。

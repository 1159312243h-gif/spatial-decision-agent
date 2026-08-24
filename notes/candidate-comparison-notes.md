# 多候选地块软评分对比与政策风险并列展示

>
> 项目：建设项目选址与国土空间合规审查 Agent

## 一、本阶段目标

此前端到端工作流已经能够为每个候选地块生成：

```text
GIS 证据 + POI 评分报告 + 政策证据 + 单地块 AnalysisResult
```

本阶段增加多候选地块对比报告：

```text
list[AnalysisResult]
-> compare_candidate_results()
-> CandidateComparisonReport
```

对比报告解决的是“各候选地块的 POI 软评分如何横向查看”，不是“哪个地块已经合规”或“系统自动推荐哪个地块”。

## 二、为什么单独建立对比报告

没有把名次直接写入 `AnalysisResult`，原因是：

- `AnalysisResult` 表示一个地块自身的证据与结果。
- 名次是多个地块之间的相对关系。
- 同一个地块放入不同候选集合时，名次可能变化。
- 单地块结果可以独立存储和复核，对比报告则属于请求级输出。

因此状态中新增：

```python
comparison_report: CandidateComparisonReport | None
```

这使单地块证据和跨地块比较保持清晰边界。

## 三、对比契约

### CandidateComparisonItem

每个候选地块对比项包含：

- `parcel_id`：候选地块标识。
- `soft_rank`：POI 软评分名次。
- `soft_score`：进入排序的软评分。
- `is_tied`：是否与其他地块完全同分。
- `policy_outcomes`：该地块已有政策规则命中等级。

`policy_outcomes` 只用于提醒调用方查看硬约束证据，不参与软评分排序。

### CandidateComparisonReport

请求级报告包含：

- `request_id`：来源请求。
- `project_type`：项目类型。
- `scoring_version`：本次比较使用的唯一 POI 评分版本。
- `ranking_basis`：固定为 `poi_soft_score_desc`。
- `candidates`：已经排序的候选地块列表。
- `notes`：排序边界和政策证据说明。

## 四、排名规则

### 降序排列

排名只使用：

```text
AnalysisResult.overall_soft_score
```

分数越高，软评分名次越靠前。

### 并列名次

使用标准竞赛排名：

```text
90, 90, 80
-> 1, 1, 3
```

完全同分时，按 `parcel_id` 升序稳定排列，保证相同输入得到相同输出。

### 为什么不使用浮点近似并列

本阶段只有总分完全相等时才视为并列，没有在排名层暗中执行四舍五入或误差合并。

如果未来业务规定总分保留两位小数，应把舍入方法写入版本化评分规则，使历史结果可以复现，而不是由比较模块自行猜测精度。

## 五、评分版本一致性

同一份对比报告中的所有候选地块必须使用同一个 `scoring_version`。

如果混用版本，例如：

```text
A01 -> mall-2026.1
A02 -> mall-2026.2
```

即使两者都显示为 80 分，也不能直接比较，因为归一化区间、指标权重或缺失策略可能不同。

因此发现多个评分版本时抛出 `CandidateComparisonBlockedError`。

## 六、评分血缘完整性

候选地块进入对比前必须同时具备：

- 非空的 `overall_soft_score`。
- 非空的 `POIEvidence.score_report`。
- 与请求项目类型一致的评分报告。
- 覆盖请求中全部候选地块的唯一 `AnalysisResult`。

此外，`AnalysisResult` 新增一致性校验：

```text
AnalysisResult.overall_soft_score
== POIEvidence.soft_score
== POIScoreReport.total_score
```

任何一层总分被单独改写都会在 Pydantic 校验阶段被拒绝。

## 七、政策结果与软排名的边界

比较项会携带该地块的 `policy_outcomes`，并按风险等级展示，但排名公式完全不读取这些等级。

这意味着可能出现：

```text
软评分第 1 名 + policy_outcomes=[prohibited]
```

这个结果不是矛盾：软分只说明 POI 条件较优，`prohibited` 则提示存在政策规则命中。业务调用方必须优先处理政策证据，不能把软评分第一名直接解释为推荐地块。

测试明确保留了“高软分且命中 prohibited 仍处于软分第一”的场景，用来防止后续开发者误以为本报告已经做了综合决策。

## 八、AgentState 一致性

当 `comparison_report` 存在时，状态校验要求：

- 报告 `request_id` 与请求一致。
- 报告 `project_type` 与请求一致。
- 报告地块集合与请求候选地块完全一致。
- 报告地块集合与 `results` 完全一致。
- 不允许只有报告而没有单地块结果。

重新组装单地块结果时会先清空旧对比报告，避免结果变化后继续携带过期排名。

## 九、LangGraph 接入

工作流末端由：

```text
policy_rules -> results -> END
```

更新为：

```text
policy_rules -> results -> comparison -> END
```

`comparison` 节点复用独立的 `compare_candidate_results()`，工作流本身只负责依赖顺序和失败路由。

发生以下问题时会进入：

```text
comparison -> failed -> END
```

包括：

- 结果尚未组装完成。
- 请求地块结果缺失或多出。
- 同一地块结果重复。
- 缺少软评分。
- 缺少评分报告。
- 评分项目类型不一致。
- 混用评分版本。

失败节点会清空 `results` 和 `comparison_report`，但保留错误说明及前序证据，避免调用方把部分输出当作完成结果。

## 十、不可变状态

比较服务通过 `model_dump()` 构建新状态，再由 `AgentState.model_validate()` 完整校验。

输入状态不会被原地写入，测试会比较调用前后的完整状态数据。

## 十一、测试覆盖

新增候选地块对比测试，覆盖：

- 按软评分降序排名。
- 标准竞赛并列名次。
- 同分地块稳定排序。
- 政策等级展示但不改变软排名。
- 输入状态不可变。
- 缺少软评分时阻断。
- 缺少评分报告时阻断。
- 混用评分版本时阻断。
- 重复地块结果时阻断。
- 缺少候选地块结果时阻断。
- 报告拒绝重复地块。
- 报告拒绝错误名次。
- 单地块结果与 POI 证据总分不一致时阻断。
- 端到端工作流生成单候选地块对比报告。

验证结果：

```text
定向测试：23 passed
全量测试：198 passed, 1 existing warning
```

现有 warning 来自 FastAPI TestClient 与 Starlette/httpx 的第三方弃用提示，与本阶段改动无关。

## 十二、当前边界与下一步

当前对比报告是可解释的软评分横向视图，不是综合推荐引擎。

下一步应把已完成的业务工作流接入应用服务/API 边界，重点包括：

1. 定义分析请求和结果响应 DTO。
2. 为评分配置、空间 Gateway、约束配置和规则建立依赖提供器。
3. 增加请求级错误映射，区分输入错误、证据阻断和服务器异常。
4. API 返回完整评分版本、政策证据和对比报告。
5. 在真实评分配置和政策规则审核完成前，不开放自动推荐或合规结论字段。

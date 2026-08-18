# POI 软评分状态服务与 LangGraph 接入

> 日期：2026-08-18
>
> 项目：建设项目选址与国土空间合规审查 Agent

## 一、本阶段目标

上一阶段已经实现版本化 POI 评分契约和纯函数：

```text
ProjectProfile + POIScoringConfig + POIFeatureSet
-> score_poi_feature_sets()
-> POIScoreReport
```

本阶段把该纯评分能力接入业务状态和端到端 LangGraph：

```text
POIFeatureSet
-> score_poi_state()
-> POIEvidence.soft_score
-> POIEvidence.score_report
-> AnalysisResult.overall_soft_score
```

## 二、工作流位置

接入后的业务图顺序为：

```text
POI 查询
-> POI 评分
-> GIS 数据收集
-> GIS 指标计算
-> 空间约束观察
-> 政策规则评估
-> 结果组装
```

对应 LangGraph 节点：

```text
poi
-> poi_scoring
-> gis_collection
-> gis_metrics
-> spatial_constraints
-> policy_rules
-> results
```

评分节点放在 POI 查询之后，因为评分必须消费已经归一化的 `POIFeatureSet`；放在 GIS 之前，可以在 POI 数据不完整或评分配置错误时尽早失败，避免继续执行成本更高的空间分析。

## 三、POIEvidence 的评分血缘

`POIEvidence` 新增字段：

```python
score_report: POIScoreReport | None = None
```

其中两个字段职责不同：

- `soft_score`：供结果汇总、排序和 API 消费的便捷总分。
- `score_report`：保存评分版本、分组分数、指标原始值、归一化结果、权重和数据源。

只保留 `soft_score` 无法解释分数来源；只保留报告则会让常用的结果读取变得繁琐。因此两个字段同时保留，但必须由模型校验保证一致。

### 一致性约束

`POIEvidence` 会校验：

1. 所有 `feature_sets` 必须属于当前 `parcel_id`。
2. `score_report.parcel_id` 必须与证据地块一致。
3. 存在评分报告时，`soft_score` 不能为 `None`。
4. `soft_score` 必须等于 `score_report.total_score`。

这些约束阻止调用方手工修改总分，却保留一份与总分不一致的评分明细。

为了兼容尚未执行评分的中间状态，`score_report=None` 时允许 `soft_score=None`。结果组装测试还保留了显式外部分数场景，但会先清除评分报告，避免伪造报告血缘。

## 四、score_poi_state 状态服务

`score_poi_state(state, config)` 是纯评分函数和 LangGraph 节点之间的业务服务层。

它负责：

- 检查评分配置项目类型与请求类型一致。
- 按 `parcel_id` 建立 POI 证据索引。
- 拒绝同一地块的重复 POI 证据。
- 要求每个候选地块都有且只有一份 `READY` POI 证据。
- 对每个候选地块调用 `score_poi_feature_sets()`。
- 同时写入 `soft_score` 和完整的 `score_report`。
- 通过 `AgentState.model_validate()` 重新验证输出状态。

### 为什么不直接在工作流节点中评分

工作流只负责节点编排和错误路由。评分输入检查、逐地块处理与状态写回封装在独立服务后，可以直接做单元测试，也可以在未来的 API、批处理或其他图中复用。

### 不修改输入状态

状态服务使用 `model_dump()` 生成新数据，再构造新的 `AgentState`。原输入对象及其中的 `POIEvidence` 不会被原地修改。

这有三个好处：

- 节点行为更容易测试和复现。
- 失败时不会留下半写入状态。
- 避免多个节点共享对象引用造成隐式副作用。

## 五、工作流依赖注入

`SiteSelectionWorkflowDependencies` 新增必填依赖：

```python
poi_scoring_config: POIScoringConfig
```

评分配置不使用模块级默认值，原因是：

- 不同项目类型的指标和分组不同。
- 归一化阈值必须经过业务校准。
- 配置必须有明确版本，才能复现历史结果。
- 测试、开发和生产配置不能被静默混用。

当前测试中的 `demo-1.0`、`demo-state-1.0` 及 `0-100` 上下界都只是合成配置，用于验证机制，不代表商场或物流园的真实评价标准。

## 六、错误路由

`POIScoringError` 已加入工作流可预期错误列表。

发生下列问题时，`poi_scoring` 节点会进入 `FAILED`：

- 缺少候选地块 POI 证据。
- POI 证据不是 `READY`。
- 同一地块存在重复 POI 证据。
- 配置项目类型不匹配。
- Profile、配置和 FeatureSet 分组不一致。
- 默认 `block` 策略下缺少评分指标。
- 评分报告地块与目标地块不一致。

失败后条件边路由到：

```text
poi_scoring -> failed -> END
```

不会继续生成 GIS 证据、政策证据或最终结果。这可以防止下游使用一份不完整的业务状态。

## 七、缺失指标策略在工作流中的表现

评分契约支持：

- `block`：缺少指标时失败。
- `zero`：明确把缺失指标记为 0 分，并在报告中保留 `raw_value=None`。

Mock Gateway 在没有匹配 POI 时仍能计算数量和密度，但不能计算最近距离与平均距离。因此工作流正常路径测试显式使用 `zero`，失败路径测试显式使用 `block`。

这只是为了覆盖两种机制。生产配置必须先区分“确实没有设施”和“数据供应商未返回指标”，不能直接照搬测试策略。

## 八、软评分与硬约束的边界

POI 评分只表达便利性和适宜性偏好：

```text
POIEvidence.soft_score
```

空间约束和政策规则证据继续保存在：

```text
GISEvidence.constraint_observations
PolicyEvidence.rule_findings
```

即使软评分很高，政策规则命中也不会被删除、降级或抵消。工作流测试同时断言软评分已生成且政策规则命中仍然存在。

`AnalysisStatus.COMPLETED` 仍然只表示所有节点执行完成，不表示项目合规。当前 `AnalysisResult.conclusion` 继续保持为空，等待经过确认的结论规则。

## 九、测试覆盖

新增 `test_poi_scoring_service.py`，覆盖：

- 写入评分报告和总分。
- 记录评分配置版本。
- 不修改输入状态。
- 缺少 POI 证据时阻断。
- 非 `READY` 证据时阻断。
- 重复地块证据时阻断。
- 报告与总分不一致时由 Pydantic 拒绝。
- `block` 策略拒绝缺失指标。

工作流测试新增或更新：

- 正常路径生成 `soft_score` 和 `score_report`。
- 结果保留 `scoring_version`。
- 不再产生“未生成软评分”警告。
- 评分失败后不执行 GIS 和政策节点。
- 软评分存在时，硬约束政策证据仍完整保留。

验证结果：

```text
定向测试：38 passed
全量测试：186 passed, 1 existing warning
```

现有 warning 来自 FastAPI TestClient 与 Starlette/httpx 的第三方弃用提示，与本阶段改动无关。

## 十、下一步

当前系统已经具备从 POI 查询到可审计软评分的完整技术链路，但仍没有真实业务评分参数。

合理的下一步是：

1. 分别建立商场与物流园的评分配置文件。
2. 为每个指标记录阈值来源、样本范围、适用行政区和版本。
3. 使用历史项目或专家样本校准上下界与权重。
4. 增加多候选地块排序，但排序结果不得替代政策判断。
5. 将真实配置纳入发布、复核和历史版本追溯流程。

在完成业务校准前，测试配置只能用于机制演示，不能用于真实选址建议。

# 版本化 POI 软评分契约与归一化

> 项目：建设项目选址与国土空间合规审查 Agent

## 一、评分层的定位

POI 评分用于表达选址便利性、交通条件、配套程度等软偏好，不是国土空间合规结论。

```text
POI 原始指标
-> 版本化归一化规则
-> 分组得分
-> Profile 权重汇总
-> POI 总分
```

POI 总分不能抵消生态保护、耕地保护或开发边界等硬约束命中。硬约束始终保存在 `PolicyEvidence`，软评分保存在 `POIEvidence`，二者不得混算。

## 二、为什么先增加 group_key

此前 `query_id` 中虽然包含分组名称，但解析字符串得到分组存在隐患：

- ID 格式变化会破坏评分逻辑。
- 分隔符可能与业务标识冲突。
- Pydantic 无法独立校验分组字段。
- 无法可靠检查查询分组是否完整或重复。

因此 `POIQuery.group_key` 已成为必填字段，由 `ProjectProfile.poi_groups` 直接写入。评分层只使用结构化 `group_key`，不解析 `query_id`。

## 三、评分方向

`ScoreDirection` 定义两种线性评分方向：

- `higher_is_better`：数值越大，得分越高。通常用于数量和密度。
- `lower_is_better`：数值越小，得分越高。通常用于最近距离和平均距离。

方向必须由配置显式声明。评分函数不会根据指标名称自动猜测方向。

## 四、线性归一化

每个指标配置 `lower_bound` 和 `upper_bound`，并要求：

```text
0 <= lower_bound < upper_bound
```

越大越好：

```text
score = clamp(
    (value - lower_bound) / (upper_bound - lower_bound) * 100,
    0,
    100,
)
```

越小越好：

```text
score = clamp(
    (upper_bound - value) / (upper_bound - lower_bound) * 100,
    0,
    100,
)
```

`clamp` 表示低于或高于配置范围时截断到 0 或 100，避免极端值把总分拉出合法区间。`NaN`、正无穷和负无穷会被拒绝，不会进入评分报告。

## 五、缺失指标策略

`MissingMetricPolicy` 当前只支持：

- `block`：缺少指标时抛出 `POIScoringError`。默认策略。
- `zero`：明确将缺失指标记为 0 分，同时在明细中保留 `raw_value=None`。

当前不支持 `skip`。跳过指标并重新分配剩余权重会让同一评分版本在不同数据完整度下产生不同公式，不利于复现和横向比较。

是否使用 `zero` 必须由业务配置明确决定。例如空 POI 结果可能合理地使数量得 0 分，但距离指标缺失既可能表示周边没有设施，也可能表示供应商没有返回距离，两者不能自动等同。

## 六、权重层级

评分有两层权重：

1. `POIGroupScoringConfig.metric_rules[].weight`：组内指标权重，总和必须为 1。
2. `ProjectProfile.poi_groups[].soft_score_weight`：项目 Profile 的分组权重，总和已经由 Profile 校验为 1。

计算过程：

```text
metric weighted score = normalized score * metric weight
group score = sum(metric weighted score)
group weighted score = group score * Profile group weight
total score = sum(group weighted score)
```

评分配置不重复保存 Profile 分组权重，避免同一权重在两个配置文件中发生漂移。

## 七、配置契约

### POIMetricScoringRule

保存：

- 指标类型。
- 评分方向。
- 归一化上下界。
- 组内权重。
- 缺失指标策略。

### POIGroupScoringConfig

保存分组标识和指标规则，并校验：

- 指标不能重复。
- 组内指标权重总和必须为 1。

### POIScoringConfig

保存：

- 项目类型。
- 评分版本。
- 全部分组评分配置。

评分执行时还会检查：

- 配置项目类型必须与 `ProjectProfile` 一致。
- 配置分组必须与 Profile 分组完全一致。
- 每个分组配置的指标必须与 Profile 声明指标完全一致。
- POI 数据分组必须与 Profile 分组完全一致。
- 同一候选地块不能出现重复分组。
- 一次纯函数调用只能处理一个候选地块。

## 八、可审计输出

`POIScoreReport` 保存：

- 候选地块编号。
- 项目类型。
- 评分配置版本。
- 每个分组的评分明细。
- 0-100 总分。

`POIGroupScore` 保存查询 ID、来源数据集、分组原始得分、Profile 权重和分组加权得分。

`POIMetricScore` 保存原始值、方向、归一化分、指标权重、加权分和缺失策略。

因此系统可以回答：

```text
这个总分使用哪个评分版本？
哪个分组贡献了多少分？
某项距离为什么得到该分数？
缺失指标按什么策略处理？
数据来自哪个 POI 数据集？
```

## 九、当前边界

本阶段只实现评分契约与纯函数，尚未：

- 配置商场和物流园的真实归一化上下界。
- 将评分报告写入 `POIEvidence`。
- 在 LangGraph 中增加评分节点。
- 建立评分配置审批、有效日期和发布流程。
- 使用真实项目样本校准阈值。

测试中的 `0-100` 上下界和 `demo-1.0` 版本均为合成参数，只用于验证公式，不能作为业务推荐标准。

## 十、测试验收

新增 20 项测试，覆盖：

- 越大越好与越小越好的线性公式。
- 上下界外截断。
- 非法上下界拦截。
- 组内权重总和校验。
- 重复指标和重复分组拦截。
- 完整评分报告及数据来源血缘。
- 项目类型、Profile 分组和 Profile 指标对齐。
- 重复数据分组拦截。
- 缺指标默认阻断和显式零分策略。
- `NaN` 与无穷值拦截。

评分契约测试为 `20 passed`，项目全量测试达到 `178 passed, 1 existing warning`。

## 十一、下一步

下一阶段先设计两类项目的评分配置草案和校准依据，再决定是否接入状态与工作流。真实阈值应来自业务目标、样本分布或专家确认，不能由代码随意指定。

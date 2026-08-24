# 选址项目入口与 POI 业务链路

> 当前范围：项目类型路由、Profile 获取、POI 查询生成、Mock POI 执行与状态回写

## 一、今日跑通的数据流

```text
原始请求数据
  -> ProjectRequest（Pydantic 校验）
  -> ProjectTypeRouter（按项目类型路由）
  -> ProfileRegistry（取得业务 Profile）
  -> build_poi_queries（生成确定性查询）
  -> ProjectIntakeSkill（建立 DATA_PENDING 状态）
  -> POIGateway（供应商无关接口）
  -> MockPOIGateway（测试实现）
  -> POIFeatureSet（记录、来源、指标）
  -> POIEvidence
  -> AgentState
```

这条链路没有调用 LLM。项目类型、查询半径、类别和状态转换都由确定性 Python 代码控制。

## 二、入口校验

`ProjectRequest` 是业务入口。数据只有通过 Pydantic 校验后，才会交给路由器。

当前入口会拦截：

- 未知项目类型，例如 `factory`
- 空候选地块列表
- 候选地块缺少经纬度等必需字段
- 经度或纬度越界
- 重复候选地块编号
- 不带时区的请求时间
- 未声明的额外字段

因此，未知类型和缺候选地块不是路由节点的正常分支，而是进入业务流程前的非法输入。

## 三、ProfileRegistry

`ProfileRegistry` 是项目 Profile 的统一读取边界，当前注册：

- `shopping_mall`：商场
- `logistics_park`：物流园

它负责：

1. 保存“项目类型 -> ProjectProfile”的白名单映射。
2. 检查注册键与 Profile 自身的 `project_type` 一致。
3. 对未知类型抛出 `UnsupportedProjectTypeError`。
4. 每次返回深拷贝，避免调用方修改全局静态配置。

它不负责：

- 理解用户自然语言
- 调用 POI 服务
- 执行 GIS 分析
- 生成合规结论

## 四、ProjectTypeRouter

`ProjectTypeRouter` 的职责非常窄：读取已经校验过的 `request.project_type`，再从 `ProfileRegistry` 取得对应 Profile。

```text
shopping_mall  -> SHOPPING_MALL_PROFILE
logistics_park -> LOGISTICS_PARK_PROFILE
```

路由器不使用关键词猜测项目类型。将来若由 LLM 提取类型，LLM 的输出仍须先经过 `ProjectType` 枚举校验。

## 五、POIQuery 生成

`build_poi_queries(request, profile)` 是纯函数：相同输入始终生成相同输出，不访问网络，也不修改输入对象。

生成规则是候选地块与 Profile POI 分组的笛卡尔积：

```text
查询数量 = 候选地块数量 * Profile POI 分组数量
```

目前每类 Profile 都有 6 个分组：

- 1 个候选地块生成 6 条查询
- 2 个候选地块生成 12 条查询

查询 ID 结构：

```text
{request_id}:{parcel_id}:{group_key}
```

例如：

```text
REQ-shopping:A01:public_transit
```

查询的经纬度来自候选地块，类别和半径来自项目 Profile。请求类型与 Profile 类型不一致时，函数立即拒绝执行。

## 六、ProjectIntakeSkill

`ProjectIntakeSkill` 编排入口阶段：

1. 调用 `ProjectTypeRouter` 取得 Profile。
2. 调用 `build_poi_queries()` 生成查询。
3. 创建选址业务 `AgentState`。
4. 将状态设置为 `DATA_PENDING`，表示查询计划已建立，但外部数据尚未全部准备完成。

这里的 Skill 是确定性业务能力封装，不是一个自主 Agent，也不直接调用 LLM。

## 七、POIGateway

`POIGateway` 是供应商无关接口：

```python
class POIGateway(Protocol):
    def search(self, query: POIQuery) -> POIFeatureSet: ...
```

业务执行函数依赖这个接口，而不依赖高德、百度或某个具体 SDK。以后可以分别实现：

- `AmapPOIGateway`
- `BaiduPOIGateway`
- `PostGISPOIGateway`

只要实现相同的 `search()` 契约，上层业务流程无需重写。

## 八、MockPOIGateway

`MockPOIGateway` 用于不访问网络的业务测试。它会：

- 按候选地块编号读取测试记录
- 过滤不属于查询类别的记录
- 过滤超过查询半径的记录
- 按距离由近到远排序
- 应用 `limit` 数量上限
- 生成 `POISourceMeta(provider=mock)`
- 返回合法的 `POIFeatureSet`

Mock 的意义不是模拟所有真实地图行为，而是验证上层业务编排不依赖真实供应商。

## 九、POI 指标

当前由标准化后的 `POIRecord` 计算四类基础指标：

- `count`：记录数量
- `density_per_sq_km`：单位查询圆面积内的 POI 密度
- `nearest_distance_m`：最近距离
- `average_distance_m`：平均距离

查询面积按圆计算：

```text
面积（平方千米） = pi * (radius_m / 1000)^2
密度 = POI 数量 / 面积
```

若上游记录没有距离数据，则不伪造最近距离和平均距离指标。

这些指标属于选址辅助信息，不是法定空间合规结论。

## 十、状态回写

`execute_poi_queries(state, gateway)` 会：

1. 执行状态中已准备的全部 `POIQuery`。
2. 收集 `POIFeatureSet`。
3. 按候选地块组织 `POIEvidence`。
4. 返回一个重新经过 Pydantic 校验的新 `AgentState`。

函数不会原地修改传入状态。这使节点测试、失败回滚和后续 LangGraph 状态更新更清晰。

## 十一、测试覆盖

本阶段新增 19 项测试，覆盖：

- 商场和物流园路由
- 未知项目类型
- 空候选地块
- 注册键与 Profile 类型不一致
- Profile 防御性深拷贝
- 两类项目生成不同查询规则
- 多候选地块查询数量和 ID 唯一性
- 请求与 Profile 类型不匹配
- `ProjectIntakeSkill` 状态转换
- Mock 类别与半径过滤
- 距离排序和数量上限
- 空 POI 结果
- 数量、密度、最近距离和平均距离指标
- POI 结果写回业务状态
- 输入状态不被原地修改

项目全量结果：

```text
86 passed, 1 existing Starlette warning
```

## 十二、当前边界

已经完成的是可测试的业务骨架，不代表已经完成真实选址分析：

- 尚未接入真实高德、百度或 PostGIS POI 查询
- Mock 中的 `distance_m` 是已标准化测试数据，不负责坐标距离计算
- 尚未校验空间数据 CRS、必需字段和几何有效性
- 尚未执行缓冲区、相交、距离等 GIS 运算
- 尚未实现 POI 软评分归一化
- 尚未接入政策 RAG 和 RuleEngine
- 尚未生成最终 `AnalysisResult`
- POI 指标不得表述为法定合规结论

## 十三、下一步

下一模块是 `spatial/validate.py`：

```text
DatasetManifest / 空间数据
  -> CRS 存在性检查
  -> 必需字段检查
  -> 空几何检查
  -> 几何有效性检查
  -> 合法数据才能进入 GIS 分析节点
```

第一批测试至少覆盖：缺 CRS、缺字段、空几何、无效几何和合法数据。

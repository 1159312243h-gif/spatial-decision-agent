# 多候选 Fixture 与数据可信度

## 目标

这组 Fixture 解决的是“案例太少，无法观察候选之间差异”的工程问题，不解决“获得真实城市设施现状”的数据采购问题。它用于验证 Agent 是否能在更丰富、可重复的输入上正确完成查询、评分、排序、证据展示、报告和异常处理。

## 当前规模

| 对象 | 数量 | 作用 |
|---|---:|---|
| 商场候选 | 6 | 比较轨交餐饮、办公、居住、综合服务、竞争饱和和成长外围画像 |
| 物流园候选 | 6 | 比较高速、铁路、港口、城市配送、综合物流和航空联运画像 |
| POI | 478 | 验证不同半径、类别、数量、密度和最近距离指标 |
| POI 类别 | 25 | 覆盖商业、居住、公共服务、交通、物流和敏感点 |
| 候选空间图层 | 2 | 商场与物流园各一层，包含不同面积的候选多边形 |
| 约束空间图层 | 2 | 每类项目各含 2 个约束要素，用于相交和最近距离验证 |

## 如何生成

`scripts/generate_rich_fixtures.py` 是单一生成源。它固定候选中心、面积、场景画像、每类 POI 数量和距离范围，再确定性生成：

- `data/fixtures/candidates.json`
- `data/fixtures/poi.json`
- `data/fixtures/spatial_layers.json`

相同版本的生成器每次输出完全一致，测试会将磁盘 JSON 与生成器结果逐项比较，防止人工修改导致候选、POI 和空间图层互相不一致。

## Agent 如何使用

1. Workbench 按项目类型加载 6 个候选，用户仍可编辑或删减。
2. API 对每个候选构造 Profile 中定义的 POI 查询组。
3. Fixture Adapter 按类别和半径过滤 478 条记录；选择 `auto / amap / overpass` 时，Provider Adapter 自动分页或构造受控在线查询。
4. 指标层计算数量、密度和最近距离，评分层使用版本化归一化配置生成软评分。
5. GIS 分支读取对应候选多边形和约束图层，计算面积、相交与最近距离。
6. 比较报告并列显示所有候选，不把最高软评分表述为自动推荐。

## 防止“看起来很多但仍然不可信”

数量增加不能自动产生真实可信度，因此系统强制暴露以下信息：

- `record_count`：本次查询实际命中的记录数；
- `available_record_count`：Adapter 在应用 `limit` 前确认的查询可用记录数；
- `is_truncated`：查询是否因返回上限只保留了部分结果；
- `dataset_record_count`：完整 Fixture 数据集的记录总数；
- `dataset_version`：可复现的数据版本；
- `is_synthetic`：是否为合成数据；
- `quality_notice`：明确禁止解释为真实城市覆盖率。

Workbench 和 DOCX 报告都会展示这些字段。测试还要求 12 个候选全部有场景 POI、两类项目分别产生至少 4 种不同软评分，避免只是复制同一份数据换名称。

当 `available_record_count > record_count` 时，契约强制 `is_truncated=true`，Evidence Review 触发人工复核，并把数量、密度和评分输入描述为下界。高德使用 Provider 返回的 `count`，Overpass 使用解析并去重后的元素数量，Fixture 使用半径和类别过滤后的数量。这个机制解决“每组恰好 100 条看起来像真实总量”的误导，但它不等同于已经完成跨页全量抓取。

## 在线自动加载

`SITE_SELECTION_POI_PROVIDER` 支持 `fixture`、`auto`、`amap` 和 `overpass`。`auto` 在存在 `AMAP_API_KEY` 时选择高德，否则选择 Overpass。在线响应统一转成 WGS84 `POIRecord`，写入 Redis 查询缓存，并按 `source + source_id` 去重入库 PostGIS。上游临时不可用时可以明确回退 Fixture；来源字段会保留原 Provider 和失败类型，因此不会把合成回退伪装成在线数据。

## 仍未解决的真实数据问题

运行时已经可以接入高德或 Overpass，但要把结果用于真实选址，还必须完成：

- 行政区和搜索半径的完整分页；
- Provider 类别到内部标准类别的抽样验收；
- GCJ-02、WGS84 与投影坐标系的显式转换和精度抽检；
- 数据更新时间、缺失率、重复率和覆盖率监控；
- 来源授权、配额、成本和审计记录；
- 多 Provider 或权威底库的交叉验证。

因此当前正确表述是：“系统已能在 12 个差异化合成候选和 478 条可复现 POI 上完成多候选证据比较。”不应表述为：“系统已经掌握真实城市 POI，能够给出可靠商业选址结论。”

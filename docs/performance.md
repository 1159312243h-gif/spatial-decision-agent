# Day 26 性能记录

## 已知回归基线

以下数据来自开发者在 Windows 终端中的实际运行输出，不是本次文档生成时重新测量：

| 日期/阶段 | 范围 | 结果 | 备注 |
|---|---|---|---|
| Day 20 | 空间查询、POI 指标、MCP 工具 | `20 passed in 1.87s` | 测试批次总耗时，不能拆成单接口 SLA |
| Day 24 | 当时全量回归 | `407 passed in 8.38s` | Docker Fixture Smoke 另行通过 |
| Day 25 | 当前 Day 26 复制前基线 | `425 passed in 7.23s` | 机器热状态与后台负载未记录 |
| Day 26 | 增加冻结评测与性能记录后的全量回归 | `430 passed in 8.39s` | Windows/Python 3.12 本机运行 |

这些结果只用于发现大幅回归，不能用于宣称生产吞吐或延迟。

## Day 26 本机 Fixture 结果

命令使用 `7` 个正式样本和 `2` 次预热，结果写入 `evals/results/day26-performance.json`：

| 指标 | 中位数 | 最小值 | 最大值 | 样本状态 |
|---|---:|---:|---:|---|
| GeoPandas 面积、相交、最近距离组合 | `0.124ms` | `0.113ms` | `0.170ms` | 1 个候选地、1 个约束，EPSG:32651 |
| Fixture POI 查询 | `0.110ms` | `0.109ms` | `0.117ms` | 本地 478 条 JSON，无 Redis、无网络 |
| 政策混合检索 | `0.033ms` | `0.030ms` | `0.043ms` | 3 份合成政策，确定性 Embedding |
| 24 条冻结评测批次 | `128.542ms` | `123.718ms` | `192.795ms` | 包含 4 条完整工作流与 4 条 POI 故障 |

以上数字是一次本机 Fixture 测量结果，不是生产 Benchmark、容量声明或在线 POI SLA。

## Day 26 测量协议

运行：

```powershell
python .\scripts\benchmark_day26.py --samples 7 --warmup-runs 2
```

脚本会写入 `evals/results/day26-performance.json`，测量：

- 单候选地/单约束的 GeoPandas 面积、相交与最近距离组合；
- 478 条本地 Fixture 上的 POI 分类和半径检索；
- 3 份 Fixture 政策上的 BM25 + 向量 + RRF 检索；
- 24 条冻结评测的完整批次。

每项记录 Python/平台、Fixture 版本、输入规模、预热次数、样本数、中位数、最小值和最大值。结果文件必须由目标机器真实运行生成，不在文档中预填虚构数字。

## 不包含的指标

- 公网高德/Overpass 网络延迟与可用率；
- 真实城市级 POI 数量和覆盖率；
- 大规模 PostGIS 图层的查询计划；
- 多用户并发、任务队列吞吐和 Redis 内存增长；
- LLM Provider 延迟、Token 用量和成本。

这些指标需要真实数据、授权与容量目标后单独设计测试。

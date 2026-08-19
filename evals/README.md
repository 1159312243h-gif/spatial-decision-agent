# Day 26 冻结评测

`day26_cases.json` 是版本化、可审计的 24 案例清单。评测只使用仓库内合成 Fixture，不调用在线 POI，也不把实时数量、网络延迟或 LLM 文本写成固定期望。

类别分布：

| 类别 | 数量 | 目标 |
|---|---:|---|
| `preflight` | 4 | 输入完整性与 Profile 路由 |
| `spatial` | 6 | CRS、几何、字段与合法数据 |
| `poi` | 3 | 类别、半径和空结果 |
| `poi_failure` | 4 | 429、重试、熔断、格式错误与降级 |
| `rag` | 3 | 项目/行政区过滤和可定位引用 |
| `runtime` | 4 | 商场、物流园、HITL 与失败闭环 |

运行：

```powershell
python .\scripts\run_day26_evaluations.py
```

评测通过条件是 `failed=0`。每条 `expected` 必须是 `actual` 的结构化子集，目的是冻结关键行为，同时允许实际结果增加非破坏性审计字段。

修改 Fixture、Profile、规则、坐标处理、异常分类或人工复核语义时，必须审查该清单。不能只为通过测试而修改期望；业务语义改变需要记录原因和版本。

结果目录：

- `results/day26-summary.json`：功能评测结果；
- `results/day26-performance.json`：本机 Fixture 性能记录。

结果包含运行环境和生成时间，允许在不同机器重新生成，不作为源码中的跨机器固定值。

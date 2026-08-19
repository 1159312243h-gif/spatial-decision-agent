# 2026-08-26 评测、文档与版本冻结

## 本日目标

把已经能运行的 GIS Agent 从“功能集合”推进为可评测、可解释、可复现的作品集版本。重点不是继续增加功能，而是冻结关键行为、记录限制并让陌生读者能够理解和复跑系统。

## 完成内容

- 外置 `evals/day26_cases.json`，冻结 24 条案例和三类 Fixture 版本。
- 覆盖前置检查、空间校验、POI 正常/失败、RAG 和完整 LangGraph 工作流。
- 四条 POI 故障案例分别验证 429 重试、熔断降级、格式错误不重试和熔断阻止额外 HTTP。
- 新增批量评测器，逐条记录期望、实际、耗时和清洗后的异常类型。
- 新增本机性能采集脚本，记录 GIS、POI、RAG 和整批评测的中位数。
- 重写 README，补充架构图、数据字典、Bad Case 和性能协议。
- 定向测试 `5 passed in 2.39s`，冻结评测 `24/24` 通过。
- 全量回归 `430 passed in 8.39s`，`git diff --check` 无空白错误。
- 本机性能中位数：GIS `0.135ms`、Fixture POI `0.031ms`、RAG `0.033ms`、24 案例批次 `88.798ms`。

## 冻结边界

- Fixture POI 仅 32 条，不能作为真实选址参考。
- 政策、规则、阈值和空间图层均为合成数据。
- GCJ-02 不能直接标为 EPSG:4326。
- 人工确认仅表示已阅，不是合规批准。
- 未命中规则不等于整体合规。
- LLM 解释不改变评分、排序或规则结果。
- 性能数据只表示本机 Fixture，不是生产 Benchmark。

## 复现命令

```powershell
python .\scripts\run_day26_evaluations.py
python .\scripts\benchmark_day26.py --samples 7 --warmup-runs 2
python -m pytest -q --basetemp .\.venv\pytest-tmp-day26
git --no-pager diff --check
```

生成的 JSON 结果应与代码、Fixture 和文档一起审查。提交前先确认全量回归，再决定是否把生成结果纳入版本控制。

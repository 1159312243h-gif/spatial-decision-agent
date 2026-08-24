# AI 代码审查

## 审查对象

`practice/ai_code_review_sample.py`

## 问题记录


| 序号 | 代码位置 | 问题 | 可能后果 | 修改建议 | 严重程度 |
|---|---|---|---|---|---|
| 1 | `open(file_path)` | 没有指定编码 | UTF-8 文件可能被按 GBK 读取并报错 | 指定 `encoding="utf-8"` | 高 |
| 2 | `reports=[]` | 使用可变默认参数 | 多次调用会共享之前的数据 | 默认值改为 `None` | 高 |
| 3 | `open(file_path)` | 文件没有明确关闭 | 异常时可能占用文件资源 | 使用 `with open(...)` | 中 |
| 4 | `missing_crs.append(...)` | 变量未初始化 | 运行时触发 `NameError` | 循环前创建 `missing_crs = []` | 高 |
| 5 | `layer["type"]` | 没有校验字段 | 缺少字段时触发 `KeyError` | 先验证数据类型和必需字段 | 高 |
| 6 | `layer_types.count(...)` | 重复遍历列表 | 数据较多时效率低 | 使用字典在一次循环中累加 | 中 |
| 7 | `list(set(...))` | 输出顺序不稳定 | 相同输入可能展示不同顺序 | 使用 `sorted(set(...))` | 低 |

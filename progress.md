# 学习进度

## 2026-08-03

> 本次任务跨午夜完成，首次提交完成于 2026-08-04 00:01。

### 今日完成

- 安装并验证了 Python 3.12.4
- 创建了 Python 虚拟环境 `.venv`
- 成功激活虚拟环境
- 验证了虚拟环境中的 Python 和 pip
- 创建了本地 Git 仓库
- 配置了 `.gitignore`
- 建立了 Agent 学习项目骨架
- 创建了 `src`、`tests` 和 `notes` 目录
- 编写并运行了最小 Python 程序
- 编写了项目 `README.md`
- 完成了第一次 Git 提交
- 修正了 Git 提交者的姓名和邮箱

### 项目运行结果

执行命令：

`python -m src.main`

输出结果：

`Agent learning project is ready.`

### 今日理解

- Python 虚拟环境依赖电脑中已经安装的基础 Python
- 虚拟环境用于隔离不同项目的 Python 依赖
- 激活虚拟环境后，`python` 和 `pip` 会指向 `.venv`
- `git init` 用于初始化本地 Git 仓库
- `git status` 用于查看文件状态
- `.gitignore` 用于排除不需要提交的文件
- `git add` 用于把修改加入暂存区
- `git diff --staged` 用于检查即将提交的内容
- `git commit` 用于把暂存区内容保存为一个版本
- Git 不会直接跟踪空目录，可以使用 `.gitkeep` 保留目录

### 遇到的问题

#### 1. PowerShell 无法识别 `py`

- 现象：执行 `py --version` 时提示无法识别命令
- 原因：系统中没有可用的 Python Launcher
- 解决方式：安装 Python 3.12.4，并改用 `python` 命令
- 是否理解：已理解，`py` 和 `python` 是不同的命令入口

#### 2. 无法激活虚拟环境

- 现象：PowerShell 提示系统禁止运行脚本
- 原因：PowerShell 执行策略阻止了 `Activate.ps1`
- 解决方式：执行 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- 是否理解：已理解，该设置只对当前 PowerShell 窗口有效

#### 3. 把 `.gitignore` 内容输入了终端

- 现象：PowerShell 把 `.venv/` 等内容当作命令执行
- 原因：没有区分终端命令和文件内容
- 解决方式：使用 VS Code 打开 `.gitignore`，在文件编辑区填写并保存
- 是否理解：已理解，终端用于执行命令，编辑器用于修改文件

#### 4. 进入 Git 分页查看器

- 现象：执行 `git diff --staged` 后进入帮助页面
- 原因：Git 使用分页查看器展示较长内容
- 解决方式：按 `q` 退出分页查看器
- 是否理解：已理解

#### 5. Git 自动使用了 unknown 用户名

- 现象：第一次提交提示提交者姓名和邮箱由 Git 自动生成
- 原因：仓库没有配置 Git 用户身份
- 解决方式：为当前仓库配置用户名和邮箱，并修改首次提交
- 是否理解：已理解，Git 提交记录包含作者身份

### 验收结果

- `python --version` 正常输出 Python 3.12.4
- `python -m src.main` 可以正常运行
- `git log --oneline -1` 可以看到首次提交
- `.venv` 没有被 Git 跟踪
- `git status` 显示工作区干净

### 明日任务

- 学习 Git 分支、合并和冲突
- 复习 Python 函数、列表、字典和集合
- 编写一个简单的数据统计程序
- 继续保持每完成一个步骤就进行验证的习惯

## 2026-08-04

> 本次任务跨午夜至 2026-08-05 完成。

### 今日完成

- 检查并恢复 Python 虚拟环境
- 学习 `branch`、`switch`、`merge`、`pull`、`push`
- 创建 `practice/git-branch`
- 在两个分支修改同一行
- 主动制造并解决一次合并冲突
- 创建 merge commit `9f35813`
- 编写 `practice/python_basics.py`
- 完成图层总数、类型集合、缺失 CRS 和按类型统计
- 完成 12 项正常与异常输入检查
- 使用 `.venv` 运行并输出 `All checks passed.`

### Git 理解

- 分支是指向提交的可移动引用
- `merge` 将另一个分支历史合入当前分支
- 两个分支修改同一行时 Git 无法自动选择，因此产生冲突
- `HEAD` 区域来自当前 `master`
- 分隔线下方来自 `practice/git-branch`
- 解决冲突后需暂存并创建 merge commit
- `pull` 获取并整合远程修改，`push` 上传本地提交；本次未实际执行

### Python 理解

- 列表保存有顺序的多个图层
- 字典保存单个图层字段和统计结果
- 集合保存不重复的图层类型和已见名称
- 循环逐项处理，条件判断负责校验异常输入

### 发现并修复的问题

- 缺少字段可能产生难理解的 `KeyError`，改为明确的 `ValueError`
- 重复图层可能导致重复计数，增加 `seen_names` 检查
- 非列表和非字典输入增加 `TypeError`
- 空列表返回合法的空统计结果

### 工具问题

- Codex 审批服务返回 403，无法代替用户写入 `.git` 或启动用户目录 Python
- 通过 VS Code 完成 Git 操作，并使用项目 `.venv` 手动运行脚本

### 后续任务

- GitHub 上传前检查作者邮箱和敏感信息
- 决定仓库公开或私有
- 将 `master` 统一为 `main`
- 创建 GitHub 空仓库并首次 `push`
- 后续再进入 GIS Agent 正式开发

## 2026-08-05

### 今日完成

- 理解了 LLM、Token、Prompt、Tool、Agent 和 Skill 的关系
- 创建了 `Layer` 类，练习了类、对象、属性和函数参数
- 将图层统计代码拆分为 `models.py`、`service.py` 和 `io.py`
- 使用 `pathlib` 和 `json` 完成 UTF-8 JSON 文件读取
- 使用 `try/except` 处理文件不存在和 JSON 格式错误
- 创建了 `run_layer_stats.py` 程序入口
- 使用 `unittest` 完成 6 项自动化测试
- 创建 GitHub 私有仓库并完成首次推送

### 今日理解

- 模块是一个 Python 文件，包是组织多个模块的目录
- 类是创建对象的模板，对象保存具体数据
- `raise` 用于主动报告错误，`try/except` 用于处理可预期错误
- JSON 的 `null` 读取到 Python 后会变成 `None`
- Tool 负责执行动作，Skill 负责描述可复用的执行方法
- `git commit` 保存到本地，`git push` 才会上传到 GitHub

### 测试结果

- 正常图层数据：通过
- 空列表：通过
- 缺少字段：通过
- 重复图层：通过
- JSON 格式错误：通过
- 文件不存在：通过
- 总计 6 项测试，全部通过

### 遇到的问题

- Codex 审批服务返回 403，Git 写操作改在本地 PowerShell 执行
- 首次推送 GitHub 时网络连接超时，重新连接后推送成功
- 修改 Git 用户邮箱只影响未来提交，不会自动修改历史提交

### 明日任务

- 复习模块、包、类和异常处理
- 学习如何为函数和类编写更完整的测试
- 根据后续计划继续完善图层数据处理能力

## 2026-08-06

### 今日完成

- 复习了 Python 模块、类、异常处理和 JSON 读取
- 练习了 `git diff`、`git diff --stat` 和 `git diff --staged`
- 审查了 AI 生成的图层统计代码
- 记录了编码、可变默认参数、文件关闭、变量初始化、字段校验、统计效率和输出顺序等 7 个问题

### Git 知识点

- `git diff` 查看工作区中尚未暂存的修改
- `git diff --stat` 查看修改文件和行数摘要
- `git diff --staged` 查看暂存区中准备提交的修改
- 文件暂存后，修改会从普通 diff 转移到 staged diff

### 遗留任务

- Hot100 第 1 题和第 49 题顺延至 8 月 7 日完成

## 2026-08-07

### 今日完成

- 审查了简历中的项目经历，确认保留两个项目：
  - 多类型建设项目选址与国土空间合规决策 Agent
  - 地理图表理解与问答评测系统
- 删除或暂不使用无法证明的训练规模、准确率和性能提升数据
- 明确简历描述应采用“完成了什么 + 使用什么技术 + 解决什么问题 + 可验证结果”的结构
- 学习了 Self-Attention 中 Q、K、V 的作用
- 理解了 `QKᵀ → 缩放 → Softmax → 乘 V` 的计算流程
- 理解了除以 `sqrt(d_k)` 是为了防止点积过大导致 Softmax 饱和

### 今日理解

- Q 表示当前词想查询什么信息
- K 表示每个候选词用于匹配的特征
- V 表示匹配后实际提供的内容
- 每个词通过 Q 与所有词的 K 计算相关度，再加权汇总所有词的 V，因此能够融合上下文信息
- 简历中的数据必须能够通过代码、测试结果或实验记录证明，不能根据参考项目直接填写

### 遗留问题

- 两个简历项目还需要随着实际开发进度持续更新
- 项目性能指标应等测试脚本和评测数据完成后再补充
- Multi-Head Attention、位置编码和完整 Transformer 结构后续继续学习

### 下一步

- 开始 FastAPI 基础开发
- 实现 `/health`、`/documents` 和 `/chat` 三个接口
- 完成参数校验、接口测试和 Swagger 联调
## 2026-08-08

### 今日完成

- 安装并验证 FastAPI、Uvicorn、pytest 和 httpx
- 建立 `app/api`、`app/schemas` 和 `app/services` 分层目录
- 实现 `GET /health` 健康检查接口
- 实现 `POST /documents` 文档元数据桩接口
- 实现 `POST /chat` 选址问题桩接口
- 使用 Pydantic 校验缺失字段、空问题和非法项目类型
- 通过 Swagger 完成三个接口的手工联调
- 新增 6 项 API 自动化测试
- 运行全部测试，12 项测试全部通过
- 完善 README 中的安装、启动、接口和测试说明

### 今日理解

- FastAPI 用于把 Python 函数组织成可以通过 HTTP 调用的后端接口
- Uvicorn 负责启动服务并监听请求
- Swagger 是接口说明和调试工具，不负责理解自然语言
- Pydantic 负责把不合法的请求拦截在业务逻辑之前
- `api` 层定义 HTTP 路由，`schemas` 层定义数据结构，`services` 层处理业务逻辑
- 当前 `/documents` 和 `/chat` 是桩接口，尚未接入真实 Agent、RAG、数据库或 GIS 分析
- 自动化测试可以重复验证正常请求和异常输入，比只依赖 Swagger 手工点击更可靠

### 遇到的问题

- `api/documents.py` 与 `schemas/documents.py` 内容一度放反，导致 Uvicorn 重载失败和 Swagger 白屏
- 通过检查 Uvicorn 终端和模块内容定位问题，交换文件内容后恢复
- 直接遍历 `app.routes` 读取 `path` 时遇到 `_IncludedRouter`，改用 `app.openapi()["paths"]` 检查公开接口
- pytest 出现 TestClient 依赖弃用 warning，但不影响当前 12 项测试结果，后续根据官方兼容说明统一处理

### 调整说明

- 因时间不足，跳过当天 ACM 和 Hot100 编程题，不补做、不挤占休息时间

## 本周总结（2026-08-03 至 2026-08-09）

### 本周完成

- 创建并激活 Python 3.12 虚拟环境，掌握依赖隔离的基本方法
- 创建本地 Git 仓库，完成首次提交、分支切换、合并和冲突处理
- 创建 GitHub 私有仓库，配置远程地址并完成多次 push
- 学习 Python 函数、列表、字典、集合、模块、包、类、异常处理和 JSON 读取
- 将图层统计脚本拆分为模型、文件读取、业务统计和程序入口
- 完成正常数据、空数据、字段缺失、重复图层、无效 JSON 和文件不存在测试
- 学习 `git diff`、`git diff --stat` 和 `git diff --staged`
- 完成一次 AI 生成代码审查，记录编码、可变默认参数、资源关闭、变量初始化和效率等问题
- 完成两数之和与字母异位词分组练习，理解哈希表和哈希键设计
- 审查简历项目真实性，删除无法证明的训练规模和效果指标
- 学习 Self-Attention 中 Q、K、V、缩放、Softmax 和上下文融合
- 建立 FastAPI 接口骨架，完成三个接口、Pydantic 校验、Swagger 联调和 API 自动化测试

### 本周掌握

- 能解释工作区、暂存区、本地仓库和远程仓库的区别
- 能完成 Git 分支开发、制造冲突、解决冲突、提交和推送
- 能使用 Python 包和模块拆分代码，并使用异常表达无效输入
- 能读取 UTF-8 JSON 并将字典数据转换为对象
- 能使用 unittest 和 pytest 验证正常路径及异常路径
- 能解释 FastAPI、Uvicorn、Swagger、Pydantic 和桩接口各自的职责
- 能解释 Q、K、V 和除以 `sqrt(d_k)` 的直观原因

### 本周遗留问题

- 当前 FastAPI 接口没有真实文件上传、持久化和文档解析能力
- `/chat` 尚未接入 LLM、意图识别、RAG 或 GIS 工具
- 项目类型目前只支持 `shopping_mall` 和 `logistics_park`
- 测试客户端存在依赖弃用 warning，需要后续查阅官方兼容方案
- Multi-Head Attention、位置编码和完整 Transformer 结构仍需继续学习
- 简历中的项目效果指标需要等真实评测脚本和数据完成后补充

### 下周目标

- 学习 FastAPI 文件上传、配置管理和统一异常处理
- 为 `/documents` 增加真实文件接收与元数据处理
- 为 `/chat` 设计可扩展的意图和候选地块输入结构
- 开始搭建项目文档解析与检索的最小流程
- 保持 Git 小步提交、pytest 回归测试和 progress 记录
- 恢复算法训练，但不挤占主项目开发和休息时间


## 2026-08-10

### 今日完成

- 复习 Token、上下文、消息角色和 Temperature
- 使用 OpenAI Python SDK 调用公司九功模型
- 通过原生 Responses API 完成最小聊天函数
- 使用 `.env` 管理真实配置，并使用 `.env.example` 提供配置模板
- 实现保留最近若干轮对话的滑动窗口
- 完成物流园选址需求的任务拆分练习
- 模型成功输出 5 个有顺序的执行步骤

### 今日理解

- Token 是模型处理文本的基本单位
- 上下文由程序保存并在下一次请求中重新发送
- System 规定规则，User 提出需求，Assistant 表示历史回复
- Temperature 控制输出的随机程度，不代表模型的聪明程度
- `.env` 保存真实配置且不能提交
- `.env.example` 只能保存变量名称和占位符
- 滑动窗口能够限制历史消息数量，避免上下文无限增长
- Responses API 使用 `client.responses.create()` 发起请求

### 遇到的问题

- `practice.llm_api` 尚未创建，首次运行出现 `ModuleNotFoundError`
- 创建 Python 包和 `client.py` 后解决
- 最初误将真实配置写入 `.env.example`
- 在 Git 暂存前替换为占位符，避免进入仓库
- CC Switch 使用原生 Responses 格式，因此将调用方式从 Chat Completions 改为 Responses API

### 遗留问题

- 当前滑动窗口按照对话轮数限制，还没有按照 Token 数量限制
- LLM API 和上下文模块还没有自动化测试
- `/chat` 接口尚未接入真实模型调用

### 下一步

- 为上下文窗口编写单元测试
- 处理模型超时、鉴权失败和空回复异常
- 根据后续计划决定是否将真实模型接入 FastAPI `/chat`

## 2026-08-11

### 今日完成

- 整理 Token、上下文窗口、消息角色和 Temperature 四张知识卡
- 阅读并解释现有 `ConversationContext` 滑动窗口代码
- 确认滑动窗口保留系统指令和最近完整问答，超出轮数后自动淘汰最旧轮次
- 审查现有 `chat()` 函数的输入、输出、API 参数和上下文保存流程
- 初步学习 Prompt 模板、Zero-shot、Few-shot 和结构化输出的基本关系

### 今日理解

- Token、系统指令、历史消息、当前问题和模型输出都会占用上下文容量
- 当前滑动窗口按照完整问答轮数裁剪，并不按照真实 Token 数裁剪
- 系统消息通过 `instructions` 单独传入，不会随旧对话一起被淘汰
- Prompt 模板把稳定的任务规则与动态用户输入分开
- Zero-shot 只提供任务说明，Few-shot 额外提供少量标准输入输出示例

### 当前边界

- 当前窗口按对话轮数限制，尚未按真实 Token 数限制
- 滑动窗口没有旧消息摘要、持久化和多用户会话隔离
- LLM API 和上下文模块还没有自动化测试

### 下一步

- 深入整理 Prompt 模板、Few-shot、输出约束和非法 JSON
- 建立选址需求 Pydantic 输出模型骨架
- 完成一次合法 JSON 的正常解析

## 2026-08-12

### 今日完成

- 深入学习 Tokenizer、BPE、BBPE、WordPiece、Unigram 和 SentencePiece
- 学习 Greedy Search、Beam Search、Top-k、Top-p 和 Temperature 等生成策略
- 阅读并整理前辈的 Prompt 工程资料，形成适用于当前选址 Agent 的项目版笔记
- 整理 Zero-shot/Few-shot、输出约束、非法 JSON 三张知识卡
- 建立 `SiteSelectionRequirement` Pydantic 输出模型骨架
- 使用 `model_validate_json()` 完成一次合法 JSON 到 Pydantic 对象的正常解析

### 今日理解

- Tokenizer 负责在文本与 Token ID 之间编码和解码，生成策略负责选择下一个 Token
- Prompt 模板负责固定角色、任务、输入边界、约束和输出协议
- Few-shot 通过少量标准输入输出示例帮助模型稳定字段映射和缺失值处理
- 模型返回 JSON 文本后，仍需经过 JSON 语法解析和 Pydantic 字段校验
- 非法 JSON 属于语法错误；字段缺失、类型错误和取值越界属于 Pydantic 校验错误
- 当前 Pydantic 模型表示选址需求，不代表已经生成合规审查结论
- 当前项目使用 Responses API，不能直接照抄 Chat Completions 的结构化输出代码

### 当前边界

- 已完成手工构造的合法 JSON 解析，尚未接入真实 API 返回文本
- 尚未实现非法 JSON、字段缺失和类型错误测试
- 公司模型接口是否支持服务端原生 Structured Outputs 尚未验证
- Prompt 只能约束模型输出倾向，不能代替 GIS 计算、政策证据和规则引擎

### 下一步

- 建立可复用的选址需求提取 Prompt 模板和 Few-shot 示例
- 将真实 API 返回的 JSON 文本解析为 Pydantic 对象
- 覆盖合法 JSON、非法 JSON、缺字段、错误类型和额外字段测试
- 设计明确的解析失败提示与有限重试策略

## 2026-08-13

### 今日完成

- 验证 `SiteSelectionRequirement` 对正常 JSON、非法 JSON 和缺失字段的处理
- 学习 Function Calling 的六步调用链路并完成闭卷流程图
- 整理 Function Calling 学习文档，明确模型、应用程序、Pydantic 和工具函数的职责
- 实现不使用 `eval()` 的安全计算器，支持加、减、乘、除
- 使用工具白名单和 Pydantic 校验工具名称及参数
- 实现 Responses API 完整工具调用循环
- 完成计算问题、普通对话、缺少参数及其他异常边界测试
- 使用公司模型端点完成一次真实 Function Calling 调用

### 今日理解

- 模型只负责选择工具、生成参数和组织最终回答，不直接执行 Python 函数
- JSON Schema 向模型描述参数合同，Pydantic 在程序端校验实际参数
- 应用程序必须校验工具白名单和参数后才能执行函数
- 工具结果需要回传模型，模型才能基于真实结果生成最终回答
- 工具执行失败时必须回传明确错误，不能伪造计算结果
- `eval()` 会执行任意 Python 表达式，不适合作为计算器实现

### 接口实测

- 当前公司 Responses 兼容接口支持函数工具定义、`function_call` 和 `function_call_output`
- 普通 HTTP 请求不支持使用 `previous_response_id` 串联响应，该字段仅支持 Responses WebSocket v2
- 第二次请求显式携带用户消息、`function_call` 和 `function_call_output` 后，真实调用成功
- 实测问题为“请计算 18.5 乘以 4”，最终回答为“18.5 × 4 = 74”

### 测试情况

- 计算器与工具调用专项测试共 10 项，全部通过
- 已覆盖正常计算、普通对话、缺少参数、非法操作、除零、额外参数、未注册工具和空输入

### 当前边界

- 当前只注册了计算器工具，尚未接入选址 Agent 的 GIS、政策检索和规则工具
- 当前调用上下文由程序显式回传，尚未使用 WebSocket v2
- 尚未验证连续多次工具调用、并行工具调用和接口超时后的重试策略
- 工具调用循环尚未接入 FastAPI `/chat`

### 下一步

- 为完整项目运行全部测试并检查 Git 差异
- 后续将工具注册表扩展为可复用结构
- 按项目计划逐步接入选址数据查询、GIS 分析和政策检索工具
- 在明确会话管理与错误处理方案后，再将真实工具调用接入 FastAPI `/chat`

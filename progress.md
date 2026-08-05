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
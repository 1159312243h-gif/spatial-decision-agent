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
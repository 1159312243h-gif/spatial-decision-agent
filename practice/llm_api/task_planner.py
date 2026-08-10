from .client import chat


SYSTEM_MESSAGE = """
你是一名建设项目选址合规审查任务规划助手。

你的职责是把用户的选址需求拆分成可执行步骤，
不直接编造审查结果，不代替法定审批结论。
"""


def create_site_selection_plan(requirement: str) -> str:
    if not requirement.strip():
        raise ValueError("选址需求不能为空")

    prompt = f"""
请把下面的建设项目选址需求拆分成3至5个有顺序的执行步骤：

{requirement}

要求：
1. 使用编号列表输出；
2. 每一步说明需要完成的任务；
3. 缺少的数据应写成“需要补充或核实”，不能自行编造；
4. 不直接给出项目合规或不合规的最终结论。
"""

    return chat(
        prompt,
        system_message=SYSTEM_MESSAGE,
    )


def main() -> None:
    requirement = """
计划建设一个占地30公顷的物流园，
目前有两个候选地块，
需要比较交通条件，并检查是否涉及生态保护红线、
永久基本农田和城镇开发边界。
"""

    plan = create_site_selection_plan(requirement)
    print(plan)


if __name__ == "__main__":
    main()
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .context import ConversationContext


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"缺少环境变量：{name}")

    return value


def chat(
    user_message: str,
    context: ConversationContext | None = None,
    system_message: str = "你是一名建设项目选址合规审查助手。",
) -> str:
    if not user_message.strip():
        raise ValueError("用户消息不能为空")

    client = OpenAI(
        api_key=get_required_env("LLM_API_KEY"),
        base_url=get_required_env("LLM_BASE_URL"),
        timeout=60.0,
    )

    if context is None:
        model_input = user_message
    else:
        model_input = context.build_input(user_message)

    response = client.responses.create(
        model=get_required_env("LLM_MODEL"),
        instructions=system_message,
        input=model_input,
    )

    content = response.output_text.strip()

    if not content:
        raise RuntimeError("模型返回了空内容")

    if context is not None:
        context.add_round(user_message, content)

    return content


def main() -> None:
    context = ConversationContext(max_rounds=2)

    questions = [
        "请记住：当前候选地块编号是 A01。",
        "我刚才提供的候选地块编号是什么？",
    ]

    for question in questions:
        print(f"用户：{question}")
        answer = chat(question, context=context)
        print(f"模型：{answer}")
        print()


if __name__ == "__main__":
    main()
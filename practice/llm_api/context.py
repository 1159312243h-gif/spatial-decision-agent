from collections import deque


class ConversationContext:
    def __init__(self, max_rounds: int = 3) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds 必须大于等于 1")

        self.max_rounds = max_rounds
        self._rounds: deque[tuple[str, str]] = deque(
            maxlen=max_rounds
        )

    def add_round(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        if not user_message.strip():
            raise ValueError("用户消息不能为空")

        if not assistant_message.strip():
            raise ValueError("模型回复不能为空")

        self._rounds.append(
            (user_message, assistant_message)
        )

    def build_input(
        self,
        current_user_message: str,
    ) -> list[dict[str, str]]:
        if not current_user_message.strip():
            raise ValueError("当前用户消息不能为空")

        messages: list[dict[str, str]] = []

        for user_message, assistant_message in self._rounds:
            messages.append({
                "role": "user",
                "content": user_message,
            })
            messages.append({
                "role": "assistant",
                "content": assistant_message,
            })

        messages.append({
            "role": "user",
            "content": current_user_message,
        })

        return messages

    def __len__(self) -> int:
        return len(self._rounds)
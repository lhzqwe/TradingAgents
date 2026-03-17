import inspect
import json
import uuid
from types import SimpleNamespace
from typing import Any, Optional

import requests
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.auth import (
    OpenAICodexAuthError,
    OpenAICodexReauthRequiredError,
    get_active_openai_codex_profile,
    refresh_openai_codex_profile,
)
from tradingagents.auth.constants import OPENAI_CODEX_RESPONSES_URL

from .base_client import BaseLLMClient
from .validators import validate_model


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(content)


def _message_to_input_items(message: BaseMessage) -> list[dict[str, Any]]:
    text = _extract_text_content(getattr(message, "content", None)).strip()

    if isinstance(message, SystemMessage):
        return [
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": text}],
            }
        ] if text else []

    if isinstance(message, HumanMessage):
        return [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        ] if text else []

    if isinstance(message, ToolMessage):
        call_id = getattr(message, "tool_call_id", None) or getattr(message, "id", None)
        return [
            {
                "type": "function_call_output",
                "call_id": str(call_id or f"call_{uuid.uuid4().hex}"),
                "output": text,
            }
        ]

    items: list[dict[str, Any]] = []
    if text:
        items.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "input_text", "text": text}],
            }
        )

    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        items.append(
            {
                "type": "function_call",
                "call_id": tool_call.get("id") or f"call_{uuid.uuid4().hex}",
                "name": tool_call.get("name"),
                "arguments": json.dumps(tool_call.get("args", {})),
            }
        )
    return items


def _dict_message_to_instruction_and_items(
    message: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]]]:
    role = str(message.get("role") or "").strip().lower()
    text = _extract_text_content(message.get("content")).strip()
    tool_calls = message.get("tool_calls") or []

    if role == "system":
        return text or None, []

    items: list[dict[str, Any]] = []
    if role in {"user", "assistant"} and text:
        items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            }
        )

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        items.append(
            {
                "type": "function_call",
                "call_id": tool_call.get("id") or f"call_{uuid.uuid4().hex}",
                "name": tool_call.get("name"),
                "arguments": json.dumps(tool_call.get("args", {})),
            }
        )

    return None, items


def _tuple_message_to_instruction_and_items(
    message: tuple[Any, ...],
) -> tuple[str | None, list[dict[str, Any]]]:
    if len(message) < 2:
        return None, []

    role = str(message[0] or "").strip().lower()
    if role == "human":
        role = "user"
    elif role in {"ai", "assistant"}:
        role = "assistant"

    text = _extract_text_content(message[1]).strip()
    if role == "system":
        return text or None, []

    if role not in {"user", "assistant"} or not text:
        return None, []

    return None, [
        {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        }
    ]


def _input_to_items(input_value: Any) -> list[dict[str, Any]]:
    _, items = _input_to_instructions_and_items(input_value)
    return items


def _input_to_instructions_and_items(input_value: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if hasattr(input_value, "to_messages"):
        input_value = input_value.to_messages()

    if isinstance(input_value, str):
        return None, _message_to_input_items(HumanMessage(content=input_value))

    if isinstance(input_value, list):
        instructions: list[str] = []
        items: list[dict[str, Any]] = []
        for message in input_value:
            if isinstance(message, BaseMessage):
                if isinstance(message, SystemMessage):
                    text = _extract_text_content(getattr(message, "content", None)).strip()
                    if text:
                        instructions.append(text)
                    continue
                items.extend(_message_to_input_items(message))
                continue
            if isinstance(message, dict):
                instruction, dict_items = _dict_message_to_instruction_and_items(message)
                if instruction:
                    instructions.append(instruction)
                items.extend(dict_items)
                continue
            if isinstance(message, tuple):
                instruction, tuple_items = _tuple_message_to_instruction_and_items(message)
                if instruction:
                    instructions.append(instruction)
                items.extend(tuple_items)
        instruction_text = "\n\n".join(part for part in instructions if part).strip()
        return instruction_text or None, items

    if isinstance(input_value, dict):
        instruction, items = _dict_message_to_instruction_and_items(input_value)
        return instruction, items

    if isinstance(input_value, tuple):
        instruction, items = _tuple_message_to_instruction_and_items(input_value)
        return instruction, items

    raise TypeError(f"Unsupported OpenAI Codex input type: {type(input_value)!r}")


def _schema_from_tool(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        if hasattr(args_schema, "model_json_schema"):
            schema = args_schema.model_json_schema()
        elif hasattr(args_schema, "schema"):
            schema = args_schema.schema()
        else:
            schema = {"type": "object", "properties": {}}
    else:
        schema = {"type": "object", "properties": {}}

    name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
    description = getattr(tool, "description", None) or inspect.getdoc(tool) or ""

    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": schema,
    }


def _build_tool_payload(tools: list[Any]) -> list[dict[str, Any]]:
    return [_schema_from_tool(tool) for tool in tools]


def _extract_output_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"output_text", "input_text", "text"}:
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(part for part in parts if part).strip()


def _parse_tool_calls(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in response_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"function_call", "tool_call"}:
            continue
        raw_arguments = item.get("arguments", {})
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            arguments = {}
        tool_calls.append(
            {
                "name": item.get("name"),
                "args": arguments,
                "id": item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex}",
                "type": "tool_call",
            }
        )
    return tool_calls


def _build_ai_message(response_json: dict[str, Any]) -> AIMessage:
    texts: list[str] = []
    for item in response_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" or item.get("role") == "assistant":
            text = _extract_output_text(item)
            if text:
                texts.append(text)

    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        texts.append(output_text.strip())

    usage = response_json.get("usage", {}) if isinstance(response_json.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    usage_metadata = None
    if isinstance(input_tokens, int) or isinstance(output_tokens, int):
        usage_metadata = {
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(
                usage.get("total_tokens")
                or int(input_tokens or 0) + int(output_tokens or 0)
            ),
        }

    return AIMessage(
        content="\n".join(texts).strip(),
        tool_calls=_parse_tool_calls(response_json),
        usage_metadata=usage_metadata,
        response_metadata={
            "id": response_json.get("id"),
            "model": response_json.get("model"),
        },
    )


def _extract_error_detail(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message") or error.get("code") or json.dumps(error)
    if error:
        return str(error)
    message = payload.get("message")
    if isinstance(message, str) and message:
        return message
    return json.dumps(payload)


def _normalize_sse_line(raw_line: Any) -> str:
    if isinstance(raw_line, bytes):
        return raw_line.decode("utf-8", errors="replace")
    return str(raw_line)


def _parse_sse_response(response: requests.Response) -> dict[str, Any]:
    event_name: str | None = None
    data_lines: list[str] = []
    last_response: dict[str, Any] | None = None

    def flush_event() -> dict[str, Any] | None:
        nonlocal event_name, data_lines, last_response
        if not data_lines:
            return None

        raw_data = "\n".join(data_lines).strip()
        event_name = event_name or ""
        data_lines = []

        if not raw_data or raw_data == "[DONE]":
            return None

        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = {"message": raw_data}

        response_payload = payload.get("response")
        if isinstance(response_payload, dict):
            last_response = response_payload

        event_type = payload.get("type") or event_name
        if event_type == "response.completed" and isinstance(response_payload, dict):
            return response_payload

        if event_type in {"response.failed", "error"}:
            raise OpenAICodexAuthError(
                f"OpenAI Codex request failed: {_extract_error_detail(payload)}"
            )

        return None

    for raw_line in response.iter_lines():
        line = _normalize_sse_line(raw_line).strip()
        if not line:
            completed = flush_event()
            if completed is not None:
                return completed
            event_name = None
            continue

        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue

        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    completed = flush_event()
    if completed is not None:
        return completed

    if last_response is not None:
        if last_response.get("status") == "completed":
            return last_response
        raise OpenAICodexAuthError(
            f"OpenAI Codex stream ended before completion: {last_response.get('status')}"
        )

    raise OpenAICodexAuthError("OpenAI Codex stream ended without a completed response.")


class OpenAICodexChatModel:
    """Minimal ChatGPT OAuth-backed responses client for TradingAgents."""

    def __init__(
        self,
        model: str,
        auth_profile_id: str | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        callbacks: Optional[list[Any]] = None,
        endpoint: str = OPENAI_CODEX_RESPONSES_URL,
    ):
        self.model = model
        self.auth_profile_id = auth_profile_id
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout or 120
        self.max_retries = max_retries or 1
        self.callbacks = callbacks or []
        self.endpoint = endpoint

    def bind_tools(self, tools: list[Any], tool_choice: Any = "auto") -> RunnableLambda:
        return RunnableLambda(
            lambda input_value, config=None, **kwargs: self.invoke(
                input_value,
                config=config,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
        )

    def _build_payload(
        self,
        input_value: Any,
        tools: list[Any] | None = None,
        tool_choice: Any = None,
    ) -> dict[str, Any]:
        instructions, items = _input_to_instructions_and_items(input_value)
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions or "You are a helpful assistant.",
            "input": items,
            "stream": True,
            "store": False,
        }

        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        if tools:
            payload["tools"] = _build_tool_payload(tools)
            payload["tool_choice"] = tool_choice or "auto"

        return payload

    def _notify_start(self, messages: list[BaseMessage]) -> None:
        serialized = {"name": "OpenAICodexChatModel", "model": self.model}
        for callback in self.callbacks:
            handler = getattr(callback, "on_chat_model_start", None)
            if callable(handler):
                try:
                    handler(serialized, [messages])
                except Exception:
                    continue

    def _notify_end(self, response_message: AIMessage) -> None:
        fake_result = SimpleNamespace(
            generations=[[SimpleNamespace(message=response_message)]]
        )
        for callback in self.callbacks:
            handler = getattr(callback, "on_llm_end", None)
            if callable(handler):
                try:
                    handler(fake_result)
                except Exception:
                    continue

    def _post(self, payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {profile['access']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "TradingAgents/0.2.1",
        }
        account_id = profile.get("account_id")
        if isinstance(account_id, str) and account_id:
            headers["ChatGPT-Account-Id"] = account_id

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise OpenAICodexAuthError(f"OpenAI Codex request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text}

        if response.status_code == 401:
            raise OpenAICodexReauthRequiredError("OpenAI Codex OAuth access token was rejected.")

        if response.status_code >= 400:
            error = body.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or "Unknown error"
            else:
                message = body.get("message") or error or response.text
            raise OpenAICodexAuthError(f"OpenAI Codex request failed: {message}")

        return _parse_sse_response(response)

    def invoke(self, input_value: Any, config=None, **kwargs) -> AIMessage:
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        payload = self._build_payload(input_value, tools=tools, tool_choice=tool_choice)

        messages = input_value.to_messages() if hasattr(input_value, "to_messages") else input_value
        if isinstance(messages, list):
            normalized_messages = [m for m in messages if isinstance(m, BaseMessage)]
        else:
            normalized_messages = [HumanMessage(content=str(input_value))]
        self._notify_start(normalized_messages)

        profile_id, profile = get_active_openai_codex_profile(self.auth_profile_id)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response_json = self._post(payload, profile)
                message = _build_ai_message(response_json)
                self._notify_end(message)
                return message
            except OpenAICodexReauthRequiredError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                try:
                    profile_id, profile = refresh_openai_codex_profile(
                        profile_id,
                        force=True,
                    )
                except OpenAICodexReauthRequiredError as refresh_exc:
                    last_error = refresh_exc
                    break

        raise OpenAICodexReauthRequiredError(
            "OpenAI Codex OAuth credentials are no longer valid. "
            "Run `tradingagents auth login --provider openai-codex` and try again."
        ) from last_error


class OpenAICodexClient(BaseLLMClient):
    """Client for ChatGPT OAuth-backed OpenAI Codex responses."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        llm_kwargs = {
            "model": self.model,
            "auth_profile_id": self.kwargs.get("auth_profile_id"),
            "reasoning_effort": self.kwargs.get("reasoning_effort"),
            "timeout": self.kwargs.get("timeout"),
            "max_retries": self.kwargs.get("max_retries"),
            "callbacks": self.kwargs.get("callbacks"),
        }
        return OpenAICodexChatModel(**llm_kwargs)

    def validate_model(self) -> bool:
        return validate_model("openai-codex", self.model)

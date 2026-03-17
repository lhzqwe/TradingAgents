import unittest
from unittest.mock import patch

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise unittest.SkipTest(f"langchain_core is not installed: {exc}") from exc

from tradingagents.auth import OpenAICodexReauthRequiredError
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.openai_client import OpenAIClient
from tradingagents.llm_clients.openai_codex_client import (
    OpenAICodexChatModel,
    OpenAICodexClient,
    _parse_sse_response,
)


class OpenAICodexClientTests(unittest.TestCase):
    def test_factory_routes_openai_codex_to_dedicated_client(self) -> None:
        codex_client = create_llm_client("openai-codex", "gpt-5.4")
        openai_client = create_llm_client("openai", "gpt-5.4")

        self.assertIsInstance(codex_client, OpenAICodexClient)
        self.assertIsInstance(openai_client, OpenAIClient)

    def test_text_response_maps_to_ai_message_content(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4")
        response_json = {
            "id": "resp_1",
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello world"}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
        }

        with patch(
            "tradingagents.llm_clients.openai_codex_client.get_active_openai_codex_profile",
            return_value=("openai-codex:default", {"access": "token", "refresh": "refresh"}),
        ), patch.object(model, "_post", return_value=response_json):
            result = model.invoke("hello")

        self.assertIsInstance(result, AIMessage)
        self.assertEqual(result.content, "hello world")
        self.assertEqual(result.usage_metadata["input_tokens"], 11)

    def test_tool_call_response_maps_to_ai_message_tool_calls(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4")
        response_json = {
            "id": "resp_2",
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "get_stock_data",
                    "arguments": "{\"symbol\":\"NVDA\"}",
                }
            ],
        }

        with patch(
            "tradingagents.llm_clients.openai_codex_client.get_active_openai_codex_profile",
            return_value=("openai-codex:default", {"access": "token", "refresh": "refresh"}),
        ), patch.object(model, "_post", return_value=response_json):
            result = model.invoke("fetch data")

        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]["name"], "get_stock_data")
        self.assertEqual(result.tool_calls[0]["args"]["symbol"], "NVDA")

    def test_payload_moves_system_messages_to_instructions(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4")

        payload = model._build_payload(
            [
                SystemMessage(content="Act as a market analyst."),
                HumanMessage(content="Summarize NVDA."),
            ]
        )

        self.assertEqual(payload["instructions"], "Act as a market analyst.")
        self.assertTrue(payload["stream"])
        self.assertFalse(payload["store"])
        self.assertEqual(len(payload["input"]), 1)
        self.assertEqual(payload["input"][0]["role"], "user")

    def test_payload_supports_dict_messages(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4")

        payload = model._build_payload(
            [
                {"role": "system", "content": "Act as a trader."},
                {"role": "user", "content": "Make a decision."},
            ]
        )

        self.assertEqual(payload["instructions"], "Act as a trader.")
        self.assertEqual(len(payload["input"]), 1)
        self.assertEqual(payload["input"][0]["role"], "user")

    def test_payload_supports_tuple_messages(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4")

        payload = model._build_payload(
            [
                ("system", "Extract only the final action."),
                ("human", "Recommendation: SELL"),
            ]
        )

        self.assertEqual(payload["instructions"], "Extract only the final action.")
        self.assertEqual(len(payload["input"]), 1)
        self.assertEqual(payload["input"][0]["role"], "user")

    def test_sse_parser_returns_completed_response(self) -> None:
        class FakeResponse:
            def iter_lines(self):
                yield b"event: response.created"
                yield b'data: {"type":"response.created","response":{"id":"resp_1","status":"in_progress"}}'
                yield b""
                yield b"event: response.completed"
                yield (
                    b'data: {"type":"response.completed","response":{"id":"resp_1","status":"completed","model":"gpt-5.4","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello!"}]}]}}'
                )
                yield b""

        parsed = _parse_sse_response(FakeResponse())

        self.assertEqual(parsed["id"], "resp_1")
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(parsed["output"][0]["role"], "assistant")

    def test_refresh_failure_raises_clear_reauth_error(self) -> None:
        model = OpenAICodexChatModel(model="gpt-5.4", max_retries=1)

        with patch(
            "tradingagents.llm_clients.openai_codex_client.get_active_openai_codex_profile",
            return_value=("openai-codex:default", {"access": "token", "refresh": "refresh"}),
        ), patch.object(
            model,
            "_post",
            side_effect=OpenAICodexReauthRequiredError("expired"),
        ), patch(
            "tradingagents.llm_clients.openai_codex_client.refresh_openai_codex_profile",
            side_effect=OpenAICodexReauthRequiredError("refresh failed"),
        ):
            with self.assertRaises(OpenAICodexReauthRequiredError) as ctx:
                model.invoke("hello")

        self.assertIn("auth login", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

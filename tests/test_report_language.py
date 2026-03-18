import unittest

from langchain_core.messages import HumanMessage

from tradingagents.llm_clients.report_language import (
    ReportLanguageLLM,
    normalize_report_language,
)


class _FakeRunnable:
    def __init__(self):
        self.last_input = None

    def invoke(self, input_value, config=None, **kwargs):
        self.last_input = input_value
        return input_value


class _FakeLLM:
    def __init__(self):
        self.last_input = None
        self.bound = _FakeRunnable()

    def invoke(self, input_value, config=None, **kwargs):
        self.last_input = input_value
        return input_value

    def bind_tools(self, tools, *args, **kwargs):
        return self.bound


class _FakePromptValue:
    def to_messages(self):
        return [HumanMessage(content="Analyze AMD.")]


class ReportLanguageTests(unittest.TestCase):
    def test_normalize_report_language_aliases(self):
        self.assertEqual(normalize_report_language("english"), "english")
        self.assertEqual(normalize_report_language("zh-CN"), "chinese")
        self.assertEqual(normalize_report_language("中文"), "chinese")

    def test_wrapper_prepends_system_message_for_string_input(self):
        fake_llm = _FakeLLM()
        wrapped = ReportLanguageLLM(fake_llm, "chinese")

        wrapped.invoke("Analyze AMD.")

        self.assertEqual(len(fake_llm.last_input), 2)
        self.assertEqual(fake_llm.last_input[0].type, "system")
        self.assertIn("Simplified Chinese", fake_llm.last_input[0].content)
        self.assertEqual(fake_llm.last_input[1].type, "human")

    def test_wrapper_supports_dict_message_lists(self):
        fake_llm = _FakeLLM()
        wrapped = ReportLanguageLLM(fake_llm, "english")

        wrapped.invoke([{"role": "user", "content": "Analyze AMD."}])

        self.assertEqual(fake_llm.last_input[0]["role"], "system")
        self.assertEqual(fake_llm.last_input[1]["role"], "user")

    def test_wrapper_supports_prompt_values(self):
        fake_llm = _FakeLLM()
        wrapped = ReportLanguageLLM(fake_llm, "chinese")

        wrapped.invoke(_FakePromptValue())

        self.assertEqual(fake_llm.last_input[0].type, "system")
        self.assertEqual(fake_llm.last_input[1].type, "human")

    def test_wrapper_supports_tuple_message_lists_for_bound_tools(self):
        fake_llm = _FakeLLM()
        wrapped = ReportLanguageLLM(fake_llm, "chinese")
        bound = wrapped.bind_tools([])

        bound.invoke([("human", "Analyze AMD.")])

        self.assertEqual(fake_llm.bound.last_input[0][0], "system")
        self.assertEqual(fake_llm.bound.last_input[1][0], "human")


if __name__ == "__main__":
    unittest.main()

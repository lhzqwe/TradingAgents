from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda


REPORT_LANGUAGE_ALIASES = {
    "english": "english",
    "en": "english",
    "en-us": "english",
    "en_us": "english",
    "chinese": "chinese",
    "zh": "chinese",
    "zh-cn": "chinese",
    "zh_cn": "chinese",
    "中文": "chinese",
    "简体中文": "chinese",
}


REPORT_LANGUAGE_DIRECTIVES = {
    "english": (
        "Output every user-facing report, debate argument, recommendation, "
        "rationale, bullet list, and Markdown table in English. Keep stock "
        "tickers, company names, dates, raw numeric values, tool names, and any "
        "explicitly required fixed labels such as `FINAL TRANSACTION PROPOSAL: "
        "**BUY/HOLD/SELL**` unchanged."
    ),
    "chinese": (
        "Output every user-facing report, debate argument, recommendation, "
        "rationale, bullet list, and Markdown table in Simplified Chinese. Keep "
        "stock tickers, company names, dates, raw numeric values, tool names, "
        "and any explicitly required fixed labels such as `FINAL TRANSACTION "
        "PROPOSAL: **BUY/HOLD/SELL**` unchanged."
    ),
}


def normalize_report_language(value: str | None) -> str:
    if value is None:
        return "english"

    normalized = REPORT_LANGUAGE_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(
            "Unsupported report language. Choose one of: english, chinese."
        )
    return normalized


def _with_language_instruction(input_value: Any, report_language: str) -> Any:
    directive = REPORT_LANGUAGE_DIRECTIVES[normalize_report_language(report_language)]

    if hasattr(input_value, "to_messages"):
        input_value = input_value.to_messages()

    if isinstance(input_value, str):
        return [
            SystemMessage(content=directive),
            HumanMessage(content=input_value),
        ]

    if isinstance(input_value, list):
        if not input_value:
            return [SystemMessage(content=directive)]

        first_item = input_value[0]
        if isinstance(first_item, tuple):
            return [("system", directive), *input_value]
        if isinstance(first_item, dict):
            return [{"role": "system", "content": directive}, *input_value]
        return [SystemMessage(content=directive), *input_value]

    if isinstance(input_value, tuple):
        return [("system", directive), input_value]

    if isinstance(input_value, dict):
        return [{"role": "system", "content": directive}, input_value]

    return input_value


class ReportLanguageLLM:
    """Wrap an LLM so all user-facing reports follow the configured language."""

    def __init__(self, llm: Any, report_language: str):
        self.llm = llm
        self.report_language = normalize_report_language(report_language)

    def invoke(self, input_value: Any, config=None, **kwargs):
        return self.llm.invoke(
            _with_language_instruction(input_value, self.report_language),
            config=config,
            **kwargs,
        )

    def bind_tools(self, tools: list[Any], *args, **kwargs):
        bound = self.llm.bind_tools(tools, *args, **kwargs)
        return RunnableLambda(
            lambda input_value, config=None, **inner_kwargs: bound.invoke(
                _with_language_instruction(input_value, self.report_language),
                config=config,
                **inner_kwargs,
            )
        )


def wrap_llm_for_report_language(llm: Any, report_language: str | None):
    normalized = normalize_report_language(report_language)
    if normalized == "english":
        return ReportLanguageLLM(llm, normalized)
    return ReportLanguageLLM(llm, normalized)

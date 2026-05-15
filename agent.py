from __future__ import annotations

import json
import os
from typing import Any
from openai import OpenAI

from memory import SessionMemory
from data_loader import PropertyDataStore
from tools import OPENAI_TOOL_SCHEMAS, TOOL_FUNCTIONS


SYSTEM_PROMPT = “””
You are UrbanTrace Research Assistant, an AI assistant for exploring structured Cluj-Napoca property data.

Core rules:
1. Use tools for any factual answer about properties, owners, transactions, or market statistics.
2. Never invent property data. Final answers must be grounded in tool results.
3. If a tool returns no results, say that clearly and suggest a useful next filter.
4. If the user asks for data that is not available, explain the limitation instead of guessing.
5. For ambiguous requests, ask one concise clarification question unless a safe assumption is obvious.
6. Preserve multi-turn context. If the user says “what about Gheorgheni?” reuse relevant prior filters and only change the requested field.
7. The dataset uses neighborhood (cartier) and ZIP as geographic fields. Some sub-area names are approximated with explicit ZIP mappings; disclose that caveat.
8. When showing property rows, show at most 8 rows in Markdown. Always include sample size and filters/caveats when relevant.
9. Area is measured in square meters (mp) and prices are in RON (Romanian Leu). 1 EUR ≈ 5 RON.
“””.strip()


class PropertyAssistant:
    def __init__(self, store: PropertyDataStore, model: str | None = None):
        self.store = store
        self.client = OpenAI()
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.last_tool_args: dict[str, Any] = {}
        self.memory = SessionMemory()

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_FUNCTIONS:
            return {
                "status": "error",
                "message": f"Unknown tool: {name}",
                "data": [],
                "metadata": {},
            }

        func = TOOL_FUNCTIONS[name]

        try:
            if name == "describe_schema":
                result = func(self.store)
            else:
                result = func(self.store, **arguments)

            self.last_tool_args[name] = arguments

            if result.get("status") != "error":
                self.memory.update(
                    tool=name,
                    params=arguments,
                    results=result.get("data"),
                )

            return result

        except Exception as exc:
            return {
                "status": "error",
                "message": f"Tool {name} failed: {exc}",
                "data": [],
                "metadata": {},
            }

    def _handle_simple_followup(self, user_text: str) -> str | None:
        text = user_text.strip().lower()

        if not text.startswith("what about"):
            return None

        last = self.memory.get()
        if not last:
            return None

        raw_value = (
            user_text.strip()
            .replace("?", "")
            .lower()
            .split("what about", 1)[-1]
            .strip()
        )

        if not raw_value:
            return None

        query_type = last.get("last_tool")
        params = dict(last.get("filters", {}))

        if not query_type:
            return None

        known_boroughs = {
            "marasti": "Mărăști",
            "mărăști": "Mărăști",
            "gheorgheni": "Gheorgheni",
            "manastur": "Mănăștur",
            "mănăștur": "Mănăștur",
            "floresti": "Florești",
            "florești": "Florești",
            "grigorescu": "Grigorescu",
            "zorilor": "Zorilor",
            "buna ziua": "Bună Ziua",
            "bună ziua": "Bună Ziua",
            "sopor": "Sopor",
            "europa": "Europa",
            "borhanci": "Borhanci",
            "dambul rotund": "Dâmbul Rotund",
            "dâmbul rotund": "Dâmbul Rotund",
            "intre lacuri": "Între Lacuri",
            "între lacuri": "Între Lacuri",
            "iris": "Iris",
            "someseni": "Someșeni",
            "someșeni": "Someșeni",
            "baciu": "Baciu",
        }

        normalized = known_boroughs.get(raw_value)
        if not normalized:
            return None

        # Reuse prior filters and only swap borough.
        if "borough" in params:
            params["borough"] = normalized
        elif "boroughs" in params:
            params["boroughs"] = [normalized]
        else:
            params["borough"] = normalized

        result = self._execute_tool(query_type, params)

        # Do not append a fake tool message here; Chat Completions requires
        # tool messages to correspond to real tool_call IDs. Instead, pass the
        # follow-up result as plain assistant context.
        final_messages = self.messages + [
            {
                "role": "assistant",
                "content": (
                    "Latest tool result for the user's follow-up:\n"
                    f"Tool: {query_type}\n"
                    f"Filters: {json.dumps(params, default=str)}\n"
                    f"Result: {json.dumps(result, default=str)}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Answer the user's follow-up using this latest tool result. "
                    "Preserve the prior metric/filter context and explain the changed borough. "
                    "Do not invent property data."
                ),
            },
        ]

        final = self.client.chat.completions.create(
            model=self.model,
            messages=final_messages,
            temperature=0.1,
        )

        answer = final.choices[0].message.content or "I could not generate a response."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})

        followup_answer = self._handle_simple_followup(user_text)
        if followup_answer:
            return followup_answer

        first = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=OPENAI_TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.1,
        )

        assistant_msg = first.choices[0].message
        self.messages.append(assistant_msg.model_dump())

        if assistant_msg.tool_calls:
            for tool_call in assistant_msg.tool_calls:
                name = tool_call.function.name

                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                result = self._execute_tool(name, args)

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": json.dumps(result, default=str),
                    }
                )

            final = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                temperature=0.1,
            )

            answer = final.choices[0].message.content or "I could not generate a response."
            self.messages.append({"role": "assistant", "content": answer})
            return answer

        answer = assistant_msg.content or "I need one more detail to answer that."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

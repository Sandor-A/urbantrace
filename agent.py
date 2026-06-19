from __future__ import annotations

import difflib
import json
import os
from typing import Any
from openai import OpenAI

from memory import SessionMemory
from data_loader import PropertyDataStore
from tools import OPENAI_TOOL_SCHEMAS, TOOL_FUNCTIONS, BOROUGH_ALIASES, _normalize_addr


SYSTEM_PROMPT = """
You are Brick, the UrbanTrace property research assistant for Cluj-Napoca.
You have access to a real database of 500 properties with ownership records and sale transactions.

STRICT RULES — never break these:
1. Every factual answer (prices, addresses, owners, statistics) MUST come from a tool result.
   If you have not called a tool yet, call one before answering.
2. NEVER invent, estimate, or extrapolate property data. If the tool returns no results,
   say exactly that — do not fill in with guesses or general knowledge.
3. If a tool returns status "empty", tell the user plainly: no records found for those filters,
   then suggest one concrete alternative (e.g., broaden the search, try a nearby neighborhood).
4. Address searches use substring matching. For "Tell me about X" queries always call BOTH:
   - lookup_owner(address=<street name only>) for ownership
   - search_properties(borough=<hood>) for recent transactions in the area
5. If the user's question is ambiguous, ask ONE short clarifying question — do not guess.
6. Multi-turn: if the user says "what about Gheorgheni?" keep all prior filters and swap only the borough.
7. Format: show max 8 property rows in a Markdown table. Always state the total match count
   and any caveats (e.g., "$0 sales excluded", "results capped at 12").
8. Units: area in m², prices in RON. Approximate: 1 EUR ~ 5 RON.
9. Available neighborhoods: Centru, Grigorescu, Marasti, Manastur, Gheorgheni, Zorilor,
   Europa, Iris, Buna Ziua, Floresti, Dambul Rotund, Someseni.
10. TYPO CORRECTION: If the tool result caveats contain a "Did you mean" or "Closest matches"
    suggestion (for neighborhood, address, or owner name), present those options to the user
    and ask which one they meant. Do not guess — always confirm before re-searching.
""".strip()


_RO_KEYWORDS = frozenset([
    "cartier", "proprietar", "vanzare", "cumparare", "apartament",
    "imobil", "pretul", "cat costa", "cine detine", "arata-mi",
    "spune-mi", "cel mai ieftin", "cele mai", "zona de",
])

_HU_KEYWORDS = frozenset([
    "negyed", "ingatlan", "elad", "mennyibe", "tulajdonos",
    "legolcsobb", "legdragabb", "kolozs",
])


def _detect_language(text: str) -> str:
    """Detect language: diacritics first, then keyword fallback."""
    lower = text.lower()
    # Hungarian diacritics are unambiguous
    if any(c in lower for c in "őű"):
        return "hu"
    # Romanian diacritics are unambiguous
    if any(c in lower for c in "ășțâî"):
        return "ro"
    # Keyword fallback for diacritic-free typing
    if any(kw in lower for kw in _RO_KEYWORDS):
        return "ro"
    if any(kw in lower for kw in _HU_KEYWORDS):
        return "hu"
    return "en"


_LANG_INSTRUCTIONS: dict[str, str] = {
    "hu": "IMPORTANT: The user wrote in Hungarian. Your entire response MUST be in Hungarian.",
    "ro": "IMPORTANT: Utilizatorul a scris în română. Răspunde integral în limba română.",
}


def _suggest_borough(raw: str) -> list[str]:
    """Return canonical borough names fuzzy-close to `raw` (typo correction)."""
    matches = difflib.get_close_matches(raw.lower(), BOROUGH_ALIASES.keys(), n=3, cutoff=0.6)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        canonical = BOROUGH_ALIASES[m]
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _suggest_address(raw: str, store: PropertyDataStore) -> list[str]:
    """Fuzzy-match `raw` against all known property addresses."""
    raw_norm = _normalize_addr(raw)
    norm_to_orig: dict[str, str] = {}
    for p in store.properties:
        addr = str(p.get("address", "")).strip()
        if addr:
            norm_to_orig.setdefault(_normalize_addr(addr), addr)
    matches = difflib.get_close_matches(raw_norm, norm_to_orig.keys(), n=3, cutoff=0.55)
    return [norm_to_orig[m] for m in matches]


def _suggest_owner(raw: str, store: PropertyDataStore) -> list[str]:
    """Fuzzy-match `raw` against all known owner names."""
    raw_lower = raw.lower()
    lower_to_orig: dict[str, str] = {}
    for o in store.ownership:
        name = str(o.get("owner_name", "")).strip()
        if name:
            lower_to_orig.setdefault(name.lower(), name)
    matches = difflib.get_close_matches(raw_lower, lower_to_orig.keys(), n=3, cutoff=0.6)
    return [lower_to_orig[m] for m in matches]


def _inject_borough_suggestions(result: dict[str, Any], args: dict[str, Any]) -> None:
    """If result is empty and a borough arg was supplied, add fuzzy suggestions to caveats."""
    if result.get("status") != "empty":
        return

    raw_borough = args.get("borough") or args.get("neighborhood")
    if not raw_borough:
        return

    # Skip if the borough was already a valid exact alias
    if raw_borough.strip().lower() in BOROUGH_ALIASES:
        return

    suggestions = _suggest_borough(raw_borough)
    if not suggestions:
        return

    caveats: list[str] = result.get("caveats", [])
    caveats.append(
        f"Did you mean one of these neighborhoods? {', '.join(suggestions)} "
        f"(your input: \"{raw_borough}\")"
    )
    result["caveats"] = caveats


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

            _inject_borough_suggestions(result, arguments)

            if result.get("status") == "empty" and name == "lookup_owner":
                caveats: list[str] = result.get("caveats", [])
                raw_addr = arguments.get("address")
                if raw_addr:
                    addr_hits = _suggest_address(raw_addr, self.store)
                    if addr_hits:
                        caveats.append(
                            f"Address not found. Closest matches: {'; '.join(addr_hits)} "
                            f"(you searched: \"{raw_addr}\")"
                        )
                raw_owner = arguments.get("owner_name_contains")
                if raw_owner:
                    owner_hits = _suggest_owner(raw_owner, self.store)
                    if owner_hits:
                        caveats.append(
                            f"Owner not found. Closest matches: {'; '.join(owner_hits)} "
                            f"(you searched: \"{raw_owner}\")"
                        )
                if caveats:
                    result["caveats"] = caveats

            return result

        except Exception as exc:
            return {
                "status": "error",
                "message": f"Tool {name} failed: {exc}",
                "data": [],
                "metadata": {},
            }

    def _handle_simple_followup(self, user_text: str, turn_messages: list[dict[str, Any]]) -> str | None:
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
        final_messages = turn_messages + [
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
            temperature=0,
        )

        answer = final.choices[0].message.content or "I could not generate a response."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})

        # Build per-turn messages with language instruction injected into system prompt
        lang = _detect_language(user_text)
        lang_note = _LANG_INSTRUCTIONS.get(lang)
        if lang_note:
            system_content = self.messages[0]["content"] + f"\n\n{lang_note}"
            turn_messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_content},
                *self.messages[1:],
            ]
        else:
            turn_messages = self.messages

        followup_answer = self._handle_simple_followup(user_text, turn_messages)
        if followup_answer:
            return followup_answer

        # Detect purely conversational messages that don't need a tool call
        _factual_keywords = (
            "price", "owner", "sale", "property", "address", "borough",
            "neighborhood", "cartier", "strada", "bulevardul", "calea",
            "street", "sqm", "median", "average", "srl", "tell me about",
            "who owns", "how much", "what is", "show me", "list",
        )
        needs_tool = any(kw in user_text.lower() for kw in _factual_keywords)
        tool_choice = "required" if needs_tool else "auto"

        first = self.client.chat.completions.create(
            model=self.model,
            messages=turn_messages,
            tools=OPENAI_TOOL_SCHEMAS,
            tool_choice=tool_choice,
            temperature=0,
        )

        assistant_msg = first.choices[0].message
        self.messages.append(assistant_msg.model_dump())

        if assistant_msg.tool_calls:
            # Build updated turn_messages to include the assistant's tool_call message
            if lang_note:
                turn_messages = [
                    {"role": "system", "content": system_content},
                    *self.messages[1:],
                ]
            else:
                turn_messages = self.messages

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

            # Rebuild turn_messages with tool results included
            if lang_note:
                turn_messages = [
                    {"role": "system", "content": system_content},
                    *self.messages[1:],
                ]
            else:
                turn_messages = self.messages

            final = self.client.chat.completions.create(
                model=self.model,
                messages=turn_messages,
                temperature=0,
            )

            answer = final.choices[0].message.content or "I could not generate a response."
            self.messages.append({"role": "assistant", "content": answer})
            return answer

        # No tool call — only acceptable for pure greetings / meta questions
        answer = assistant_msg.content or "I need one more detail to answer that."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

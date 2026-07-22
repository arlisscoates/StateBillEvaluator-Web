"""Claude API client — port of ClaudeService.swift.

Keeps the original app's model id, token limits, and prompt intent.
"""
import json

import anthropic

from models import PREDEFINED_CATEGORIES

MODEL = "claude-sonnet-4-5-20250929"  # same model the macOS app used


class ClaudeError(Exception):
    pass


class ClaudeService:
    def __init__(self, api_key: str):
        key = (api_key or "").strip()
        if not key:
            raise ClaudeError("Claude API key is not configured. Set it in the sidebar.")
        self.client = anthropic.Anthropic(api_key=key)

    def categorize_bill(self, title: str, description: str) -> str:
        """Classify a bill into one predefined category (categorizeBill, 50 tokens)."""
        categories = ", ".join(PREDEFINED_CATEGORIES)
        prompt = (
            f"Categorize this state legislation bill into exactly ONE of these categories:\n"
            f"{categories}\n\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Respond with ONLY the category name, nothing else."
        )
        msg = self.client.messages.create(
            model=MODEL, max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Validation with fuzzy fallback, matching the app's behavior.
        for cat in PREDEFINED_CATEGORIES:
            if cat.lower() == raw.lower():
                return cat
        for cat in PREDEFINED_CATEGORIES:
            if cat.lower() in raw.lower() or raw.lower() in cat.lower():
                return cat
        return raw or "Budget & Appropriations"

    def analyze_impact(self, title: str, description: str) -> dict:
        """Winners/losers industry & company analysis (analyzeImpact, 1200 tokens)."""
        prompt = (
            f"Analyze the market and industry impact of this state legislation.\n\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Identify which industries and companies would benefit (winners) and which "
            f"would be harmed (losers) if this bill becomes law.\n\n"
            f"Respond with ONLY valid JSON in this exact format, no other text:\n"
            f'{{\n'
            f'  "winners": [\n'
            f'    {{"industry": "string", "companies": ["string"], "reason": "string",\n'
            f'      "company_details": [{{"name": "string", "scale": "local|regional|national|global",\n'
            f'        "ticker": "string or null", "parent_company": "string or null",\n'
            f'        "parent_ticker": "string or null"}}]}}\n'
            f'  ],\n'
            f'  "losers": [ same shape as winners ]\n'
            f'}}'
        )
        msg = self.client.messages.create(
            model=MODEL, max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        # Strip markdown code fences before parsing, like the app does.
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip("` \n")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Could not parse impact JSON: {e}\n\n{text[:500]}")

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        """Free-form conversation (chat, 1024 tokens)."""
        kwargs = {"model": MODEL, "max_tokens": 1024, "messages": messages}
        if system:
            kwargs["system"] = system
        msg = self.client.messages.create(**kwargs)
        return msg.content[0].text

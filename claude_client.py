"""Claude API client, retargeted for Accela sales signal.

Two AI jobs:
  * categorize_bill  -> which Accela product line the bill touches (or Not Relevant)
  * analyze_impact   -> a sales-opportunity signal (score + why-it-matters + buyer)

The chat() helper is unchanged.
"""
import json

import anthropic

from models import ACCELA_PRODUCT_LINES

MODEL = "claude-sonnet-4-5-20250929"

# Shared context so the model knows what Accela sells.
ACCELA_CONTEXT = (
    "Accela sells cloud software to U.S. state and local governments for: "
    "building/construction permitting and land management, professional and "
    "business licensing, citizen engagement / self-service portals, code "
    "enforcement, cannabis and other regulated licensing, and short-term-rental "
    "regulation — plus records, transparency, and general digital-government "
    "modernization. Legislation that creates NEW obligations for governments to "
    "issue permits/licenses, digitize services, stand up online portals, enforce "
    "codes, or regulate new activities tends to DRIVE DEMAND for Accela's products."
)


class ClaudeError(Exception):
    pass


class ClaudeService:
    def __init__(self, api_key: str):
        key = (api_key or "").strip()
        if not key:
            raise ClaudeError("Claude API key is not configured. Set it in the sidebar.")
        self.client = anthropic.Anthropic(api_key=key)

    def _parse_json(self, text: str, what: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip("` \n")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"Could not parse {what} JSON: {e}\n\n{text[:500]}")

    def categorize_bill(self, title: str, description: str) -> str:
        """Classify a bill into ONE Accela product line, or 'Not Relevant'."""
        lines = ", ".join(ACCELA_PRODUCT_LINES)
        prompt = (
            f"{ACCELA_CONTEXT}\n\n"
            f"Classify this state legislation bill into exactly ONE of these Accela "
            f"product lines based on which one it most affects. If the bill has no "
            f"plausible connection to Accela's govtech products, answer 'Not Relevant'.\n\n"
            f"Product lines: {lines}\n\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Respond with ONLY the product line name, nothing else."
        )
        msg = self.client.messages.create(
            model=MODEL, max_tokens=30,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        for cat in ACCELA_PRODUCT_LINES:
            if cat.lower() == raw.lower():
                return cat
        for cat in ACCELA_PRODUCT_LINES:
            if cat.lower() in raw.lower() or raw.lower() in cat.lower():
                return cat
        return "Not Relevant"

    def analyze_impact(self, title: str, description: str) -> dict:
        """Score a bill as an Accela sales opportunity.

        Returns a dict:
          relevant           bool
          opportunity_score  int 0-100 (demand signal for Accela products)
          product_lines      list[str] (from ACCELA_PRODUCT_LINES)
          buyer              str  (which level of govt must act = the buyer)
          drivers            list[str] (what in the bill creates the demand)
          why_it_matters     str  (a paragraph a rep can paste to a prospect)
          talking_point      str  (one-sentence hook for outreach)
        """
        lines = ", ".join(l for l in ACCELA_PRODUCT_LINES if l != "Not Relevant")
        prompt = (
            f"{ACCELA_CONTEXT}\n\n"
            f"You are helping an Accela sales rep. Assess whether this state "
            f"legislation is a SALES OPPORTUNITY for Accela and how strong it is.\n\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Score the opportunity 0-100: how strongly, if this becomes law, it "
            f"would create or accelerate demand for Accela's products. High scores "
            f"= the bill forces governments to issue/track permits or licenses, "
            f"digitize services, launch online portals, enforce codes, or regulate "
            f"a new activity that needs a system of record. Low/zero = no govtech "
            f"software angle.\n\n"
            f"Respond with ONLY valid JSON in this exact format, no other text:\n"
            f'{{\n'
            f'  "relevant": true,\n'
            f'  "opportunity_score": 0,\n'
            f'  "product_lines": ["one or more of: {lines}"],\n'
            f'  "buyer": "which level/type of government must act (the buyer)",\n'
            f'  "drivers": ["specific requirement in the bill that creates demand"],\n'
            f'  "why_it_matters": "2-3 sentences a rep can paste into an email to a prospect",\n'
            f'  "talking_point": "one-sentence outreach hook"\n'
            f'}}'
        )
        msg = self.client.messages.create(
            model=MODEL, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        data = self._parse_json(msg.content[0].text, "sales opportunity")
        # Normalize the score to an int in [0, 100].
        try:
            data["opportunity_score"] = max(0, min(100, int(data.get("opportunity_score", 0))))
        except (TypeError, ValueError):
            data["opportunity_score"] = 0
        return data

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        kwargs = {"model": MODEL, "max_tokens": 1024, "messages": messages}
        if system:
            kwargs["system"] = system
        msg = self.client.messages.create(**kwargs)
        return msg.content[0].text

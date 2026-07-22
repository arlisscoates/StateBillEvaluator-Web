"""LegiScan API client — port of LegiScanService.swift."""
import requests

BASE_URL = "https://api.legiscan.com/"


class LegiScanError(Exception):
    pass


class LegiScanService:
    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()

    def _request(self, params: dict) -> dict:
        if not self.api_key:
            raise LegiScanError("LegiScan API key is not configured. Set it in the sidebar.")
        params = {**params, "key": self.api_key}
        resp = requests.get(BASE_URL, params=params, timeout=30)
        if resp.status_code != 200:
            raise LegiScanError(f"LegiScan API returned HTTP {resp.status_code}.")
        data = resp.json()
        if data.get("status") != "OK":
            raise LegiScanError(data.get("alert", {}).get("message", "LegiScan returned an error."))
        return data

    def _search_page(self, query: str, state: str | None, page: int) -> tuple[list[dict], dict]:
        params = {"op": "getSearch", "query": query, "page": str(page)}
        if state:
            params["state"] = state
        result = self._request(params)["searchresult"]
        summary = result.get("summary", {})
        bills = [v for k, v in result.items() if k != "summary" and isinstance(v, dict)]
        return bills, summary

    def search_bills(self, query: str, state: str | None = None) -> list[dict]:
        """Fetch all result pages for a query (optionally scoped to one state)."""
        bills, summary = self._search_page(query, state, 1)
        try:
            total_pages = int(summary.get("page_total", 1))
        except (TypeError, ValueError):
            total_pages = 1
        for page in range(2, total_pages + 1):
            more, _ = self._search_page(query, state, page)
            bills.extend(more)
        return bills

    def get_bill(self, bill_id: int) -> dict:
        return self._request({"op": "getBill", "id": str(bill_id)})["bill"]

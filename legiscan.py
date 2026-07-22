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

    # LegiScan numeric status codes -> human text (used by parse_detail).
    STATUS_MAP = {
        "1": "Introduced", "2": "Engrossed", "3": "Enrolled",
        "4": "Passed", "5": "Vetoed", "6": "Failed / Dead",
    }

    @staticmethod
    def parse_detail(bill: dict) -> dict:
        """Normalize a getBill response into the fields store.set_detail expects.

        Ported from SyncService.fetchBillDetail (description/status/url/session/
        sponsors). Any field that is missing comes back as None so the caller's
        COALESCE keeps the existing value.
        """
        sponsors = bill.get("sponsors") or []
        sp = ", ".join(
            s.get("name", "") + (f" ({s['party']})" if s.get("party") else "")
            for s in sponsors if s.get("name")
        )
        status_code = bill.get("status")
        status_text = LegiScanService.STATUS_MAP.get(str(status_code)) if status_code is not None else None
        session = (bill.get("session") or {}).get("session_name")
        return {
            "description": bill.get("description"),
            "status": status_text,
            "url": bill.get("url") or bill.get("state_link"),
            "session": session,
            "sponsors": sp or None,
        }

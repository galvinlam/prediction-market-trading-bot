from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests


CLOB_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"


class MarketDataClient:
    def __init__(
        self,
        *,
        clob_url: str | None = None,
        gamma_url: str | None = None,
        data_api_url: str | None = None,
        position_cache_ttl_seconds: float = 30.0,
    ) -> None:
        self.clob_url = (clob_url or os.environ.get("POLYMARKET_CLOB_URL") or CLOB_URL).rstrip("/")
        self.gamma_url = (gamma_url or os.environ.get("POLYMARKET_GAMMA_URL") or GAMMA_URL).rstrip("/")
        self.data_api_url = (data_api_url or os.environ.get("POLYMARKET_DATA_API_URL") or DATA_API_URL).rstrip("/")
        self.position_cache_ttl_seconds = max(0.0, float(position_cache_ttl_seconds))
        self._position_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def best_effort_buy_price(self, asset_id: str) -> float | None:
        try:
            price = self._get_clob_price(asset_id, side="SELL")
            if price is not None:
                return price
            midpoint = self._get_midpoint(asset_id)
            if midpoint is not None:
                return midpoint
            return self._get_gamma_outcome_price(asset_id)
        except requests.RequestException:
            return None

    def market_metadata(self, asset_id: str) -> dict[str, Any] | None:
        try:
            market = self._get_gamma_market(asset_id)
        except requests.RequestException:
            return None
        if not market:
            return None
        return _market_metadata(asset_id, market)

    def source_position_snapshot(self, wallet: str, asset_id: str) -> dict[str, Any] | None:
        clean_wallet = str(wallet or "").strip().lower()
        clean_asset = str(asset_id or "").strip()
        if not clean_wallet or not clean_asset:
            return None
        try:
            positions = self._get_user_positions(clean_wallet)
        except requests.RequestException:
            return None
        for row in positions:
            snapshot = _position_snapshot_from_row(row)
            if snapshot is not None and snapshot["asset_id"] == clean_asset:
                return snapshot
        return None

    def _get_clob_price(self, asset_id: str, *, side: str) -> float | None:
        response = requests.get(
            f"{self.clob_url}/price",
            params={"token_id": asset_id, "side": side},
            timeout=15,
        )
        if response.status_code in {400, 404}:
            return None
        response.raise_for_status()
        return _float_or_none(response.json().get("price"))

    def _get_midpoint(self, asset_id: str) -> float | None:
        response = requests.get(f"{self.clob_url}/midpoint", params={"token_id": asset_id}, timeout=15)
        if response.status_code in {400, 404}:
            return None
        response.raise_for_status()
        payload = response.json()
        return _float_or_none(payload.get("mid") or payload.get("mid_price"))

    def _get_gamma_outcome_price(self, asset_id: str) -> float | None:
        market = self._get_gamma_market(asset_id)
        if not market:
            return None
        return _outcome_price(asset_id, market)

    def _get_gamma_market(self, asset_id: str) -> dict[str, Any] | None:
        response = requests.get(
            f"{self.gamma_url}/markets",
            params={"clob_token_ids": asset_id, "limit": 1},
            timeout=15,
        )
        if response.status_code in {400, 404}:
            return None
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None
        return rows[0]

    def _get_user_positions(self, wallet: str) -> list[dict[str, Any]]:
        cached = self._position_cache.get(wallet)
        now = time.monotonic()
        if cached is not None and now - cached[0] <= self.position_cache_ttl_seconds:
            return cached[1]
        response = requests.get(
            f"{self.data_api_url}/positions",
            params={"user": wallet, "sizeThreshold": 0, "limit": 500},
            timeout=15,
        )
        if response.status_code in {400, 404}:
            return []
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        positions = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        self._position_cache[wallet] = (now, positions)
        return positions


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_snapshot_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = _string_or_none(
        row.get("asset")
        or row.get("asset_id")
        or row.get("assetId")
        or row.get("token_id")
        or row.get("tokenId")
        or row.get("clobTokenId")
    )
    if asset_id is None:
        return None
    quantity = _float_or_none(row.get("size") or row.get("quantity") or row.get("net_quantity"))
    avg_price = _float_or_none(row.get("avgPrice") or row.get("avg_price") or row.get("avg_buy_price") or row.get("price"))
    current_value = _float_or_none(row.get("currentValue") or row.get("current_value") or row.get("value"))
    explicit_notional = _float_or_none(
        row.get("initialValue") or row.get("costBasis") or row.get("cost_usdc") or row.get("notional_usdc")
    )
    notional = explicit_notional
    if notional is None and quantity is not None and avg_price is not None and quantity > 0 and avg_price > 0:
        notional = quantity * avg_price if avg_price <= 1 else quantity
    if notional is None and current_value is not None:
        notional = current_value
    if notional is None or notional <= 0:
        return None
    return {
        "asset_id": asset_id,
        "net_quantity": round(quantity or 0.0, 6),
        "avg_buy_price": round(avg_price or 0.0, 6),
        "net_notional_usdc": round(notional, 6),
        "current_value_usdc": round(current_value or 0.0, 6),
        "source": "data_api_positions",
    }


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return [str(item) for item in loaded]
    return []


def _market_metadata(asset_id: str, market: dict[str, Any]) -> dict[str, Any] | None:
    clob_ids = _json_list(market.get("clobTokenIds"))
    if asset_id not in clob_ids:
        return None
    index = clob_ids.index(asset_id)
    outcomes = _json_list(market.get("outcomes"))
    current_price = _outcome_price(asset_id, market)
    closed = bool(market.get("closed") or market.get("archived"))
    resolution_price = current_price if closed and current_price in {0.0, 1.0} else None
    market_slug = str(market.get("slug") or "")
    event_slug = _event_slug(market)
    event_title = _event_title(market)
    market_time, market_time_kind = market_close_time_details_from_gamma(market)
    classification = market_classification_fields(market)
    return {
        "market_id": str(market.get("id")) if market.get("id") is not None else None,
        "condition_id": str(market.get("conditionId")) if market.get("conditionId") else None,
        "title": str(market.get("question") or market.get("title") or ""),
        "market_slug": market_slug or None,
        "market_url": _market_url(asset_id=asset_id, market_slug=market_slug, event_slug=event_slug),
        "outcome": outcomes[index] if index < len(outcomes) else None,
        "outcome_side": "OUTCOME_SIDE_YES" if index == 0 else "OUTCOME_SIDE_NO" if index == 1 else None,
        **classification,
        "event_slug": event_slug or None,
        "event_title": event_title,
        "neg_risk": _bool_or_none(market.get("negRisk") if "negRisk" in market else market.get("negativeRisk")),
        "mergeable": _bool_or_none(market.get("mergeable")),
        "current_price": current_price,
        "price_source": "gamma_outcome" if current_price is not None else None,
        "is_closed": closed,
        "resolution_price": resolution_price,
        "market_close_time": market_time,
        "market_close_time_kind": market_time_kind,
    }


def _outcome_price(asset_id: str, market: dict[str, Any]) -> float | None:
    clob_ids = _json_list(market.get("clobTokenIds"))
    outcome_prices = _json_list(market.get("outcomePrices"))
    if asset_id not in clob_ids:
        return None
    index = clob_ids.index(asset_id)
    if index >= len(outcome_prices):
        return None
    return _float_or_none(outcome_prices[index])


def _event_slug(market: dict[str, Any]) -> str:
    events = market.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        if isinstance(first, dict):
            return str(first.get("slug") or "")
    return str(market.get("eventSlug") or "")


def _event_title(market: dict[str, Any]) -> str | None:
    events = market.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        if isinstance(first, dict):
            title = first.get("title") or first.get("ticker") or first.get("slug")
            return str(title) if title else None
    title = market.get("eventTitle")
    return str(title) if title else None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _market_url(*, asset_id: str, market_slug: str, event_slug: str) -> str:
    if market_slug and event_slug:
        return f"https://polymarket.com/event/{event_slug}/{market_slug}"
    if market_slug:
        return f"https://polymarket.com/market/{market_slug}"
    return f"https://polymarket.com/search?q={asset_id}"


def market_close_time_from_gamma(market: dict[str, Any]) -> str | None:
    return market_close_time_details_from_gamma(market)[0]


def market_close_time_details_from_gamma(market: dict[str, Any]) -> tuple[str | None, str | None]:
    for value, kind in _market_close_candidates(market):
        close_time = _gamma_time_to_pdt(value)
        if close_time:
            return close_time, kind
    return None, None


def _market_close_candidates(market: dict[str, Any]) -> list[tuple[Any, str]]:
    actual_close_candidates = [
        market.get("closedTime"),
        market.get("closedAt"),
        market.get("closeTime"),
        market.get("resolvedTime"),
        market.get("resolutionTime"),
        market.get("finishedTimestamp"),
    ]
    event_actual_close_candidates = []
    event_start_candidates = []
    event_end_candidates = []
    events = market.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                event_actual_close_candidates.extend(
                    [
                        event.get("closedTime"),
                        event.get("closedAt"),
                        event.get("closeTime"),
                        event.get("resolvedTime"),
                        event.get("resolutionTime"),
                        event.get("finishedTimestamp"),
                    ]
                )
                event_start_candidates.extend([event.get("gameStartTime"), event.get("eventDate")])
                event_end_candidates.append(event.get("endDate"))
    if classify_market(market) == "sports":
        return (
            [(value, "actual_close") for value in actual_close_candidates]
            + [(value, "actual_close") for value in event_actual_close_candidates]
            + [(market.get("gameStartTime"), "event_start")]
            + [(value, "event_start") for value in event_start_candidates]
            + [(market.get("endDate"), "event_start")]
            + [(market.get("endDateIso"), "event_start")]
            + [(value, "event_start") for value in event_end_candidates]
        )
    return (
        [(value, "actual_close") for value in actual_close_candidates]
        + [(market.get("endDate"), "actual_close")]
        + [(market.get("gameStartTime"), "event_start")]
        + [(market.get("endDateIso"), "actual_close")]
        + [(value, "actual_close") for value in event_actual_close_candidates]
        + [(value, "actual_close") for value in event_end_candidates]
        + [(value, "event_start") for value in event_start_candidates]
    )


def _gamma_time_to_pdt(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(ZoneInfo("America/Los_Angeles"))
    return local.strftime("%Y-%m-%d %H:%M PDT")


def classify_market(market: dict[str, Any]) -> str:
    structured_market_type = _structured_market_type(market)
    if structured_market_type is not None:
        return structured_market_type
    return _classify_market_from_text(market)


def classify_sport_key(market: dict[str, Any]) -> str | None:
    existing = _normalize_structured_value(market.get("sport_key"))
    if existing:
        return existing
    for value in [_series_slug(market), *_market_structured_values(market)]:
        sport = _sport_key_from_structured_value(value)
        if sport is not None:
            return sport
    return _classify_sport_key_from_text(market)


def classify_bet_type(market: dict[str, Any]) -> str | None:
    existing = _normalize_structured_value(market.get("bet_type"))
    if existing:
        return existing
    structured = _bet_type_from_sports_market_type(_sports_market_type(market))
    if structured is not None:
        return structured
    return _classify_bet_type_from_text(market)


def market_classification_fields(market: dict[str, Any]) -> dict[str, str | None]:
    return {
        "market_type": classify_market(market),
        "sport_key": classify_sport_key(market),
        "bet_type": classify_bet_type(market),
        "series_slug": _series_slug(market),
        "sports_market_type": _sports_market_type(market),
        "category_slug": _category_slug(market),
    }


def _structured_market_type(market: dict[str, Any]) -> str | None:
    values = {_normalize_structured_value(value) for value in _market_structured_values(market)}
    values.discard("")
    if _has_structured_sports_marker(market) or any(_is_sports_structured_value(value) for value in values):
        return "sports"
    if any(value in {"crypto", "cryptocurrency"} for value in values):
        return "crypto"
    if "weather" in values:
        return "weather"
    return None


def _market_structured_values(market: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in (
        "category",
        "categorySlug",
        "marketType",
        "seriesSlug",
        "eventType",
    ):
        values.append(market.get(key))
    values.extend(
        _structured_values_from_items(
            market.get("tags"),
            ("category", "categorySlug", "label", "name", "slug", "ticker", "seriesSlug", "marketType"),
        )
    )
    values.extend(
        _structured_values_from_items(
            market.get("series"),
            ("category", "categorySlug", "label", "name", "slug", "ticker", "seriesSlug", "marketType"),
        )
    )
    values.extend(
        _structured_values_from_items(
            market.get("events"),
            ("category", "categorySlug", "slug", "ticker", "seriesSlug", "marketType", "sportsMarketType", "eventType"),
        )
    )
    return values


def _series_slug(market: dict[str, Any]) -> str | None:
    for value in (
        market.get("seriesSlug"),
        _first_item_value(market.get("events"), "seriesSlug"),
        _first_item_value(market.get("series"), "slug"),
        _first_item_value(market.get("series"), "ticker"),
    ):
        normalized = _normalize_structured_value(value)
        if normalized:
            return normalized
    return None


def _sports_market_type(market: dict[str, Any]) -> str | None:
    for value in (market.get("sportsMarketType"), _first_item_value(market.get("events"), "sportsMarketType")):
        normalized = _normalize_structured_value(value)
        if normalized:
            return normalized
    return None


def _category_slug(market: dict[str, Any]) -> str | None:
    for value in (market.get("categorySlug"), market.get("category"), _first_item_value(market.get("tags"), "slug")):
        normalized = _normalize_structured_value(value)
        if normalized:
            return normalized
    return None


def _first_item_value(items: Any, key: str) -> Any:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get(key):
            return item.get(key)
    return None


def _structured_values_from_items(items: Any, keys: tuple[str, ...]) -> list[Any]:
    if not isinstance(items, list):
        return []
    values: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            for key in keys:
                values.append(item.get(key))
        else:
            values.append(item)
    return values


def _has_structured_sports_marker(market: dict[str, Any]) -> bool:
    if market.get("sportsMarketType"):
        return True
    events = market.get("events")
    return isinstance(events, list) and any(isinstance(event, dict) and event.get("sportsMarketType") for event in events)


def _normalize_structured_value(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def _is_sports_structured_value(value: str) -> bool:
    if value in {"sports", "sport", "esports", "mlb", "nba", "nfl", "nhl", "mls", "epl", "wta", "atp", "tennis"}:
        return True
    return value.startswith(
        (
            "mlb-",
            "nba-",
            "nfl-",
            "nhl-",
            "mls-",
            "epl-",
            "wta-",
            "atp-",
            "ufc-",
            "uefa-",
            "champions-league-",
            "premier-league-",
            "la-liga-",
            "laliga-",
            "serie-a-",
            "bundesliga-",
            "counter-strike-",
            "cs2-",
            "dota-",
            "valorant-",
            "league-of-legends-",
        )
    )


def _sport_key_from_structured_value(value: Any) -> str | None:
    normalized = _normalize_structured_value(value)
    if normalized in {"mlb", "nba", "nfl", "nhl", "wta", "atp", "tennis", "esports"}:
        return normalized
    if normalized in {"mls", "epl", "uefa", "ucl", "uel", "soccer", "football"}:
        return "soccer"
    for prefix, sport in (
        ("mlb-", "mlb"),
        ("nba-", "nba"),
        ("nfl-", "nfl"),
        ("nhl-", "nhl"),
        ("wta-", "wta"),
        ("atp-", "atp"),
        ("mls-", "soccer"),
        ("epl-", "soccer"),
        ("uefa-", "soccer"),
        ("ucl-", "soccer"),
        ("uel-", "soccer"),
        ("champions-league-", "soccer"),
        ("premier-league-", "soccer"),
        ("la-liga-", "soccer"),
        ("laliga-", "soccer"),
        ("serie-a-", "soccer"),
        ("bundesliga-", "soccer"),
        ("counter-strike-", "esports"),
        ("cs2-", "esports"),
        ("dota-", "esports"),
        ("valorant-", "esports"),
        ("league-of-legends-", "esports"),
    ):
        if normalized.startswith(prefix):
            return sport
    return None


def _bet_type_from_sports_market_type(value: Any) -> str | None:
    normalized = _normalize_structured_value(value)
    if not normalized:
        return None
    if normalized in {"moneyline", "winner", "match-winner", "game-winner"}:
        return "moneyline_winlose"
    if "spread" in normalized or "handicap" in normalized:
        return "spread_handicap"
    if normalized in {"total", "totals"} or "over-under" in normalized or "o-u" in normalized:
        return "total_or_over_under"
    if normalized in {"both-teams-to-score", "btts"}:
        return "both_teams_score"
    if normalized == "draw":
        return "draw"
    if "map" in normalized or "game" in normalized:
        return "map_or_game_winner"
    return None


def _classify_sport_key_from_text(market: dict[str, Any]) -> str | None:
    text = _market_text(market)
    if any(token in text for token in ("counter-strike", "cs2", "league-of-legends", "dota", "valorant")):
        return "esports"
    if any(token in text for token in ("nba", "basketball")):
        return "nba"
    if any(token in text for token in ("mlb", "baseball")):
        return "mlb"
    if any(token in text for token in ("nfl", "american football")):
        return "nfl"
    if any(token in text for token in ("nhl", "hockey")):
        return "nhl"
    if "atp" in text:
        return "atp"
    if "wta" in text:
        return "wta"
    if "tennis" in text:
        return "tennis"
    if "soccer" in text or "football" in text or " fc " in f" {text} " or " win on " in text:
        return "soccer"
    return None


def _classify_bet_type_from_text(market: dict[str, Any]) -> str | None:
    text = _market_text(market)
    if "both teams to score" in text or " btts " in f" {text} ":
        return "both_teams_score"
    if "end in a draw" in text or " draw" in text:
        return "draw"
    if "o/u" in text or "over/under" in text or "total" in text or " over " in f" {text} " or " under " in f" {text} ":
        return "total_or_over_under"
    if "spread" in text or "handicap" in text:
        return "spread_handicap"
    if ("map " in text or "game " in text) and ("winner" in text or " win" in text):
        return "map_or_game_winner"
    if " win on " in text or "winner" in text or " vs " in text or " vs. " in text:
        return "moneyline_winlose"
    return None


def _classify_market_from_text(market: dict[str, Any]) -> str:
    text = _market_text(market)
    if any(token in text for token in ("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "crypto")):
        return "crypto"
    if any(
        token in text
        for token in (
            "nba",
            "nfl",
            "mlb",
            "nhl",
            "soccer",
            "tennis",
            "wta",
            "atp",
            "ufc",
            "sports",
            "esports",
            "counter-strike",
            "cs2",
            "dota",
            "valorant",
            "league of legends",
            "-vs-",
            " vs ",
            " vs. ",
            "o/u",
            "spread:",
            "both teams to score",
        )
    ):
        return "sports"
    if "will " in text and " win on 20" in text:
        return "sports"
    if any(token in text for token in ("weather", "temperature", "rain", "snow", "hurricane")):
        return "weather"
    return "other"


def _classify_market(market: dict[str, Any]) -> str:
    return classify_market(market)


def _market_text(market: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            market.get("category"),
            market.get("marketType"),
            market.get("sportsMarketType"),
            market.get("question"),
            market.get("title"),
            market.get("slug"),
            market.get("market_slug"),
            market.get("event_slug"),
            market.get("event_title"),
            market.get("outcome"),
        )
    ).lower()

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
import websockets

from polymarket_copy_trading.config import AppSettings, load_config
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.market_data import classify_market, market_classification_fields, market_close_time_details_from_gamma
from polymarket_copy_trading.store import Store


CLOB_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PDT = timezone(timedelta(hours=-7), "PDT")


class PriceMonitor:
    def __init__(
        self,
        *,
        config: AppSettings,
        store: Store,
        clob_url: str | None = None,
        gamma_url: str | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.config_path = config_path
        self.clob_url = (clob_url or os.environ.get("POLYMARKET_CLOB_URL") or CLOB_URL).rstrip("/")
        self.gamma_url = (gamma_url or os.environ.get("POLYMARKET_GAMMA_URL") or GAMMA_URL).rstrip("/")
        self.market_ws_url = os.environ.get("POLYMARKET_MARKET_WS_URL") or MARKET_WS_URL

    def run_forever(self, *, poll_seconds: float | None = None) -> None:
        if poll_seconds is None:
            asyncio.run(self._run_ws_forever())
            return
        self.store.set_runtime_state("price_monitor_status", "starting")
        while True:
            stats = self.refresh_once()
            self.store.set_runtime_state("price_monitor_last_stats", json.dumps(stats))
            time.sleep(self.next_poll_seconds(stats, override_seconds=poll_seconds))

    def next_poll_seconds(self, stats: dict[str, int], *, override_seconds: float | None = None) -> float:
        if override_seconds is not None:
            return override_seconds
        if int(stats.get("open_assets") or 0) > 0:
            return self.config.price_monitor.poll_interval_seconds
        return self.config.price_monitor.idle_poll_interval_seconds

    async def _run_ws_forever(self) -> None:
        self.store.set_runtime_state("price_monitor_status", "starting_ws")
        delay = max(0.5, self.config.price_monitor.poll_interval_seconds)
        while True:
            self._refresh_config()
            if not self.config.price_monitor.enabled:
                self.store.set_runtime_state("price_monitor_status", "disabled")
                await asyncio.sleep(self.config.price_monitor.idle_poll_interval_seconds)
                delay = max(0.5, self.config.price_monitor.poll_interval_seconds)
                continue
            assets = self.store.list_open_asset_ids()
            if not assets:
                self.store.set_runtime_state("price_monitor_status", "idle_no_positions")
                await asyncio.sleep(self.config.price_monitor.idle_poll_interval_seconds)
                delay = max(0.5, self.config.price_monitor.poll_interval_seconds)
                continue
            try:
                await self._run_ws_session(assets)
                delay = max(0.5, self.config.price_monitor.poll_interval_seconds)
            except Exception as exc:
                self.store.set_runtime_state("price_monitor_status", "ws_reconnecting")
                self.store.set_runtime_state("price_monitor_last_error", f"{type(exc).__name__}: {exc}"[:500])
                self.refresh_once()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.watcher.ws_reconnect_max_seconds)

    async def _run_ws_session(self, assets: list[str]) -> None:
        subscribed = set(assets)
        async with websockets.connect(
            self.market_ws_url,
            ping_interval=self.config.watcher.ws_ping_interval_seconds,
            ping_timeout=self.config.watcher.ws_ping_timeout_seconds,
            close_timeout=self.config.watcher.ws_close_timeout_seconds,
        ) as websocket:
            await websocket.send(json.dumps(_market_subscription(assets)))
            heartbeat = asyncio.create_task(_send_market_heartbeats(websocket))
            self.store.set_runtime_state("price_monitor_status", "running_ws")
            self.store.set_runtime_state("price_monitor_last_error", "")
            last_http_refresh = time.monotonic()
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        self._refresh_config()
                        if not self.config.price_monitor.enabled:
                            self.store.set_runtime_state("price_monitor_status", "disabled")
                            return
                        current = set(self.store.list_open_asset_ids())
                        if current != subscribed:
                            return
                        if time.monotonic() - last_http_refresh >= self.config.price_monitor.poll_interval_seconds:
                            stats = self.refresh_once()
                            self.store.set_runtime_state("price_monitor_last_stats", json.dumps(stats))
                            self.store.set_runtime_state("price_monitor_status", "running_ws")
                            last_http_refresh = time.monotonic()
                        continue
                    if raw == "PONG":
                        continue
                    self._refresh_config()
                    if not self.config.price_monitor.enabled:
                        self.store.set_runtime_state("price_monitor_status", "disabled")
                        return
                    payload = json.loads(raw)
                    stats = self.handle_market_ws_message(payload)
                    if stats["updated"]:
                        self.store.set_runtime_state("price_monitor_last_stats", json.dumps(stats))
            finally:
                heartbeat.cancel()

    def refresh_once(self) -> dict[str, int]:
        self._refresh_config()
        if not self.config.price_monitor.enabled:
            self.store.set_runtime_state("price_monitor_status", "disabled")
            return {"priced": 0, "metadata": 0, "errors": 0, "exits": 0, "settlements": 0, "open_assets": 0}

        stats = {"priced": 0, "metadata": 0, "errors": 0, "exits": 0, "settlements": 0, "open_assets": 0}
        open_assets = self.store.list_open_asset_ids()
        stats["open_assets"] = len(open_assets)
        assets = self.store.list_price_monitor_asset_ids()
        self.store.set_runtime_state("price_monitor_status", "running")
        for asset_id in assets:
            try:
                existing = self.store.get_market_metadata(asset_id) or {}
                metadata = self.get_market_metadata(asset_id)
                event_slug = _string_or_none(metadata.get("event_slug") or existing.get("event_slug"))
                should_try_event_fallback = (
                    not metadata.get("_has_market_metadata")
                    or (
                        event_slug
                        and str(metadata.get("market_type") or existing.get("market_type") or "").lower() == "sports"
                        and not bool(metadata.get("is_closed"))
                    )
                )
                if should_try_event_fallback and event_slug:
                    event_metadata = self.get_event_market_metadata(asset_id, event_slug=event_slug)
                    if event_metadata.get("_has_market_metadata"):
                        metadata = event_metadata
                metadata_price = metadata.pop("_current_price", None)
                metadata_source = metadata.pop("_price_source", None)
                has_market_metadata = bool(metadata.pop("_has_market_metadata", False))
                try:
                    price, source = self.get_current_price(
                        asset_id,
                        fallback_price=metadata_price,
                        fallback_source=metadata_source,
                    )
                except ValueError:
                    existing_price = _float_or_none(existing.get("current_price"))
                    if not has_market_metadata and existing_price is not None and existing_price <= 0.005:
                        price = existing_price
                        source = "clob_no_orderbook"
                    elif not metadata.get("is_closed"):
                        raise
                    else:
                        price = metadata.get("resolution_price")
                        source = "resolution" if price is not None else "closed_unpriced"
                self.store.upsert_market_metadata(
                    asset_id=asset_id,
                    current_price=price,
                    price_source=source,
                    last_price_at=_now_pdt(),
                    **metadata,
                )
                stats["priced"] += 1
                if has_market_metadata:
                    stats["metadata"] += 1
            except Exception as exc:
                stats["errors"] += 1
                self.store.set_runtime_state("price_monitor_last_error", f"{type(exc).__name__}: {exc}"[:500])
        engine = CopyTradingEngine(config=self.config, store=self.store)
        stats["settlements"] = engine.process_market_settlements()
        stats["exits"] = engine.process_local_exits()
        self.store.set_runtime_state("price_monitor_status", "idle" if assets else "idle_no_positions")
        self.store.set_runtime_state("price_monitor_last_stats", json.dumps(stats))
        return stats

    def handle_market_ws_message(self, payload: dict[str, Any] | list[Any]) -> dict[str, int]:
        self._refresh_config()
        if not self.config.price_monitor.enabled:
            self.store.set_runtime_state("price_monitor_status", "disabled")
            return {"updated": 0, "exits": 0, "settlements": 0}
        updated = 0
        if isinstance(payload, list):
            events = [event for event in payload if isinstance(event, dict)]
        elif isinstance(payload, dict):
            events = [payload]
        else:
            events = []
        for event in events:
            updated += self._handle_market_ws_event(event)
        engine = CopyTradingEngine(config=self.config, store=self.store)
        settlements = engine.process_market_settlements()
        exits = engine.process_local_exits()
        self.store.set_runtime_state("price_monitor_status", "running_ws")
        return {"updated": updated, "exits": exits, "settlements": settlements}

    def _handle_market_ws_event(self, payload: dict[str, Any]) -> int:
        updated = 0
        event_type = str(payload.get("event_type") or "")
        if event_type == "book":
            updated += self._update_ws_price(
                asset_id=str(payload.get("asset_id") or ""),
                price=_book_best_bid(payload.get("bids")),
                source="clob_ws_book",
            )
        elif event_type == "price_change":
            for change in payload.get("price_changes") or []:
                if not isinstance(change, dict):
                    continue
                updated += self._update_ws_price(
                    asset_id=str(change.get("asset_id") or ""),
                    price=_float_or_none(change.get("best_bid") or change.get("price")),
                    source="clob_ws_price_change",
                )
        elif event_type == "best_bid_ask":
            updated += self._update_ws_price(
                asset_id=str(payload.get("asset_id") or ""),
                price=_float_or_none(payload.get("best_bid")),
                source="clob_ws_best_bid",
            )
        elif event_type == "last_trade_price":
            updated += self._update_ws_price(
                asset_id=str(payload.get("asset_id") or ""),
                price=_float_or_none(payload.get("price")),
                source="clob_ws_last_trade",
            )
        elif event_type == "market_resolved":
            updated += self._handle_market_resolved(payload)
        return updated

    def _update_ws_price(self, *, asset_id: str, price: float | None, source: str) -> int:
        if not asset_id or price is None or price < 0:
            return 0
        self.store.upsert_market_metadata(
            asset_id=asset_id,
            current_price=price,
            price_source=source,
            last_price_at=_now_pdt(),
        )
        return 1

    def _handle_market_resolved(self, payload: dict[str, Any]) -> int:
        winning_asset_id = str(payload.get("winning_asset_id") or "")
        asset_ids = payload.get("assets_ids") or payload.get("clob_token_ids") or []
        updated = 0
        if winning_asset_id:
            updated += self._update_resolution_price(winning_asset_id, 1.0)
        for asset_id in asset_ids:
            asset_text = str(asset_id or "")
            if asset_text and asset_text != winning_asset_id:
                updated += self._update_resolution_price(asset_text, 0.0)
        return updated

    def _update_resolution_price(self, asset_id: str, price: float) -> int:
        self.store.upsert_market_metadata(
            asset_id=asset_id,
            current_price=price,
            price_source="clob_ws_market_resolved",
            last_price_at=_now_pdt(),
            is_closed=True,
            resolution_price=price,
        )
        return 1

    def _refresh_config(self) -> None:
        if self.config_path is None:
            return
        self.config = load_config(self.config_path)

    def get_current_price(
        self,
        asset_id: str,
        *,
        fallback_price: float | None = None,
        fallback_source: str | None = None,
    ) -> tuple[float, str]:
        price = self._get_price(asset_id, side="SELL")
        if price is not None:
            return price, "clob_sell"
        midpoint = self._get_midpoint(asset_id)
        if midpoint is not None:
            return midpoint, "clob_midpoint"
        if fallback_price is not None:
            return fallback_price, fallback_source or "gamma_outcome"
        raise ValueError(f"no CLOB price available for {asset_id}")

    def get_market_metadata(self, asset_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.gamma_url}/markets",
            params={"clob_token_ids": asset_id, "limit": 1},
            timeout=15,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return {"market_url": f"https://polymarket.com/search?q={asset_id}", "_has_market_metadata": False}
        return _market_metadata_from_gamma(asset_id, rows[0])

    def get_event_market_metadata(self, asset_id: str, *, event_slug: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.gamma_url}/events",
            params={"slug": event_slug, "limit": 1},
            timeout=15,
        )
        response.raise_for_status()
        events = response.json()
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            for market in event.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                if asset_id in _json_list(market.get("clobTokenIds")):
                    event_stub = {
                        "slug": event.get("slug"),
                        "title": event.get("title"),
                        "category": event.get("category"),
                        "categorySlug": event.get("categorySlug"),
                        "marketType": event.get("marketType"),
                        "seriesSlug": event.get("seriesSlug"),
                        "sportsMarketType": event.get("sportsMarketType"),
                        "eventType": event.get("eventType"),
                        "tags": event.get("tags"),
                        "series": event.get("series"),
                        "closedTime": event.get("closedTime"),
                        "closedAt": event.get("closedAt"),
                        "closeTime": event.get("closeTime"),
                        "resolvedTime": event.get("resolvedTime"),
                        "resolutionTime": event.get("resolutionTime"),
                        "finishedTimestamp": event.get("finishedTimestamp"),
                        "gameStartTime": event.get("gameStartTime") or event.get("startTime"),
                        "eventDate": event.get("eventDate"),
                        "endDate": event.get("endDate"),
                    }
                    enriched = {**market, "events": [event_stub]}
                    return _market_metadata_from_gamma(asset_id, enriched, event_slug=event_slug)
        return {"market_url": f"https://polymarket.com/search?q={asset_id}", "_has_market_metadata": False}

    def _get_price(self, asset_id: str, *, side: str) -> float | None:
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


def _market_metadata_from_gamma(
    asset_id: str,
    market: dict[str, Any],
    *,
    event_slug: str | None = None,
) -> dict[str, Any]:
    slug = _string_or_none(market.get("slug"))
    clean_event_slug = event_slug or _event_slug(market.get("events"))
    clob_ids = _json_list(market.get("clobTokenIds"))
    outcomes = _json_list(market.get("outcomes"))
    outcome_prices = _json_list(market.get("outcomePrices"))
    closed = bool(market.get("closed") or market.get("archived"))
    outcome = None
    outcome_side = None
    outcome_price = None
    if asset_id in clob_ids:
        index = clob_ids.index(asset_id)
        outcome_side = "OUTCOME_SIDE_YES" if index == 0 else "OUTCOME_SIDE_NO" if index == 1 else None
        if index < len(outcomes):
            outcome = str(outcomes[index])
        if index < len(outcome_prices):
            outcome_price = _float_or_none(outcome_prices[index])
    resolution_price = outcome_price if closed and outcome_price in {0.0, 1.0} else None
    market_time, market_time_kind = market_close_time_details_from_gamma(market)
    classification = market_classification_fields(market)
    return {
        "market_id": _string_or_none(market.get("id")),
        "condition_id": _string_or_none(market.get("conditionId")),
        "outcome": outcome,
        "outcome_side": outcome_side,
        "title": _string_or_none(market.get("question")),
        "market_slug": slug,
        "market_url": _market_url(asset_id=asset_id, market_slug=slug, event_slug=clean_event_slug),
        **classification,
        "event_slug": clean_event_slug,
        "market_close_time": market_time,
        "market_close_time_kind": market_time_kind,
        "is_closed": closed,
        "resolution_price": resolution_price,
        "_current_price": outcome_price,
        "_price_source": "gamma_outcome",
        "_has_market_metadata": True,
    }


def _now_pdt() -> str:
    return datetime.now(tz=PDT).strftime("%Y-%m-%d %H:%M PDT")


def _market_subscription(asset_ids: list[str]) -> dict[str, Any]:
    return {
        "assets_ids": asset_ids,
        "type": "market",
        "custom_feature_enabled": True,
    }


async def _send_market_heartbeats(websocket: Any) -> None:
    while True:
        await asyncio.sleep(10)
        await websocket.send("PING")


def _book_best_bid(rows: Any) -> float | None:
    if not isinstance(rows, list):
        return None
    prices = [_float_or_none(row.get("price")) for row in rows if isinstance(row, dict)]
    clean = [price for price in prices if price is not None]
    return max(clean) if clean else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _event_slug(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if not isinstance(first, dict):
        return None
    return _string_or_none(first.get("slug"))


def _market_url(*, asset_id: str, market_slug: str | None, event_slug: str | None) -> str:
    if market_slug and event_slug:
        return f"https://polymarket.com/event/{event_slug}/{market_slug}"
    if market_slug:
        return f"https://polymarket.com/market/{market_slug}"
    return f"https://polymarket.com/search?q={asset_id}"


def _classify_market(market: dict[str, Any]) -> str:
    return classify_market(market)

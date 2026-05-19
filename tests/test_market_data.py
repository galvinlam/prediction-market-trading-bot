from polymarket_copy_trading.market_data import MarketDataClient


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_market_data_client_classifies_asset_market_metadata(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-weather-no", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2080000",
                    "conditionId": "0xweather",
                    "question": "Will the highest temperature in Miami be between 88-89F on April 27?",
                    "slug": "highest-temperature-in-miami-on-april-27-2026-88-89f",
                    "endDate": "2026-04-29T12:00:00Z",
                    "events": [{"slug": "highest-temperature-in-miami-on-april-27-2026"}],
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.12", "0.88"]',
                    "clobTokenIds": '["asset-weather-yes", "asset-weather-no"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-weather-no")

    assert metadata == {
        "market_id": "2080000",
        "condition_id": "0xweather",
        "title": "Will the highest temperature in Miami be between 88-89F on April 27?",
        "market_slug": "highest-temperature-in-miami-on-april-27-2026-88-89f",
        "market_url": (
            "https://polymarket.com/event/highest-temperature-in-miami-on-april-27-2026/"
            "highest-temperature-in-miami-on-april-27-2026-88-89f"
        ),
        "outcome": "No",
        "outcome_side": "OUTCOME_SIDE_NO",
        "market_type": "weather",
        "sport_key": None,
        "bet_type": None,
        "series_slug": None,
        "sports_market_type": None,
        "category_slug": None,
        "event_slug": "highest-temperature-in-miami-on-april-27-2026",
        "event_title": "highest-temperature-in-miami-on-april-27-2026",
        "neg_risk": None,
        "mergeable": None,
        "current_price": 0.88,
        "price_source": "gamma_outcome",
        "is_closed": False,
        "resolution_price": None,
        "market_close_time": "2026-04-29 05:00 PDT",
        "market_close_time_kind": "actual_close",
    }


def test_market_data_client_returns_source_position_snapshot_for_asset(monkeypatch) -> None:
    calls = []

    def fake_get(url, params=None, timeout=None):
        _ = timeout
        calls.append((url, params))
        assert url == "https://data-api.polymarket.com/positions"
        assert params == {"user": "0xrn1", "sizeThreshold": 0, "limit": 500}
        return FakeResponse(
            [
                {"asset": "other-asset", "size": "20", "avgPrice": "0.50"},
                {"asset": "asset-pistons", "size": "20000", "avgPrice": "0.75", "currentValue": "9000"},
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    client = MarketDataClient()
    snapshot = client.source_position_snapshot("0xrn1", "asset-pistons")

    assert snapshot == {
        "asset_id": "asset-pistons",
        "net_quantity": 20000.0,
        "avg_buy_price": 0.75,
        "net_notional_usdc": 15000.0,
        "current_value_usdc": 9000.0,
        "source": "data_api_positions",
    }
    assert client.source_position_snapshot("0xrn1", "asset-pistons") == snapshot
    assert calls == [("https://data-api.polymarket.com/positions", {"user": "0xrn1", "sizeThreshold": 0, "limit": 500})]


def test_market_data_client_classifies_wta_slug_as_sports(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-werner", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2107001",
                    "conditionId": "0xtennis",
                    "question": "La Bisbal: Rebecca Sramkova vs Caroline Werner",
                    "slug": "wta-sramkov-werner-2026-04-29",
                    "endDate": "2026-05-06T09:00:00Z",
                    "events": [{"slug": "wta-sramkov-werner-2026-04-29"}],
                    "outcomes": '["Rebecca Sramkova", "Caroline Werner"]',
                    "outcomePrices": '["0.00", "1.00"]',
                    "clobTokenIds": '["asset-sramkova", "asset-werner"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-werner")

    assert metadata["market_type"] == "sports"


def test_market_data_client_classifies_carolina_hurricanes_as_sports(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-flyers", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2107003",
                    "conditionId": "0xnhl",
                    "question": "Hurricanes vs. Flyers",
                    "slug": "nhl-car-phi-2026-05-07",
                    "sportsMarketType": "moneyline",
                    "seriesSlug": "nhl-2026",
                    "endDate": "2026-05-08T00:00:00Z",
                    "events": [
                        {"slug": "nhl-car-phi-2026-05-07", "title": "Hurricanes vs. Flyers", "seriesSlug": "nhl-2026"}
                    ],
                    "outcomes": '["Hurricanes", "Flyers"]',
                    "outcomePrices": '["0.615", "0.385"]',
                    "clobTokenIds": '["asset-hurricanes", "asset-flyers"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-flyers")

    assert metadata["market_type"] == "sports"
    assert metadata["sport_key"] == "nhl"
    assert metadata["bet_type"] == "moneyline_winlose"
    assert metadata["series_slug"] == "nhl-2026"
    assert metadata["sports_market_type"] == "moneyline"


def test_market_data_client_classifies_structured_sports_without_keyword_text(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-away", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2107004",
                    "conditionId": "0xstructuredsports",
                    "question": "Participant A / Participant B",
                    "slug": "daily-match-market",
                    "sportsMarketType": "moneyline",
                    "seriesSlug": "nhl-2026",
                    "events": [{"slug": "daily-match-event", "seriesSlug": "nhl-2026", "title": "Participant A / Participant B"}],
                    "outcomes": '["Home", "Away"]',
                    "outcomePrices": '["0.62", "0.38"]',
                    "clobTokenIds": '["asset-home", "asset-away"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-away")

    assert metadata["market_type"] == "sports"
    assert metadata["sport_key"] == "nhl"
    assert metadata["bet_type"] == "moneyline_winlose"


def test_sports_close_time_uses_game_start_before_week_later_end_date(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-athletics", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2107002",
                    "conditionId": "0xmlb",
                    "question": "Cleveland Guardians vs. Athletics",
                    "slug": "mlb-cle-oak-2026-05-02",
                    "endDate": "2026-05-09T20:05:00Z",
                    "gameStartTime": "2026-05-02T20:05:00Z",
                    "events": [
                        {
                            "slug": "mlb-cle-oak-2026-05-02",
                            "endDate": "2026-05-09T20:05:00Z",
                            "gameStartTime": "2026-05-02T20:05:00Z",
                        }
                    ],
                    "outcomes": '["Guardians", "Athletics"]',
                    "outcomePrices": '["1.00", "0.00"]',
                    "clobTokenIds": '["asset-guardians", "asset-athletics"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-athletics")

    assert metadata["market_type"] == "sports"
    assert metadata["market_close_time"] == "2026-05-02 13:05 PDT"
    assert metadata["market_close_time_kind"] == "event_start"


def test_market_data_client_classifies_soccer_props_as_sports(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-braga-no", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2108001",
                    "conditionId": "0xsoccer",
                    "question": "Will SC Braga win on 2026-04-30?",
                    "slug": "will-sc-braga-win-on-2026-04-30",
                    "endDate": "2026-04-30T19:00:00Z",
                    "events": [{"slug": "sc-braga-vs-opponent-2026-04-30"}],
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.31", "0.69"]',
                    "clobTokenIds": '["asset-braga-yes", "asset-braga-no"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-braga-no")

    assert metadata["market_type"] == "sports"


def test_market_close_time_prefers_actual_close_over_game_start(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        _ = timeout
        assert url == "https://gamma-api.polymarket.com/markets"
        assert params == {"clob_token_ids": "asset-san-diego-no", "limit": 1}
        return FakeResponse(
            [
                {
                    "id": "2109001",
                    "conditionId": "0xmls",
                    "question": "Will San Diego FC win on 2026-05-02?",
                    "slug": "will-san-diego-fc-win-on-2026-05-02",
                    "gameStartTime": "2026-05-02T20:30:00Z",
                    "closedTime": "2026-05-02T22:42:00Z",
                    "events": [
                        {
                            "slug": "mls-san-diego-fc-vs-la-galaxy-2026-05-02",
                            "gameStartTime": "2026-05-02T20:30:00Z",
                        }
                    ],
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.00", "1.00"]',
                    "clobTokenIds": '["asset-san-diego-yes", "asset-san-diego-no"]',
                }
            ]
        )

    monkeypatch.setattr("polymarket_copy_trading.market_data.requests.get", fake_get)

    metadata = MarketDataClient().market_metadata("asset-san-diego-no")

    assert metadata["market_close_time"] == "2026-05-02 15:42 PDT"
    assert metadata["market_close_time_kind"] == "actual_close"

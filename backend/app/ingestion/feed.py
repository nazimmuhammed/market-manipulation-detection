import random
import requests
from datetime import datetime
from app.core.config import TICKERS, TICKER_DISPLAY, TWELVE_DATA_API_KEY, TWELVE_DATA_SYMBOLS
from app.db import neo4j_client

class MarketFeed:
    def __init__(self):
        self.tick_history = {TICKER_DISPLAY[t]: [] for t in TICKERS}
        self.injected_scenario = None

    def inject_scenario(self, ticker, scenario, length_ticks=15):
        self.injected_scenario = {"ticker": ticker, "scenario": scenario, "tick": 0, "len": length_ticks}

    def _fetch_twelve_data(self):
        results = {}
        try:
            symbols = ",".join(TWELVE_DATA_SYMBOLS.values())
            url = f"https://api.twelvedata.com/quote?symbol={symbols}&apikey={TWELVE_DATA_API_KEY}"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if len(TWELVE_DATA_SYMBOLS) == 1:
                data = {list(TWELVE_DATA_SYMBOLS.values())[0]: data}
            for ticker, symbol in TWELVE_DATA_SYMBOLS.items():
                d = data.get(symbol)
                if not d or "close" not in d:
                    continue
                results[ticker] = {
                    "close": float(d["close"]), "open": float(d.get("open", d["close"])),
                    "high": float(d.get("high", d["close"])), "low": float(d.get("low", d["close"])),
                    "volume": int(float(d.get("volume", 10000)) or 10000),
                }
        except Exception as e:
            print(f"Twelve Data unavailable ({e})")
            return None
        return results if results else None

    def poll(self, conn):
        live_data = self._fetch_twelve_data()
        return self._synthetic_poll(conn, live_data)


    

    def _apply_scenario(self, close, volume, base_price=None):
        sc = self.injected_scenario
        progress = sc["tick"] / sc["len"]
        meta = {"scenario": sc["scenario"], "progress": round(progress, 2), "overlay": True}
        pool_ranges = {
            "insider_trading": 9001,
            "pump_and_dump": 8001,
            "spoofing": 7001,
            "layering": 6001,
        }
        base_id = pool_ranges.get(sc["scenario"], 9001)
        pool = [f"T{base_id+i}" for i in range(4)]
        base = base_price or close

        if sc["scenario"] == "pump_and_dump":
            mult = 1.03 if progress < 0.6 else 0.97
            close = round(base * mult, 2)
            volume = int(volume * (4 if progress < 0.6 else 6))
            trades = [{"trader": t, "side": "buy" if progress < 0.6 else "sell", "qty": volume // 4} for t in pool]
        elif sc["scenario"] == "insider_trading":
            if progress < 0.8:
                volume = int(volume * 1.8)
                trades = [{"trader": p, "side": "buy", "qty": volume // len(pool)} for p in pool]
            else:
                close = round(base * 1.05, 2)
                volume = int(volume * 2.5)
                trades = [{"trader": p, "side": "buy", "qty": volume // len(pool)} for p in pool]
                meta["insider_cluster"] = pool
        elif sc["scenario"] == "spoofing":
            volume = int(volume * 1.1)
            trades = [{"trader": p, "side": "buy", "qty": volume // len(pool)} for p in pool]
            meta["order_book_imbalance"] = 0.85
        elif sc["scenario"] == "layering":
            volume = int(volume * 1.5)
            trades = [{"trader": p, "side": "buy" if i % 2 == 0 else "sell", "qty": 100} for i, p in enumerate(pool * 2)]
        else:
            trades = [{"trader": f"T{random.randint(1000,9999)}", "side": "buy", "qty": volume}]

        sc["tick"] += 1
        if sc["tick"] >= sc["len"]:
            self.injected_scenario = None
        return close, volume, trades, meta

    def _synthetic_poll(self, conn, live_data=None):
        out = []
        cur = conn.cursor()
        for ticker in TICKERS:
            display = TICKER_DISPLAY[ticker]
            last = self.tick_history[display][-1] if self.tick_history[display] else None
            base_price = last["close"] if last else round(random.uniform(500, 3000), 2)

            pct = random.gauss(0, 0.006)
            close = round(base_price * (1 + pct), 2)

            # If real data is available, gently pull synthetic price toward it
            # instead of jumping straight to it — keeps chart smooth for demo
            real = live_data.get(ticker) if live_data else None
            if real and "close" in real:
                real_close = real["close"]
                pull_strength = 0.15  # how much of the gap to close each tick (0-1)
                close = round(close + (real_close - close) * pull_strength, 2)

            volume = random.randint(10000, 100000)
            meta = {}
            trades = [{"trader": f"T{random.choice(range(1000, 1300))}", "side": "buy", "qty": volume}]
            if self.injected_scenario and self.injected_scenario["ticker"] == display:
                close, volume, trades, meta = self._apply_scenario(close, volume, base_price=base_price)
            payload = {
                "ticker": display, "open": base_price, "high": max(base_price, close),
                "low": min(base_price, close), "close": close, "volume": volume,
                "timestamp": datetime.now(), "trades": trades, "meta": meta,
            }
            cur.execute(
                "INSERT INTO price_ticks (ticker, open, high, low, close, volume, tick_timestamp, scenario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING tick_id",
                (payload["ticker"], payload["open"], payload["high"], payload["low"], payload["close"],
                payload["volume"], payload["timestamp"], meta.get("scenario"))
            )
            tick_id = cur.fetchone()[0]
            for tr in trades:
                cur.execute("INSERT INTO trades (tick_id, ticker, trader_id, side, qty) VALUES (%s,%s,%s,%s,%s)",
                            (tick_id, display, tr["trader"], tr["side"], tr["qty"]))
            neo4j_client.write_trade_edges(trades)
            self.tick_history[display].append(payload)
            out.append(payload)
        return out

market_feed = MarketFeed()
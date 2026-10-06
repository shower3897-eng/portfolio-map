import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
KST = ZoneInfo("Asia/Seoul")

SYMBOLS = {
    "329180": "329180.KS",
    "009540": "009540.KS",
    "010140": "010140.KS",
    "017960": "017960.KS",
    "082740": "082740.KS",
    "032500": "032500.KQ",
    "005935": "005935.KS",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


def get_recent_closes(code: str):
    symbol = SYMBOLS.get(code)
    if not symbol:
        raise RuntimeError(f"{code}: Yahoo symbol mapping이 없습니다.")

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "10d", "interval": "1d", "events": "history"}

    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    payload = r.json()

    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise RuntimeError(f"{code}: Yahoo 응답 오류: {err}")

    block = result[0]
    timestamps = block.get("timestamp") or []
    closes = (((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])

    rows = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=KST)
        rows.append((dt.date().isoformat(), float(close)))

    if len(rows) < 2:
        raise RuntimeError(f"{code}: 최근 2거래일 종가를 읽지 못했습니다.")

    return rows[-1], rows[-2]


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    stock_rows = [item for item in data["items"] if item.get("code")]
    if not stock_rows:
        raise RuntimeError("종목 코드가 없습니다.")

    prices = {}
    latest_dates = set()

    for item in stock_rows:
        latest, previous = get_recent_closes(item["code"])
        prices[item["code"]] = {
            "latest_date": latest[0],
            "close": latest[1],
            "prev_date": previous[0],
            "prev_close": previous[1],
        }
        latest_dates.add(latest[0])

    if len(latest_dates) != 1:
        raise RuntimeError(f"종목별 최신 거래일이 다릅니다: {sorted(latest_dates)}")

    latest_date = next(iter(latest_dates))
    if data.get("asOfDate") == latest_date:
        print(f"이미 최신 종가 반영 완료: {latest_date}")
        return

    adjusted = []

    for item in data["items"]:
        code = item.get("code")
        weight = float(item.get("weight", 0))

        if not code:
            item["dailyChange"] = None
            adjusted.append((item, weight))
            continue

        p = prices[code]
        close = p["close"]
        prev_close = p["prev_close"]
        old_close = item.get("lastClose")

        price_factor = close / float(old_close) if old_close and float(old_close) > 0 else 1.0

        old_hr = item.get("holdingReturn")
        if old_hr is not None:
            item["holdingReturn"] = ((1 + float(old_hr) / 100.0) * price_factor - 1) * 100.0

        item["dailyChange"] = (close / prev_close - 1) * 100.0 if prev_close > 0 else None
        item["lastClose"] = int(round(close))
        adjusted.append((item, weight * price_factor))

    total = sum(v for _, v in adjusted)
    if total <= 0:
        raise RuntimeError("포트폴리오 비중 합계가 0 이하입니다.")

    for item, adjusted_weight in adjusted:
        item["weight"] = adjusted_weight / total * 100.0

    sample = next(iter(prices.values()))
    data["asOfDate"] = latest_date
    data["previousTradingDate"] = sample["prev_date"]
    data["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")

    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"업데이트 완료: {latest_date}")


if __name__ == "__main__":
    main()

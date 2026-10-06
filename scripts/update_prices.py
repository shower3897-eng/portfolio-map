import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
KST = ZoneInfo("Asia/Seoul")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}


def get_recent_closes(code: str):
    url = f"https://finance.naver.com/item/sise_day.naver?code={code}&page=1"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = "euc-kr"

    soup = BeautifulSoup(r.text, "html.parser")
    rows = []

    for tr in soup.select("table.type2 tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue

        date_text = tds[0].get_text(strip=True)
        close_text = tds[1].get_text(strip=True).replace(",", "")

        if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", date_text):
            continue
        if not close_text.isdigit():
            continue

        rows.append((date_text.replace(".", "-"), float(close_text)))

    if len(rows) < 2:
        raise RuntimeError(f"{code}: 최근 2거래일 종가를 읽지 못했습니다.")

    return rows[0], rows[1]


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
        item["lastClose"] = int(close)
        adjusted.append((item, weight * price_factor))

    total = sum(v for _, v in adjusted)
    if total <= 0:
        raise RuntimeError("포트폴리오 비중 합계가 0 이하입니다.")

    for item, adjusted_weight in adjusted:
        item["weight"] = adjusted_weight / total * 100.0

    data["asOfDate"] = latest_date
    data["previousTradingDate"] = next(iter(prices.values()))["prev_date"]
    data["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")

    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"업데이트 완료: {latest_date}")


if __name__ == "__main__":
    main()

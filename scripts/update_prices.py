import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pykrx import stock

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
KST = ZoneInfo("Asia/Seoul")


def market_frame(day):
    return stock.get_market_ohlcv_by_ticker(day.strftime("%Y%m%d"), market="ALL")


def find_trading_day(start_day, max_lookback=10):
    day = start_day
    for _ in range(max_lookback):
        df = market_frame(day)
        if df is not None and not df.empty and "종가" in df.columns:
            return day, df
        day -= timedelta(days=1)
    raise RuntimeError("최근 거래일을 찾지 못했습니다.")


def previous_trading_day(day):
    prev, df = find_trading_day(day - timedelta(days=1), 10)
    return prev, df


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    today = datetime.now(KST).date()

    latest_day, latest_df = find_trading_day(today)
    prev_day, prev_df = previous_trading_day(latest_day)

    latest_str = latest_day.isoformat()
    previous_asof = data.get("asOfDate")

    # 휴장일/중복 실행이면 데이터 변경 없이 종료
    if previous_asof == latest_str:
        print(f"이미 최신 종가 반영 완료: {latest_str}")
        return

    adjusted = []

    for item in data["items"]:
        code = item.get("code")
        weight = float(item.get("weight", 0))

        if not code:
            item["dailyChange"] = None
            adjusted.append((item, weight))
            continue

        if code not in latest_df.index:
            raise RuntimeError(f"{code} {item['name']} 최신 종가를 찾을 수 없습니다.")

        close = float(latest_df.loc[code, "종가"])
        prev_close = float(prev_df.loc[code, "종가"]) if code in prev_df.index else None
        old_close = item.get("lastClose")

        if old_close and float(old_close) > 0:
            price_factor = close / float(old_close)
        else:
            price_factor = 1.0

        old_hr = item.get("holdingReturn")
        if old_hr is not None:
            item["holdingReturn"] = ((1 + float(old_hr) / 100.0) * price_factor - 1) * 100.0

        if prev_close and prev_close > 0:
            item["dailyChange"] = (close / prev_close - 1) * 100.0
        else:
            item["dailyChange"] = None

        item["lastClose"] = int(close)
        adjusted.append((item, weight * price_factor))

    total = sum(v for _, v in adjusted)
    if total <= 0:
        raise RuntimeError("포트폴리오 비중 합계가 0 이하입니다.")

    for item, adjusted_weight in adjusted:
        item["weight"] = adjusted_weight / total * 100.0

    data["asOfDate"] = latest_str
    data["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    data["previousTradingDate"] = prev_day.isoformat()

    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"업데이트 완료: {latest_str}")


if __name__ == "__main__":
    main()

import os
import requests
from datetime import datetime, timezone

headers = {"User-Agent": "Mozilla/5.0"}

MIN_RISK = 3.0
MAX_AGE = 9000
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
STATE_FILE = "last_signal_1h.txt"


def load_last():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def save_last(value):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(value)
    except Exception as e:
        print("خطا در ذخیره وضعیت:", e)


def send_notify(text):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC تنظیم نشده، اعلان نفرستادم")
        return
    try:
        r = requests.post(
            NTFY_URL,
            data=text.encode("utf-8"),
            headers={"Title": "Gold 1H Signal"},
            timeout=20
        )
        print("ntfy status:", r.status_code)
    except Exception as e:
        print("خطا در ارسال اعلان:", e)


def trend_of(candles):
    hh = 0
    hl = 0
    lh = 0
    ll = 0
    for i in range(1, len(candles)):
        if candles[i][2] > candles[i-1][2]:
            hh += 1
        else:
            lh += 1
        if candles[i][3] > candles[i-1][3]:
            hl += 1
        else:
            ll += 1
    if hh >= 3 and hl >= 3:
        return "صعودی"
    if lh >= 3 and ll >= 3:
        return "نزولی"
    return "خنثی"


def analyze():
    last_signal = load_last()

    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1h&range=1mo"
    r = requests.get(url, headers=headers, timeout=20)
    print("status:", r.status_code)

    data = r.json()["chart"]["result"][0]
    times = data["timestamp"]
    q = data["indicators"]["quote"][0]

    hourly = []
    for i in range(len(times)):
        t = times[i]
        o = q["open"][i]
        h = q["high"][i]
        l = q["low"][i]
        c = q["close"][i]
        if None in (o, h, l, c):
            continue
        if t % 3600 != 0:
            continue
        hourly.append((t, o, h, l, c))

    now = datetime.now(timezone.utc).timestamp()

    blocks = {}
    for t, o, h, l, c in hourly:
        key = t // 14400
        blocks.setdefault(key, []).append((t, o, h, l, c))

    candles4h = []
    for key in sorted(blocks):
        group = blocks[key]
        start = key * 14400
        o = group[0][1]
        h = max(x[2] for x in group)
        l = min(x[3] for x in group)
        c = group[-1][4]
        if start + 14400 <= now:
            candles4h.append((start, o, h, l, c))

    h_closed = [x for x in hourly if x[0] + 3600 <= now]

    trend4 = trend_of(candles4h[-6:])
    trend1 = trend_of(h_closed[-6:])

    age = now - (h_closed[-1][0] + 3600)
    print("سن آخرین کندل بسته (دقیقه):", int(age / 60))

    rs = requests.get("https://api.gold-api.com/price/XAU", timeout=20)
    spot = rs.json()["price"]
    closes = [c for c in q["close"] if c is not None]
    offset = closes[-1] - spot

    has_signal = False
    reason = "۴ ساعته و ۱ ساعته هم‌جهت نیستند"
    entry = 0
    sl = 0
    tp = 0
    risk = 0

    if age > MAX_AGE:
        reason = "داده ۱ ساعته کهنه است"
    elif trend4 == trend1 and trend4 != "خنثی":
        last6 = h_closed[-6:]
        entry = last6[-1][4]
        low6 = min(x[3] for x in last6)
        high6 = max(x[2] for x in last6)
        if trend4 == "صعودی":
            sl = low6
            risk = entry - sl
            tp = entry + 2 * risk
        else:
            sl = high6
            risk = sl - entry
            tp = entry - 2 * risk
        if risk < MIN_RISK:
            reason = "حد ضرر خیلی نزدیک است (SL too close)"
        else:
            has_signal = True

    last_time = datetime.fromtimestamp(h_closed[-1][0], timezone.utc).strftime("%Y-%m-%d %H:%M")

    print("")
    print("======== گزارش ۱ ساعته ========")
    print("آخرین کندل بسته ۱ ساعته (UTC):", last_time)
    print("قیمت اسپات الان:", round(spot, 1))
    print("فرق آتی و اسپات:", round(offset, 1))
    print("روند ۴ ساعته:", trend4)
    print("روند ۱ ساعته:", trend1)
    if has_signal:
        print("جهت احتمالی:", trend4)
        print("Entry:", round(entry - offset, 1))
        print("SL:", round(sl - offset, 1))
        print("TP:", round(tp - offset, 1))
        print("ریسک:", round(risk, 1))
        print("ریسک به ریوارد: 1 به 2")
        if trend4 != last_signal:
            msg = (
                "جهت احتمالی: " + trend4 + "\n"
                + "Entry: " + str(round(entry - offset, 1)) + "\n"
                + "SL: " + str(round(sl - offset, 1)) + "\n"
                + "TP: " + str(round(tp - offset, 1)) + "\n"
                + "ریسک: " + str(round(risk, 1)) + "\n"
                + "کندل ۱ ساعته (UTC): " + last_time + "\n"
                + "این فقط تحلیل است، سیگنال معامله نیست"
            )
            send_notify(msg)
            save_last(trend4)
        else:
            print("اعلان تکراری است، نفرستادم")
    else:
        print("NO TRADE")
        print("دلیل:", reason)
        if age <= MAX_AGE:
            save_last("")
    print("این فقط تحلیل است، سیگنال معامله نیست")
    print("===============================")


try:
    analyze()
except Exception as e:
    print("خطا:", e)

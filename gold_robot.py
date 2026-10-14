import os
import requests
from datetime import datetime, timezone

headers = {"User-Agent": "Mozilla/5.0"}

MIN_RISK = 3.0
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
STATE_FILE = "last_signal.txt"


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
            headers={"Title": "Gold Signal"},
            timeout=20
        )
        print("ntfy status:", r.status_code)
    except Exception as e:
        print("خطا در ارسال اعلان:", e)


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

    blocks = {}
    for t, o, h, l, c in hourly:
        key = t // 14400
        blocks.setdefault(key, []).append((t, o, h, l, c))

    now = datetime.now(timezone.utc).timestamp()

    candles4h = []
    for key in sorted(blocks):
        group = blocks[key]
        start = key * 14400
        o = group[0][1]
        h = max(x[2] for x in group)
        l = min(x[3] for x in group)
        c = group[-1][4]
        closed = (start + 14400 <= now)
        candles4h.append((start, o, h, l, c, closed))

    closed_list = [x for x in candles4h if x[5]]
    last = closed_list[-6:]

    hh = 0
    hl = 0
    lh = 0
    ll = 0
    for i in range(1, len(last)):
        if last[i][2] > last[i-1][2]:
            hh += 1
        else:
            lh += 1
        if last[i][3] > last[i-1][3]:
            hl += 1
        else:
            ll += 1

    h_closed = [x for x in hourly if x[0] + 3600 <= now]
    last1 = h_closed[-6:]

    hh1 = 0
    hl1 = 0
    lh1 = 0
    ll1 = 0
    for i in range(1, len(last1)):
        if last1[i][2] > last1[i-1][2]:
            hh1 += 1
        else:
            lh1 += 1
        if last1[i][3] > last1[i-1][3]:
            hl1 += 1
        else:
            ll1 += 1

    trend4 = "صعودی" if (hh >= 3 and hl >= 3) else ("نزولی" if (lh >= 3 and ll >= 3) else "خنثی")
    trend1 = "صعودی" if (hh1 >= 3 and hl1 >= 3) else ("نزولی" if (lh1 >= 3 and ll1 >= 3) else "خنثی")

    url15 = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=15m&range=5d"
    r15 = requests.get(url15, headers=headers, timeout=20)
    print("15m status:", r15.status_code)

    d15 = r15.json()["chart"]["result"][0]
    t15 = d15["timestamp"]
    q15 = d15["indicators"]["quote"][0]

    m15 = []
    for i in range(len(t15)):
        o = q15["open"][i]
        h = q15["high"][i]
        l = q15["low"][i]
        c = q15["close"][i]
        if None in (o, h, l, c):
            continue
        if t15[i] % 900 != 0:
            continue
        m15.append((t15[i], o, h, l, c))

    m15_closed = [x for x in m15 if x[0] + 900 <= now]

    rs = requests.get("https://api.gold-api.com/price/XAU", timeout=20)
    spot = rs.json()["price"]
    closes15 = [c for c in q15["close"] if c is not None]
    offset = closes15[-1] - spot

    has_signal = False
    reason = "۴ ساعته و ۱ ساعته هم‌جهت نیستند"
    entry = 0
    sl = 0
    tp = 0
    risk = 0

    if trend4 == trend1 and trend4 != "خنثی":
        last15 = m15_closed[-6:]
        entry = last15[-1][4]
        low15 = min(x[3] for x in last15)
        high15 = max(x[2] for x in last15)
        if trend4 == "صعودی":
            sl = low15
            risk = entry - sl
            tp = entry + 2 * risk
        else:
            sl = high15
            risk = sl - entry
            tp = entry - 2 * risk
        if risk < MIN_RISK:
            reason = "حد ضرر خیلی نزدیک است (SL too close)"
        else:
            has_signal = True

    last_time = datetime.fromtimestamp(m15_closed[-1][0], timezone.utc).strftime("%Y-%m-%d %H:%M")

    print("")
    print("======== گزارش نهایی ========")
    print("آخرین کندل بسته ۱۵ دقیقه (UTC):", last_time)
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
                + "کندل ۱۵ دقیقه (UTC): " + last_time + "\n"
                + "این فقط تحلیل است، سیگنال معامله نیست"
            )
            send_notify(msg)
            save_last(trend4)
        else:
            print("اعلان تکراری است، نفرستادم")
    else:
        print("NO TRADE")
        print("دلیل:", reason)
        save_last("")
    print("این فقط تحلیل است، سیگنال معامله نیست")
    print("=============================")


try:
    analyze()
except Exception as e:
    print("خطا:", e)

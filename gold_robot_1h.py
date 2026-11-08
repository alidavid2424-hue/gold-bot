import os
import requests
from datetime import datetime, timezone

headers = {"User-Agent": "Mozilla/5.0"}

MIN_RISK = 6.0
MAX_RISK = 60.0
MAX_AGE = 9000
MAX_OPEN_HOURS = 48
ACCOUNT = 1000.0
RISK_PERCENT = 1.5
RISK_DOLLAR = ACCOUNT * RISK_PERCENT / 100
OUNCE_PER_LOT = 100
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
STATE_FILE = "last_signal_1h.txt"


def load_last():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            parts = f.read().strip().split("|")
        if len(parts) < 5:
            return None
        return {
            "dir": parts[0],
            "entry": float(parts[1]),
            "sl": float(parts[2]),
            "tp": float(parts[3]),
            "end": float(parts[4]),
        }
    except Exception:
        return None


def save_last(direction, entry, sl, tp, end):
    try:
        value = "|".join([direction, str(entry), str(sl), str(tp), str(end)])
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(value)
    except Exception as e:
        print("خطا در ذخیره وضعیت:", e)


def clear_last():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write("")
    except Exception as e:
        print("خطا در پاک کردن وضعیت:", e)


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


def check_open(last, hourly, now):
    if now - last["end"] > MAX_OPEN_HOURS * 3600:
        return False, "منقضی شد (بیش از 48 ساعت)"
    for t, o, h, l, c in hourly:
        if t < last["end"]:
            continue
        if last["dir"] == "صعودی":
            if l <= last["sl"]:
                return False, "SL خورد"
            if h >= last["tp"]:
                return False, "TP خورد"
        else:
            if h >= last["sl"]:
                return False, "SL خورد"
            if l <= last["tp"]:
                return False, "TP خورد"
    return True, "هنوز باز است"


def analyze():
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

    last = load_last()
    prev_text = "ندارد"
    if last is not None:
        is_open, status = check_open(last, hourly, now)
        prev_text = last["dir"] + " - " + status
        if not is_open:
            clear_last()
            last = None

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

    end_time = h_closed[-1][0] + 3600
    age = now - end_time
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
        elif risk > MAX_RISK:
            reason = "حد ضرر خیلی دور است (SL too far)"
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
    print("سیگنال قبلی:", prev_text)
    if has_signal:
        lot = round(RISK_DOLLAR / (risk * OUNCE_PER_LOT), 3)
        print("جهت احتمالی:", trend4)
        print("Entry:", round(entry - offset, 1))
        print("SL:", round(sl - offset, 1))
        print("TP:", round(tp - offset, 1))
        print("ریسک:", round(risk, 1))
        print("ریسک به ریوارد: 1 به 2")
        print("ریسک پولی:", RISK_DOLLAR, "دلار - لات:", lot)
        if last is not None and last["dir"] == trend4:
            print("سیگنال قبلی هم‌جهت هنوز باز است، سیگنال جدید نفرستادم")
        else:
            msg = (
                "جهت احتمالی: " + trend4 + "\n"
                + "Entry: " + str(round(entry - offset, 1)) + "\n"
                + "SL: " + str(round(sl - offset, 1)) + "\n"
                + "TP: " + str(round(tp - offset, 1)) + "\n"
                + "ریسک: " + str(round(risk, 1)) + "\n"
                + "ریسک پولی: " + str(RISK_DOLLAR) + " دلار (" + str(RISK_PERCENT) + "٪)\n"
                + "لات: " + str(lot) + "\n"
                + "کندل ۱ ساعته (UTC): " + last_time + "\n"
                + "این فقط تحلیل است، سیگنال معامله نیست"
            )
            send_notify(msg)
            save_last(trend4, entry, sl, tp, end_time)
    else:
        print("NO TRADE")
        print("دلیل:", reason)
    print("این فقط تحلیل است، سیگنال معامله نیست")
    print("===============================")


try:
    analyze()
except Exception as e:
    print("خطا:", e)

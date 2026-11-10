import os
import requests
from datetime import datetime, timezone

headers = {"User-Agent": "Mozilla/5.0"}

MIN_RISK = 6.0
MAX_OPEN_HOURS = 48
RISK_PER_SIGNAL = 1.5
RR = 2.0
DAILY_LIMIT = 3.0
TOTAL_LIMIT = 10.0
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = "https://ntfy.sh/" + NTFY_TOPIC
STATE_FILE = "last_signal.txt"


def day_of(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def load_state():
    # فرمت: جهت|ورود|زمان ارسال|SL|TP|پایان کندل سیگنال|شمرده شده|کل|روز|ضرر روز
    st = {
        "dir": "", "entry": 0.0, "sent": 0.0, "sl": 0.0, "tp": 0.0,
        "sig_end": 0.0, "counted": 0.0, "total": 0.0, "day": "", "day_r": 0.0
    }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception:
        return st
    parts = text.split("|")
    st["dir"] = parts[0]
    if len(parts) >= 6:
        try:
            st["entry"] = float(parts[1])
            st["sent"] = float(parts[2])
            st["sl"] = float(parts[3])
            st["tp"] = float(parts[4])
            st["sig_end"] = float(parts[5])
            st["counted"] = st["sig_end"]
        except Exception:
            pass
    if len(parts) >= 10:
        try:
            st["counted"] = float(parts[6])
            st["total"] = float(parts[7])
            st["day"] = parts[8]
            st["day_r"] = float(parts[9])
        except Exception:
            pass
    return st


def save_state(st):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(
                st["dir"] + "|" + str(st["entry"]) + "|" + str(st["sent"]) + "|"
                + str(st["sl"]) + "|" + str(st["tp"]) + "|" + str(st["sig_end"]) + "|"
                + str(st["counted"]) + "|" + str(st["total"]) + "|"
                + st["day"] + "|" + str(st["day_r"])
            )
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


def previous_status(st, m15_closed, offset, now):
    # نتیجه: none / open / SL / TP / expired
    if st["dir"] == "" or st["sl"] == 0 or st["tp"] == 0 or st["sig_end"] == 0:
        return "none", 0
    for t, o, h, l, c in m15_closed:
        if t < st["sig_end"]:
            continue
        hi = h - offset
        lo = l - offset
        if st["dir"] == "صعودی":
            if lo <= st["sl"]:
                return "SL", t + 900
            if hi >= st["tp"]:
                return "TP", t + 900
        else:
            if hi >= st["sl"]:
                return "SL", t + 900
            if lo <= st["tp"]:
                return "TP", t + 900
    if now - st["sig_end"] > MAX_OPEN_HOURS * 3600:
        return "expired", 0
    return "open", 0


def update_risk(st, status, close_t):
    # اگر نتیجه سیگنال قبلی تازه معلوم شده، به حساب ضرر و سود اضافه می‌کند
    if st["dir"] == "" or st["sig_end"] == 0:
        return False
    if st["counted"] == st["sig_end"]:
        return False
    if status == "expired":
        st["counted"] = st["sig_end"]
        return True
    if status != "SL" and status != "TP":
        return False
    if status == "SL":
        pnl = -RISK_PER_SIGNAL
    else:
        pnl = RR * RISK_PER_SIGNAL
    day = day_of(close_t)
    if st["day"] != day:
        st["day"] = day
        st["day_r"] = 0.0
    st["day_r"] += pnl
    st["total"] += pnl
    st["counted"] = st["sig_end"]
    return True


def analyze():
    st = load_state()

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
    today = day_of(now)

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
    trend4_real = trend4
    if trend4 == "خنثی":
        trend4 = trend1

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

    # نتیجه سیگنال قبلی و حساب ضرر و سود
    status, close_t = previous_status(st, m15_closed, offset, now)
    if update_risk(st, status, close_t):
        save_state(st)

    day_r_today = st["day_r"] if st["day"] == today else 0.0
    blocked_reason = ""
    if st["total"] <= -TOTAL_LIMIT:
        blocked_reason = "حد ضرر کل ۱۰٪ خورده"
    elif day_r_today <= -DAILY_LIMIT:
        blocked_reason = "حد ضرر روزانه ۳٪ خورده"

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
    print("روند ۴ ساعته:", trend4_real)
    print("روند ۱ ساعته:", trend1)
    print("سیگنال قبلی:", status)
    print("سود/ضرر امروز (٪):", round(day_r_today, 1))
    print("سود/ضرر کل (٪):", round(st["total"], 1))
    if has_signal:
        entry_spot = round(entry - offset, 1)
        sl_spot = round(sl - offset, 1)
        tp_spot = round(tp - offset, 1)
        print("جهت احتمالی:", trend4)
        print("Entry:", entry_spot)
        print("SL:", sl_spot)
        print("TP:", tp_spot)
        print("ریسک:", round(risk, 1))
        print("ریسک به ریوارد: 1 به 2")

        if blocked_reason:
            print("NO TRADE:", blocked_reason)
            print("اعلان نفرستادم")
        else:
            should_send = False
            if trend4 != st["dir"]:
                should_send = True
            elif status == "open":
                print("سیگنال قبلی هنوز باز است (نه TP نه SL)، سیگنال جدید نفرستادم")
            else:
                should_send = True

            if should_send:
                msg = (
                    "جهت احتمالی: " + trend4 + "\n"
                    + "Entry: " + str(entry_spot) + "\n"
                    + "SL: " + str(sl_spot) + "\n"
                    + "TP: " + str(tp_spot) + "\n"
                    + "ریسک: " + str(round(risk, 1)) + "\n"
                    + "کندل ۱۵ دقیقه (UTC): " + last_time + "\n"
                    + "این فقط تحلیل است، سیگنال معامله نیست"
                )
                send_notify(msg)
                st["dir"] = trend4
                st["entry"] = entry_spot
                st["sent"] = now
                st["sl"] = sl_spot
                st["tp"] = tp_spot
                st["sig_end"] = m15_closed[-1][0] + 900
                save_state(st)
    else:
        print("NO TRADE")
        print("دلیل:", reason)
    print("این فقط تحلیل است، سیگنال معامله نیست")
    print("=============================")


try:
    analyze()
except Exception as e:
    print("خطا:", e)

import os
import json
from datetime import datetime
import requests

BASE_URL = "https://eu5.fusionsolar.huawei.com"

FS_USERNAME = os.environ["FUSIONSOLAR_USERNAME"]
FS_PASSWORD = os.environ["FUSIONSOLAR_PASSWORD"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BATTERY_DEV_ID = "1000000147306576"
BATTERY_DEV_TYPE_ID = 39

INVERTER_DEV_ID = "1000000147306575"
INVERTER_DEV_TYPE_ID = 38

STATE_FILE = "state.json"

LATITUDE = 44.768
LONGITUDE = 8.704
TIMEZONE = "Europe/Rome"

BATTERY_CAPACITY_KWH = 10.0
RESET_THRESHOLD = 75.0


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "notified_80": False,
            "notified_100": False
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text
        },
        timeout=30
    )
    r.raise_for_status()


def fs_login(session: requests.Session):
    url = f"{BASE_URL}/thirdData/login"
    payload = {
        "userName": FS_USERNAME,
        "systemCode": FS_PASSWORD
    }

    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()

    token = None

    if "XSRF-TOKEN" in session.cookies:
        token = session.cookies.get("XSRF-TOKEN")

    if not token:
        token = r.headers.get("XSRF-TOKEN")

    if not token:
        raise RuntimeError("Token XSRF non trovato dopo il login")

    session.headers.update({
        "XSRF-TOKEN": token,
        "Content-Type": "application/json"
    })


def get_device_kpi(session: requests.Session, dev_type_id: int, dev_id: str):
    url = f"{BASE_URL}/thirdData/getDevRealKpi"
    payload = {
        "devTypeId": dev_type_id,
        "devIds": dev_id
    }

    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()

    data = r.json()

    if not data.get("success"):
        raise RuntimeError(f"Errore FusionSolar: {data}")

    items = data.get("data", [])
    if not items:
        raise RuntimeError(f"Nessun dato restituito: {data}")

    return items[0]["dataItemMap"]


def get_weather_forecast():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}"
        f"&longitude={LONGITUDE}"
        f"&hourly=temperature_2m,cloud_cover,shortwave_radiation"
        f"&forecast_days=2"
        f"&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def get_night_temperatures(weather_data):
    hourly = weather_data["hourly"]
    times = hourly["time"]
    temps = hourly["temperature_2m"]

    night_values = []

    for t_str, temp in zip(times, temps):
        dt = datetime.fromisoformat(t_str)
        hour = dt.hour
        if hour >= 22 or hour < 6:
            night_values.append(temp)

    if not night_values:
        return None, None

    avg_temp = round(sum(night_values) / len(night_values), 1)
    min_temp = round(min(night_values), 1)
    return avg_temp, min_temp


def estimate_fill_time_100(current_soc, weather_data):
    if current_soc >= 100:
        return "gia piena"

    needed_kwh = BATTERY_CAPACITY_KWH * (100 - current_soc) / 100.0

    hourly = weather_data["hourly"]
    times = hourly["time"]
    radiation = hourly["shortwave_radiation"]
    cloud_cover = hourly["cloud_cover"]

    estimated_energy = 0.0
    now = datetime.now()

    for t_str, rad, cloud in zip(times, radiation, cloud_cover):
        dt = datetime.fromisoformat(t_str)

        if dt < now:
            continue

        factor = max(0.0, 1.0 - (cloud / 100.0) * 0.6)
        hourly_kwh = min((rad / 1000.0) * 6.0 * factor, 4.5)
        net_hourly_kwh = max(0.0, hourly_kwh - 0.4)

        estimated_energy += net_hourly_kwh

        if estimated_energy >= needed_kwh:
            return dt.strftime("%H:%M")

    return "non stimabile oggi"


def main():
    state = load_state()

    session = requests.Session()
    fs_login(session)

    battery = get_device_kpi(session, BATTERY_DEV_TYPE_ID, BATTERY_DEV_ID)
    inverter = get_device_kpi(session, INVERTER_DEV_TYPE_ID, INVERTER_DEV_ID)

    battery_soc = float(battery.get("battery_soc", 0))
    solar_power = float(inverter.get("active_power", 0))
    day_energy = float(inverter.get("day_cap", 0))

    weather = get_weather_forecast()
    night_avg, night_min = get_night_temperatures(weather)
    eta_100 = estimate_fill_time_100(battery_soc, weather)

    if battery_soc < RESET_THRESHOLD:
        state["notified_80"] = False
        state["notified_100"] = False

    if battery_soc >= 80 and not state["notified_80"]:
        text = (
            f"[TEST 80] Batteria al {battery_soc:.0f}%.\n"
            f"FV attuale: {solar_power} W\n"
            f"Stima arrivo al 100%: {eta_100}\n"
            f"Notte Basaluzzo 22-06: media {night_avg} C, minima {night_min} C"
        )
        send_telegram(text)
        state["notified_80"] = True

    if battery_soc >= 100 and not state["notified_100"]:
        text = (
            f"Batteria al 100%.\n"
            f"FV attuale: {solar_power} W\n"
            f"Energia prodotta oggi: {day_energy} kWh\n"
            f"Notte Basaluzzo 22-06: media {night_avg} C, minima {night_min} C"
        )
        send_telegram(text)
        state["notified_100"] = True

    save_state(state)


if __name__ == "__main__":
    main()

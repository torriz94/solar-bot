import os
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


def main():
    session = requests.Session()

    fs_login(session)

    battery = get_device_kpi(session, BATTERY_DEV_TYPE_ID, BATTERY_DEV_ID)
    inverter = get_device_kpi(session, INVERTER_DEV_TYPE_ID, INVERTER_DEV_ID)

    battery_soc = battery.get("battery_soc")
    battery_power = battery.get("ch_discharge_power")
    solar_power = inverter.get("active_power")
    day_energy = inverter.get("day_cap")

    text = (
        f"Batteria: {battery_soc}%\n"
        f"Potenza FV attuale: {solar_power} W\n"
        f"Potenza batteria: {battery_power} W\n"
        f"Energia prodotta oggi: {day_energy} kWh"
    )

    if battery_soc is not None and battery_soc >= 80:
        text += "\n\nBatteria sopra 80%: puoi accendere un carico elettrico."

    send_telegram(text)


if __name__ == "__main__":
    main()

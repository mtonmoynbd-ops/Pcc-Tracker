import os, json, requests
from bs4 import BeautifulSoup

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"

STEPS = [
    "Application Submitted",
    "Payment Confirmed",
    "Sent to Police Station",
    "Under Investigation",
    "Investigation Complete",
    "Sent to SP Office",
    "SP Office Approved",
    "Certificate Ready",
    "Certificate Delivered",
]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def login_and_get_applications():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    
    # Login page
    r = session.get("https://pcc.police.gov.bd/ords/r/pcc/pcc/home")
    soup = BeautifulSoup(r.text, "html.parser")
    
    # Find login form
    login_url = "https://pcc.police.gov.bd/ords/r/pcc/pcc/login"
    data = {
        "p_username": USERNAME,
        "p_password": PASSWORD,
    }
    session.post(login_url, data=data)
    
    # Get applications list
    r = session.get("https://pcc.police.gov.bd/ords/r/pcc/pcc/23")
    soup = BeautifulSoup(r.text, "html.parser")
    
    applications = []
    rows = soup.select("table tr")
    for row in rows[1:]:
        cols = row.select("td")
        if len(cols) >= 3:
            applications.append({
                "ref": cols[0].text.strip(),
                "name": cols[1].text.strip(),
                "status": cols[2].text.strip(),
            })
    return applications

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def main():
    old_state = load_state()
    
    try:
        apps = login_and_get_applications()
    except Exception as e:
        send_telegram(f"⚠️ PCC চেক করতে সমস্যা হয়েছে:\n{e}")
        return
    
    new_state = {}
    changes = []
    
    for app in apps:
        ref = app["ref"]
        status = app["status"]
        new_state[ref] = status
        
        if ref in old_state and old_state[ref] != status:
            changes.append(
                f"🔔 <b>{app['name']}</b>\n"
                f"📄 Ref: {ref}\n"
                f"⬅️ আগে: {old_state[ref]}\n"
                f"✅ এখন: {status}"
            )
    
    if changes:
        msg = "🇧🇩 <b>PCC স্ট্যাটাস পরিবর্তন!</b>\n\n" + "\n\n".join(changes)
        send_telegram(msg)
    
    save_state(new_state)
    print(f"চেক সম্পন্ন। {len(apps)} আবেদন, {len(changes)} পরিবর্তন।")

if __name__ == "__main__":
    main()

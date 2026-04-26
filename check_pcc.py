import os, json, requests
from bs4 import BeautifulSoup

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})
    print(f"Telegram response: {r.status_code} - {r.text}")

def login_and_get_applications():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    
    r = session.get("https://pcc.police.gov.bd/ords/r/pcc/pcc/home")
    print(f"Home page status: {r.status_code}")
    
    login_url = "https://pcc.police.gov.bd/ords/r/pcc/pcc/login"
    data = {
        "p_username": USERNAME,
        "p_password": PASSWORD,
    }
    r2 = session.post(login_url, data=data)
    print(f"Login status: {r2.status_code}")
    
    r3 = session.get("https://pcc.police.gov.bd/ords/r/pcc/pcc/23")
    print(f"Account page status: {r3.status_code}")
    print(f"Page content preview: {r3.text[:500]}")
    
    soup = BeautifulSoup(r3.text, "html.parser")
    
    applications = []
    rows = soup.select("table tr")
    print(f"Table rows found: {len(rows)}")
    
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
    send_telegram("🔄 PCC Checker চালু হয়েছে — লগইন করছি...")
    
    old_state = load_state()
    
    try:
        apps = login_and_get_applications()
    except Exception as e:
        send_telegram(f"⚠️ সমস্যা হয়েছে:\n{e}")
        return
    
    if not apps:
        send_telegram("⚠️ কোনো আবেদন পাওয়া যায়নি। লগইন সমস্যা হতে পারে।")
        return
    
    new_state = {}
    changes = []
    
    for app in apps:
        ref = app["ref"]
        status = app["status"]
        new_state[ref] = status
        
        if ref not in old_state:
            changes.append(f"🆕 <b>{app['name']}</b>\n📄 Ref: {ref}\n✅ স্ট্যাটাস: {status}")
        elif old_state[ref] != status:
            changes.append(
                f"🔔 <b>{app['name']}</b>\n"
                f"📄 Ref: {ref}\n"
                f"⬅️ আগে: {old_state[ref]}\n"
                f"✅ এখন: {status}"
            )
    
    if changes:
        msg = "🇧🇩 <b>PCC আপডেট!</b>\n\n" + "\n\n".join(changes)
        send_telegram(msg)
    else:
        send_telegram(f"✅ চেক সম্পন্ন। {len(apps)}টি আবেদন পাওয়া গেছে, কোনো পরিবর্তন নেই।")
    
    save_state(new_state)

if __name__ == "__main__":
    main()

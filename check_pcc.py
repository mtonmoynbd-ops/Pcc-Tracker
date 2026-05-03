import os, json, asyncio, requests, re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from datetime import datetime

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"
DATA_FILE = "docs/data.json"
RSS_FILE = "docs/rss.xml"
USERDATA_FILE = "docs/userdata.json"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})
    print(f"Telegram: {r.status_code}")

def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        if data and isinstance(list(data.values())[0], str):
            return {"statuses": data, "print_dates": {}, "status_history": {}}
        if "status_history" not in data:
            data["status_history"] = {}
        return data
    except:
        return {"statuses": {}, "print_dates": {}, "status_history": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_userdata():
    try:
        with open(USERDATA_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_data(applications):
    os.makedirs("docs", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump({
            "updated": datetime.now().strftime("%d-%b-%Y %I:%M %p"),
            "applications": applications
        }, f, ensure_ascii=False)

def save_rss(changes):
    os.makedirs("docs", exist_ok=True)
    now = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = ""
    for c in changes:
        items += f"""<item>
<title>{c['name']} - {c['new']}</title>
<link>https://mtonmoynbd-ops.github.io/Pcc-Tracker/</link>
<description>Ref: {c['ref']} | Before: {c['old']} - Now: {c['new']}</description>
<pubDate>{now}</pubDate>
<guid isPermaLink="false">{c['ref']}-{c['new']}-{datetime.now().strftime('%Y%m%d%H%M')}</guid>
</item>"""
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>PCC Tracker</title>
<link>https://mtonmoynbd-ops.github.io/Pcc-Tracker/</link>
<description>PCC Status Updates</description>
<language>bn</language>
<lastBuildDate>{now}</lastBuildDate>
<atom:link href="https://mtonmoynbd-ops.github.io/Pcc-Tracker/rss.xml" rel="self" type="application/rss+xml"/>
{items}
</channel>
</rss>"""
    with open(RSS_FILE, "w", encoding="utf-8") as f:
        f.write(rss)

def save_userdata(print_dates, status_history):
    os.makedirs("docs", exist_ok=True)
    existing = load_userdata()
    existing["print_dates"] = print_dates
    existing["status_history"] = status_history
    existing["script_updated"] = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    with open(USERDATA_FILE, "w") as f:
        json.dump(existing, f, ensure_ascii=False)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto("https://pcc.police.gov.bd/ords/r/pcc/pcc/login_desktop", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            await page.fill("input[type='text']", USERNAME)
            await page.fill("input[type='password']", PASSWORD)
            await page.click("button:has-text('Sign in')")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)

            current_url = page.url
            if "login" in current_url.lower():
                send_telegram("❌ লগইন ব্যর্থ।")
                await browser.close()
                return

            session_match = re.search(r'session=(\d+)', current_url)
            account_url = f"https://pcc.police.gov.bd/ords/r/pcc/pcc/23?session={session_match.group(1)}" if session_match else "https://pcc.police.gov.bd/ords/r/pcc/pcc/23"

            await page.goto(account_url, timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            if "login" in page.url.lower():
                send_telegram("❌ My Account পেজে যাওয়া যায়নি।")
                await browser.close()
                return

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            applications = []
            rows = soup.select("table tr")

            for row in rows[1:]:
                cols = row.select("td")
                if len(cols) >= 9:
                    ref = cols[0].text.strip()
                    apply_date = cols[3].text.strip()
                    phone = cols[4].text.strip()
                    name = cols[5].text.strip()
                    full_status = cols[8].text.strip()
                    match = re.match(r'(\d+/\d+)', full_status)
                    status = match.group(1) if match else full_status
                    if ref and len(ref) > 2:
                        applications.append({
                            "ref": ref,
                            "name": name,
                            "apply_date": apply_date,
                            "phone": phone,
                            "status": status
                        })

            if not applications:
                send_telegram("⚠️ আবেদন পাওয়া যায়নি।")
                await browser.close()
                return

            # Filter out 10/10 for data.json display
            display_apps = [a for a in applications if a["status"] != "10/10"]
            save_data(display_apps)

            old_state = load_state()
            old_statuses = old_state.get("statuses", {})
            old_print_dates = old_state.get("print_dates", {})
            old_history = old_state.get("status_history", {})

            new_statuses = {}
            new_print_dates = dict(old_print_dates)
            new_history = dict(old_history)
            changes = []
            new_files = []
            today_str = datetime.now().strftime("%d-%b-%Y")

            for app in applications:
                ref = app["ref"]
                status = app["status"]
                new_statuses[ref] = status

                # Track print date at 5/10
                num = int(status.split('/')[0]) if '/' in status else 0
                if num == 5 and ref not in new_print_dates:
                    new_print_dates[ref] = today_str

                # Status history
                if ref not in new_history:
                    new_history[ref] = []
                history_list = new_history[ref]
                if not history_list or history_list[-1]["status"] != status:
                    history_list.append({
                        "status": status,
                        "date": today_str
                    })
                new_history[ref] = history_list

                # New file
                if ref not in old_statuses:
                    new_files.append(app)
                # Status changed
                elif old_statuses[ref] != status:
                    changes.append({
                        "ref": ref,
                        "name": app["name"],
                        "old": old_statuses[ref],
                        "new": status,
                        "date": app["apply_date"]
                    })

            # Send notifications
            if new_files and old_statuses:  # Don't notify on very first run
                for app in new_files:
                    send_telegram(
                        f"🆕 <b>নতুন আবেদন!</b>\n\n"
                        f"<b>{app['name']}</b>\n"
                        f"📄 Ref: {app['ref']}\n"
                        f"📅 তারিখ: {app['apply_date']}\n"
                        f"✅ স্ট্যাটাস: {app['status']}"
                    )

            if changes:
                save_rss(changes)
                for c in changes:
                    send_telegram(
                        f"<b>স্ট্যাটাস:</b>\n\n"
                        f"<b>{c['name']}</b>\n"
                        f"📄 Ref: {c['ref']}\n"
                        f"📅 তারিখ: {c['date']}\n"
                        f"⬅️ আগে: {c['old']}\n"
                        f"✅ এখন: {c['new']}"
                    )
            elif not old_statuses:
                save_rss([])
                send_telegram(f"✅ প্রথম চেক সম্পন্ন!\n📊 মোট আবেদন: {len(applications)}টি")

            save_state({"statuses": new_statuses, "print_dates": new_print_dates, "status_history": new_history})
            save_userdata(new_print_dates, new_history)
            print(f"Done. {len(applications)} apps, {len(changes)} changes, {len(new_files)} new.")

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{str(e)[:200]}")
            print(f"Error: {e}")
        await browser.close()

asyncio.run(main())

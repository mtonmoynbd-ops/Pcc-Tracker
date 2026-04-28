import os, json, asyncio, requests, re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
STATE_FILE = "pcc_state.json"

def send_telegram(msg, target=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": target or CHAT_ID, "text": msg, "parse_mode": "HTML"})
    print(f"Telegram: {r.status_code}")

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

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
            print(f"After login URL: {current_url}")

            if "login" in current_url.lower():
                send_telegram("❌ লগইন ব্যর্থ। Username/Password চেক করুন।")
                await browser.close()
                return

            session_match = re.search(r'session=(\d+)', current_url)
            if session_match:
                session_id = session_match.group(1)
                account_url = f"https://pcc.police.gov.bd/ords/r/pcc/pcc/23?session={session_id}"
            else:
                account_url = "https://pcc.police.gov.bd/ords/r/pcc/pcc/23"

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
                    name = cols[5].text.strip()
                    full_status = cols[8].text.strip()
                    match = re.match(r'(\d+/\d+)', full_status)
                    status = match.group(1) if match else full_status
                    if ref and len(ref) > 2:
                        applications.append({
                            "ref": ref,
                            "name": name,
                            "apply_date": apply_date,
                            "status": status
                        })

            print(f"Applications found: {len(applications)}")

            if not applications:
                send_telegram(f"⚠️ আবেদন পাওয়া যায়নি।")
                await browser.close()
                return

            old_state = load_state()
            new_state = {}
            changes = []

            for app in applications:
                ref = app["ref"]
                status = app["status"]
                new_state[ref] = status

                if old_state.get(ref) and old_state.get(ref) != status:
                    changes.append(
                        f"<b>{app['name']}</b>\n"
                        f"📄 Ref: {ref}\n"
                        f"📅 তারিখ: {app['apply_date']}\n"
                        f"⬅️ আগে: {old_state[ref]}\n"
                        f"✅ এখন: {status}"
                    )

            if changes:
                for chunk in changes:
                    # ব্যক্তিগত message তোমাকে
                    send_telegram(f"<b>স্ট্যাটাস:</b>\n\n{chunk}", CHAT_ID)
                    # Channel-এও post হবে
                    send_telegram(f"<b>স্ট্যাটাস:</b>\n\n{chunk}", CHANNEL_ID)
            else:
                if not old_state:
                    msg = f"✅ প্রথম চেক সম্পন্ন!\n📊 মোট আবেদন: {len(applications)}টি\n\nস্ট্যাটাস বদলালে notification আসবে।"
                    send_telegram(msg, CHAT_ID)
                    send_telegram(msg, CHANNEL_ID)

            save_state(new_state)

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{str(e)[:200]}")
            print(f"Error: {e}")

        await browser.close()

asyncio.run(main())
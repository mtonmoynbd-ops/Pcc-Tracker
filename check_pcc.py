import os, json, asyncio, requests
from playwright.async_api import async_playwright

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})
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
    send_telegram("🔄 PCC চেক শুরু হয়েছে...")

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

            print(f"Login page loaded: {page.url}")

            # Fill mobile number
            mobile_input = await page.query_selector("input[type='text']")
            if mobile_input:
                await mobile_input.fill(USERNAME)
                print("Mobile filled")

            # Fill password
            pass_input = await page.query_selector("input[type='password']")
            if pass_input:
                await pass_input.fill(PASSWORD)
                print("Password filled")

            # Click sign in
            await page.click("button:has-text('Sign in')")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            print(f"After login: {page.url}")

            # Check if login successful
            if "login" in page.url.lower():
                send_telegram("❌ লগইন ব্যর্থ হয়েছে। Username/Password চেক করুন।")
                await browser.close()
                return

            # Navigate to My Account
            await page.goto("https://pcc.police.gov.bd/ords/r/pcc/pcc/23", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            print(f"Account page: {page.url}")

            if "login" in page.url.lower():
                send_telegram("❌ My Account পেজে যাওয়া যায়নি।")
                await browser.close()
                return

            # Get page content
            from bs4 import BeautifulSoup
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")

            applications = []
            rows = soup.select("table tr")
            print(f"Rows: {len(rows)}")

            for row in rows[1:]:
                cols = row.select("td")
                if len(cols) >= 3:
                    ref = cols[0].text.strip()
                    name = cols[1].text.strip()
                    status = cols[2].text.strip()
                    if ref:
                        applications.append({"ref": ref, "name": name, "status": status})

            print(f"Applications: {len(applications)}")

            if not applications:
                # Try finding application data differently
                all_text = soup.get_text()
                print(f"Page text preview: {all_text[:300]}")
                send_telegram(f"⚠️ আবেদন পাওয়া যায়নি। পেজ URL: {page.url}")
                await browser.close()
                return

            old_state = load_state()
            new_state = {}
            changes = []

            for app in applications:
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
                msg = "🇧🇩 <b>PCC স্ট্যাটাস পরিবর্তন!</b>\n\n" + "\n\n".join(changes)
                send_telegram(msg)
            else:
                send_telegram(f"✅ চেক সম্পন্ন। {len(applications)}টি আবেদন, কোনো পরিবর্তন নেই।")

            save_state(new_state)

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{e}")
            print(f"Error: {e}")

        await browser.close()

asyncio.run(main())

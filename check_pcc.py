import os, json, asyncio, requests, re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

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

            # Fill form
            await page.fill("input[type='text']", USERNAME)
            await page.fill("input[type='password']", PASSWORD)
            print("Form filled")

            # Click sign in and wait
            await page.click("button:has-text('Sign in')")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)

            current_url = page.url
            print(f"After login URL: {current_url}")

            if "login" in current_url.lower():
                send_telegram("❌ লগইন ব্যর্থ। Username/Password ভুল হতে পারে।")
                await browser.close()
                return

            # Extract session from current URL
            session_match = re.search(r'session=(\d+)', current_url)
            if session_match:
                session_id = session_match.group(1)
                print(f"Session ID: {session_id}")
                account_url = f"https://pcc.police.gov.bd/ords/r/pcc/pcc/23?session={session_id}"
            else:
                # Try clicking My Account link directly
                account_url = "https://pcc.police.gov.bd/ords/r/pcc/pcc/23"

            await page.goto(account_url, timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            print(f"Account page URL: {page.url}")

            if "login" in page.url.lower():
                # Try clicking the My Account link from the page
                await page.goto(current_url, timeout=30000)
                await page.wait_for_timeout(2000)
                my_account = await page.query_selector("a:has-text('My Account')")
                if my_account:
                    await my_account.click()
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(3000)
                    print(f"After clicking My Account: {page.url}")

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")

            applications = []
            rows = soup.select("table tr")
            print(f"Rows found: {len(rows)}")

            for row in rows[1:]:
                cols = row.select("td")
                if len(cols) >= 3:
                    ref = cols[0].text.strip()
                    name = cols[1].text.strip()
                    status = cols[2].text.strip()
                    if ref and len(ref) > 2:
                        applications.append({"ref": ref, "name": name, "status": status})

            print(f"Applications found: {len(applications)}")

            if not applications:
                preview = soup.get_text()[:200]
                print(f"Page preview: {preview}")
                send_telegram(f"⚠️ আবেদন পাওয়া যায়নি।\nURL: {page.url}")
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
                    changes.append(f"🆕 <b>{app['name']}</b>\n📄 Ref: {ref}\n✅ {status}")
                elif old_state[ref] != status:
                    changes.append(
                        f"🔔 <b>{app['name']}</b>\n📄 Ref: {ref}\n"
                        f"⬅️ আগে: {old_state[ref]}\n✅ এখন: {status}"
                    )

            if changes:
                for chunk in changes:
                    send_telegram(f"🇧🇩 <b>PCC পরিবর্তন!</b>\n\n{chunk}")
            else:
                # First run - just confirm
                send_telegram(f"✅ প্রথম চেক সম্পন্ন!\n📊 মোট আবেদন: {len(applications)}টি\n\nপরবর্তীতে স্ট্যাটাস বদলালে notification আসবে।")
            save_state(new_state)

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{str(e)[:200]}")
            print(f"Error: {e}")

        await browser.close()

asyncio.run(main())

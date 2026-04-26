import os, json, asyncio
from playwright.async_api import async_playwright

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"

import requests

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
        page = await browser.new_page()
        
        try:
            # Login page
            await page.goto("https://pcc.police.gov.bd/ords/r/pcc/pcc/login_desktop", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # Fill login form
            await page.fill("input[type='text'], input[placeholder*='Mobile'], input[name*='username'], input[name*='USERNAME']", USERNAME)
            await page.fill("input[type='password']", PASSWORD)
            
            # Click login button
            await page.click("button[type='submit'], input[type='submit'], button:has-text('Sign in')")
            await page.wait_for_timeout(3000)
            
            print(f"After login URL: {page.url}")
            
            # Go to My Account page
            await page.goto("https://pcc.police.gov.bd/ords/r/pcc/pcc/23", timeout=30000)
            await page.wait_for_timeout(2000)
            
            print(f"Account page URL: {page.url}")
            
            # Get all application rows
            content = await page.content()
            print(f"Page content length: {len(content)}")
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            
            applications = []
            rows = soup.select("table tr")
            print(f"Rows found: {len(rows)}")
            
            for row in rows[1:]:
                cols = row.select("td")
                if len(cols) >= 3:
                    applications.append({
                        "ref": cols[0].text.strip(),
                        "name": cols[1].text.strip(),
                        "status": cols[2].text.strip(),
                    })
            
            print(f"Applications found: {len(applications)}")
            
            if not applications:
                send_telegram("⚠️ আবেদন পাওয়া যায়নি। লগইন সমস্যা হতে পারে।")
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

import os, json, asyncio, requests, re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

USERNAME = os.environ["PCC_USERNAME"]
PASSWORD = os.environ["PCC_PASSWORD"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "pcc_state.json"
DATA_FILE = "docs/data.json"
RSS_FILE = "docs/rss.xml"
USERDATA_FILE = "docs/userdata.json"
CERT_DIR = "docs/certs"

BD_TZ = timezone(timedelta(hours=6))
PCC_BASE = "https://pcc.police.gov.bd"


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
            "updated": datetime.now(BD_TZ).strftime("%d-%b-%Y %I:%M %p"),
            "applications": applications
        }, f, ensure_ascii=False)


def save_rss(changes):
    os.makedirs("docs", exist_ok=True)
    now = datetime.now(BD_TZ).strftime("%a, %d %b %Y %H:%M:%S +0600")
    items = ""
    for c in changes:
        items += f"""<item>
<title>{c['name']} - {c['new']}</title>
<link>https://mtonmoynbd-ops.github.io/Pcc-Tracker/</link>
<description>Ref: {c['ref']} | {c['old']} → {c['new']}</description>
<pubDate>{now}</pubDate>
<guid isPermaLink="false">{c['ref']}-{c['new']}-{datetime.now(BD_TZ).strftime('%Y%m%d%H%M')}</guid>
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
    existing["script_updated"] = datetime.now(BD_TZ).strftime("%d-%b-%Y %I:%M %p")
    with open(USERDATA_FILE, "w") as f:
        json.dump(existing, f, ensure_ascii=False)


def parse_rows(rows):
    """Parse table rows into application dicts — also extracts cert link"""
    apps = []
    for row in rows:
        cols = row.select("td")
        if len(cols) >= 9:
            ref = cols[0].text.strip()

            # ── Certificate link (col index 1) ──────────────────────
            cert_tag = cols[1].select_one("a")
            raw_href = cert_tag["href"].strip() if cert_tag else None
            if raw_href:
                cert_url = (raw_href if raw_href.startswith("http") else PCC_BASE + raw_href).strip()
            else:
                cert_url = None

            apply_date = cols[3].text.strip()
            phone      = cols[4].text.strip()
            name       = cols[5].text.strip()
            full_status = cols[8].text.strip()
            m = re.match(r'(\d+/\d+)', full_status)
            status = m.group(1) if m else full_status

            if ref and len(ref) > 2:
                apps.append({
                    "ref":        ref,
                    "name":       name,
                    "apply_date": apply_date,
                    "phone":      phone,
                    "status":     status,
                    "cert_url":   cert_url,   # raw site URL (session-bound)
                    "cert_file":  None,        # will be filled after download
                })
    return apps


async def download_cert(page, app):
    """
    Navigate to the certificate URL using the active session,
    save as PDF → docs/certs/{ref}.pdf
    Returns the relative path on success, None on failure.
    """
    ref      = app["ref"]
    cert_url = app.get("cert_url")
    if not cert_url:
        return None

    os.makedirs(CERT_DIR, exist_ok=True)
    pdf_path    = f"{CERT_DIR}/{ref}.pdf"
    github_path = f"certs/{ref}.pdf"   # relative path served by GitHub Pages

    # Skip if already downloaded in a previous run
    if os.path.exists(pdf_path):
        print(f"Cert already exists: {ref}")
        return github_path

    try:
        await page.goto(cert_url, timeout=20000, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # If we got redirected to login, session expired — skip
        if "login" in page.url.lower():
            print(f"Session expired for cert {ref}")
            return None

        # Save the certificate page as PDF
        await page.pdf(
            path=pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"}
        )
        print(f"✅ Cert downloaded: {ref} → {pdf_path}")
        return github_path

    except Exception as e:
        print(f"⚠️ Cert download failed [{ref}]: {e}")
        return None


async def scrape_all_pages(page):
    """Scrape all pagination pages — handles multi-page PCC lists"""
    all_apps = []
    page_num = 0

    while page_num < 20:
        page_num += 1
        await page.wait_for_timeout(1500)

        content = await page.content()
        soup    = BeautifulSoup(content, "html.parser")
        rows    = soup.select("table tr")[1:]

        if not rows:
            print(f"Page {page_num}: no rows found, stopping")
            break

        page_apps = parse_rows(rows)
        all_apps.extend(page_apps)
        print(f"Page {page_num}: {len(page_apps)} applications")

        has_next = await page.evaluate("""() => {
            const candidates = [
                ...document.querySelectorAll(
                    'button[title="Next"], a[title="Next"], ' +
                    'button[aria-label="Next"], a[aria-label="Next"], ' +
                    '.t-Report-paginationLink--next, ' +
                    'a.t-Button--pagination, button.t-Button--pagination'
                )
            ];
            for (const el of candidates) {
                const txt   = el.textContent.trim();
                const title = (el.getAttribute('title') || '').toLowerCase();
                const aria  = (el.getAttribute('aria-label') || '').toLowerCase();
                if (
                    title.includes('next') || aria.includes('next') ||
                    txt === '>' || txt === 'Next' || txt === '›'
                ) {
                    if (!el.disabled && !el.classList.contains('disabled') && el.offsetParent !== null) {
                        el.click();
                        return true;
                    }
                }
            }
            const all = [...document.querySelectorAll('button, a, span[role="button"]')];
            for (const el of all) {
                if (el.textContent.trim() === '>' && !el.disabled && el.offsetParent !== null) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")

        if not has_next:
            print(f"No next page after page {page_num}")
            break

        await page.wait_for_load_state("networkidle")
        print(f"Navigated to page {page_num + 1}")

    return all_apps


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            # ── Login ────────────────────────────────────────────────
            await page.goto("https://pcc.police.gov.bd/ords/r/pcc/pcc/login_desktop", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            await page.fill("input[type='text']",     USERNAME)
            await page.fill("input[type='password']", PASSWORD)
            await page.click("button:has-text('Sign in')")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(4000)

            if "login" in page.url.lower():
                send_telegram("❌ লগইন ব্যর্থ।")
                await browser.close()
                return

            session_match = re.search(r'session=(\d+)', page.url)
            account_url = (
                f"https://pcc.police.gov.bd/ords/r/pcc/pcc/23?session={session_match.group(1)}"
                if session_match
                else "https://pcc.police.gov.bd/ords/r/pcc/pcc/23"
            )

            await page.goto(account_url, timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            if "login" in page.url.lower():
                send_telegram("❌ My Account পেজে যাওয়া যায়নি।")
                await browser.close()
                return

            # ── Scrape ───────────────────────────────────────────────
            applications = await scrape_all_pages(page)

            if not applications:
                send_telegram("⚠️ আবেদন পাওয়া যায়নি।")
                await browser.close()
                return

            print(f"Total applications found: {len(applications)}")

            # ── Download certificates for 9/10 apps ─────────────────
            for app in applications:
                status_num = int(app["status"].split('/')[0]) if '/' in app["status"] else 0
                if status_num == 9 and app.get("cert_url"):
                    app["cert_file"] = await download_cert(page, app)

            save_data(applications)

            # ── Change detection ─────────────────────────────────────
            old_state      = load_state()
            old_statuses   = old_state.get("statuses", {})
            old_print_dates= old_state.get("print_dates", {})
            old_history    = old_state.get("status_history", {})

            new_statuses   = {}
            new_print_dates= dict(old_print_dates)
            new_history    = dict(old_history)
            changes        = []
            new_files      = []
            today_str      = datetime.now(BD_TZ).strftime("%d-%b-%Y")

            for app in applications:
                ref    = app["ref"]
                status = app["status"]
                new_statuses[ref] = status

                num = int(status.split('/')[0]) if '/' in status else 0
                if num == 5 and ref not in new_print_dates:
                    new_print_dates[ref] = today_str
                    print(f"Print date recorded: {ref} → {today_str}")

                if ref not in new_history:
                    new_history[ref] = []
                hist = new_history[ref]
                if not hist or hist[-1]["status"] != status:
                    hist.append({"status": status, "date": today_str})
                new_history[ref] = hist

                if ref not in old_statuses:
                    new_files.append(app)
                elif old_statuses[ref] != status:
                    changes.append({
                        "ref": ref, "name": app["name"],
                        "old": old_statuses[ref], "new": status,
                        "date": app["apply_date"]
                    })

            # ── Telegram notifications ───────────────────────────────
            if new_files and old_statuses:
                for app in new_files:
                    send_telegram(
                        f"🆕 <b>নতুন আবেদন!</b>\n\n<b>{app['name']}</b>\n"
                        f"📄 Ref: {app['ref']}\n📅 তারিখ: {app['apply_date']}\n✅ স্ট্যাটাস: {app['status']}"
                    )

            if changes:
                save_rss(changes)
                for c in changes:
                    cert_note = ""
                    # If newly reached 9/10 and cert downloaded, add note
                    if c["new"].startswith("9/") and c["old"] != c["new"]:
                        matched = next((a for a in applications if a["ref"] == c["ref"]), None)
                        if matched and matched.get("cert_file"):
                            cert_note = "\n📥 সার্টিফিকেট ডাউনলোড হয়েছে — এপে দেখুন"
                    send_telegram(
                        f"<b>স্ট্যাটাস আপডেট:</b>\n\n<b>{c['name']}</b>\n"
                        f"📄 Ref: {c['ref']}\n📅 তারিখ: {c['date']}\n"
                        f"⬅️ আগে: {c['old']}\n✅ এখন: {c['new']}{cert_note}"
                    )
            elif not old_statuses:
                save_rss([])
                send_telegram(f"✅ প্রথম চেক সম্পন্ন!\n📊 মোট আবেদন: {len(applications)}টি")

            save_state({"statuses": new_statuses, "print_dates": new_print_dates, "status_history": new_history})
            save_userdata(new_print_dates, new_history)
            cert_count = sum(1 for a in applications if a.get("cert_file"))
            print(f"Done. {len(applications)} apps, {len(changes)} changes, {len(new_files)} new, {cert_count} certs.")

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{str(e)[:200]}")
            print(f"Error: {e}")
        await browser.close()


asyncio.run(main())

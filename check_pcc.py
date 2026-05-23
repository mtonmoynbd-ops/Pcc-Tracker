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
    """Parse table rows — extracts cert link and form link"""
    apps = []
    for row in rows:
        cols = row.select("td")
        if len(cols) >= 9:
            ref = cols[0].text.strip()

            # ── Form link (col 0 — ref is a link) ───────────────────
            ref_tag = cols[0].select_one("a")
            raw_form = ref_tag["href"].strip() if ref_tag else None
            if raw_form:
                form_url = (raw_form if raw_form.startswith("http") else PCC_BASE + "/" + raw_form.lstrip("/")).strip()
            else:
                form_url = None

            # ── Certificate link (col 1) ─────────────────────────────
            cert_tag = cols[1].select_one("a")
            raw_href = cert_tag["href"].strip() if cert_tag else None
            if raw_href:
                cert_url = (raw_href if raw_href.startswith("http") else PCC_BASE + raw_href).strip()
            else:
                cert_url = None

            apply_date  = cols[3].text.strip()
            phone       = cols[4].text.strip()
            name        = cols[5].text.strip()
            full_status = cols[8].text.strip()
            m = re.match(r'(\d+/\d+)', full_status)
            status = m.group(1) if m else full_status

            if ref and len(ref) > 2:
                apps.append({
                    "ref":          ref,
                    "name":         name,
                    "apply_date":   apply_date,
                    "phone":        phone,
                    "status":       status,
                    "cert_url":     cert_url,
                    "cert_file":    None,
                    "form_url":     form_url,
                    "form_file":    None,
                    "chalan_file":  None,
                    "passport_file":None,
                    "nid_file":     None,
                })
    return apps


def migrate_pdf_to_png():
    """Delete old PDFs and cert PNGs (no suffix) to force re-screenshot without footer"""
    if not os.path.exists(CERT_DIR):
        return
    for fname in os.listdir(CERT_DIR):
        # Delete PDFs always
        if fname.endswith(".pdf"):
            try:
                os.remove(os.path.join(CERT_DIR, fname))
                print(f"🗑️ Removed old PDF: {fname}")
            except Exception as e:
                print(f"Remove failed [{fname}]: {e}")
        # Delete cert PNGs (no underscore = cert, not form/chalan/passport)
        elif fname.endswith(".png") and "_" not in fname:
            try:
                os.remove(os.path.join(CERT_DIR, fname))
                print(f"🗑️ Removed old cert PNG: {fname}")
            except Exception as e:
                print(f"Remove failed [{fname}]: {e}")


def cleanup_certs(applications):
    """Remove cert/doc PNGs for apps that are 10/10 or no longer in list"""
    if not os.path.exists(CERT_DIR):
        return
    active_refs    = {a["ref"] for a in applications}
    delivered_refs = {a["ref"] for a in applications if a["status"] == "10/10"}
    for fname in os.listdir(CERT_DIR):
        if not fname.endswith(".png") and not fname.endswith(".pdf"):
            continue
        # ref = everything before first underscore or dot
        ref = fname.split("_")[0].split(".")[0]
        if ref in delivered_refs or ref not in active_refs:
            try:
                os.remove(os.path.join(CERT_DIR, fname))
                print(f"🗑️ Removed: {fname}")
            except Exception as e:
                print(f"Remove failed [{fname}]: {e}")


async def download_cert(page, app):
    """Screenshot #printID → docs/certs/{ref}.png"""
    ref      = app["ref"]
    cert_url = app.get("cert_url")
    if not cert_url:
        return None

    os.makedirs(CERT_DIR, exist_ok=True)
    png_path    = f"{CERT_DIR}/{ref}.png"
    github_path = f"certs/{ref}.png"

    if os.path.exists(png_path):
        print(f"Cert already exists: {ref}")
        return github_path

    old_pdf = f"{CERT_DIR}/{ref}.pdf"
    if os.path.exists(old_pdf):
        os.remove(old_pdf)

    try:
        await page.goto(cert_url, timeout=20000, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        if "login" in page.url.lower():
            return None
        await page.set_viewport_size({"width": 900, "height": 1200})
        await page.wait_for_timeout(500)

        cert_el = await page.query_selector("#printID")
        if cert_el:
            await cert_el.screenshot(path=png_path)
        else:
            await page.screenshot(path=png_path, full_page=True)
        print(f"✅ Cert screenshot: {ref} → {png_path}")
        return github_path
    except Exception as e:
        print(f"⚠️ Cert failed [{ref}]: {e}")
        return None


async def scrape_form_docs(page, app):
    """Visit application form page → screenshot form + all attachments"""
    ref      = app["ref"]
    form_url = app.get("form_url")
    if not form_url:
        return {}

    os.makedirs(CERT_DIR, exist_ok=True)
    results = {}

    try:
        await page.goto(form_url, timeout=20000, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        if "login" in page.url.lower():
            return {}

        await page.set_viewport_size({"width": 900, "height": 1400})
        await page.wait_for_timeout(500)

        # ── Screenshot form page ──────────────────────────────────
        form_path = f"{CERT_DIR}/{ref}_form.png"
        if not os.path.exists(form_path):
            await page.evaluate("""() => {
                ['nav','header','footer','.t-Header','.t-Footer',
                 '.t-NavigationBar','.t-Body-nav','#t_Header','#t_Footer']
                .forEach(s => document.querySelectorAll(s)
                .forEach(el => el.style.display='none'));
            }""")
            await page.wait_for_timeout(200)
            await page.screenshot(path=form_path, full_page=True)
            print(f"✅ Form: {ref}")
        results["form_file"] = f"certs/{ref}_form.png"

        # ── Parse all doc-card attachments ────────────────────────
        content = await page.content()
        soup    = BeautifulSoup(content, "html.parser")

        for card in soup.select("div.doc-card"):
            label = card.select_one("p")
            link  = card.select_one("a[href]")
            if not label or not link:
                continue
            label_text = label.text.strip()
            href = link["href"].strip()
            if not href or href == "#":
                continue

            # Generate safe file key and filename from label
            label_lower = label_text.lower()
            if "chalan" in label_lower or "challan" in label_lower:
                key = "chalan_file"; slug = "chalan"
            elif "passport" in label_lower:
                key = "passport_file"; slug = "passport"
            elif "national" in label_lower or "nid" in label_lower:
                key = "nid_file"; slug = "nid"
            else:
                # Generic: sanitize label to slug
                slug = re.sub(r'[^a-z0-9]', '_', label_lower).strip('_')[:20]
                key  = slug + "_file"

            png_path = f"{CERT_DIR}/{ref}_{slug}.png"
            if os.path.exists(png_path):
                results[key] = f"certs/{ref}_{slug}.png"
                continue

            try:
                await page.goto(href, timeout=15000, wait_until="networkidle")
                await page.wait_for_timeout(1000)
                await page.set_viewport_size({"width": 900, "height": 1200})
                await page.screenshot(path=png_path, full_page=True)
                print(f"✅ {label_text}: {ref}")
                results[key] = f"certs/{ref}_{slug}.png"
            except Exception as e:
                print(f"⚠️ {label_text} failed [{ref}]: {e}")

        return results

    except Exception as e:
        print(f"⚠️ Form docs failed [{ref}]: {e}")
        return {}


async def scrape_all_pages(page):
    """Scrape all pagination pages"""
    all_apps = []
    page_num = 0
    while page_num < 3:  # Only first 3 pages (~45 most recent files)
        page_num += 1
        await page.wait_for_timeout(1500)
        content = await page.content()
        soup    = BeautifulSoup(content, "html.parser")
        rows    = soup.select("table tr")[1:]
        if not rows:
            print(f"Page {page_num}: no rows found, stopping")
            break
        page_apps = parse_rows(rows)
        # Filter out already-delivered files from processing (still count them)
        all_apps.extend(page_apps)
        print(f"Page {page_num}: {len(page_apps)} applications")
        has_next = await page.evaluate("""() => {
            const candidates = [...document.querySelectorAll(
                'button[title="Next"], a[title="Next"], button[aria-label="Next"], a[aria-label="Next"], .t-Report-paginationLink--next, a.t-Button--pagination, button.t-Button--pagination'
            )];
            for (const el of candidates) {
                const txt = el.textContent.trim();
                const title = (el.getAttribute('title')||'').toLowerCase();
                const aria  = (el.getAttribute('aria-label')||'').toLowerCase();
                if (title.includes('next')||aria.includes('next')||txt==='>'||txt==='Next'||txt==='›') {
                    if (!el.disabled && !el.classList.contains('disabled') && el.offsetParent!==null) {
                        el.click(); return true;
                    }
                }
            }
            const all = [...document.querySelectorAll('button, a, span[role="button"]')];
            for (const el of all) {
                if (el.textContent.trim()==='>' && !el.disabled && el.offsetParent!==null) {
                    el.click(); return true;
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
    migrate_pdf_to_png()
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

            # ── Download form docs for ALL active apps ───────────────
            for app in applications:
                if not app.get("form_url"):
                    continue
                ref = app["ref"]
                form_exists = os.path.exists(f"{CERT_DIR}/{ref}_form.png")
                nid_exists  = os.path.exists(f"{CERT_DIR}/{ref}_nid.png")
                if form_exists:
                    # Fill in all existing files from disk
                    for fname in os.listdir(CERT_DIR):
                        if fname.startswith(ref+"_") and fname.endswith(".png"):
                            slug = fname[len(ref)+1:-4]
                            app[slug+"_file"] = f"certs/{fname}"
                    # If NID missing, re-scrape to get remaining attachments
                    if not nid_exists:
                        docs = await scrape_form_docs(page, app)
                        app.update(docs)
                    continue
                docs = await scrape_form_docs(page, app)
                app.update(docs)

            # ── Cleanup ──────────────────────────────────────────────
            cleanup_certs(applications)
            save_data(applications)

            # ── Change detection ─────────────────────────────────────
            old_state       = load_state()
            old_statuses    = old_state.get("statuses", {})
            old_print_dates = old_state.get("print_dates", {})
            old_history     = old_state.get("status_history", {})

            new_statuses    = {}
            new_print_dates = dict(old_print_dates)
            new_history     = dict(old_history)
            changes         = []
            new_files       = []
            today_str       = datetime.now(BD_TZ).strftime("%d-%b-%Y")

            for app in applications:
                ref    = app["ref"]
                status = app["status"]
                new_statuses[ref] = status

                num = int(status.split('/')[0]) if '/' in status else 0
                if num == 5 and ref not in new_print_dates:
                    new_print_dates[ref] = today_str

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
            doc_count  = sum(1 for a in applications if a.get("form_file"))
            print(f"Done. {len(applications)} apps, {len(changes)} changes, {len(new_files)} new, {cert_count} certs, {doc_count} forms.")

        except Exception as e:
            send_telegram(f"⚠️ সমস্যা:\n{str(e)[:200]}")
            print(f"Error: {e}")
        await browser.close()


async def run_with_retry(max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            await main()
            return
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt < max_attempts:
                print(f"Retrying in 30 seconds...")
                await asyncio.sleep(30)
            else:
                print("All attempts failed.")
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                        json={"chat_id": CHAT_ID, "text": f"⚠️ সব retry ব্যর্থ:\n{str(e)[:200]}", "parse_mode": "HTML"}
                    )
                except:
                    pass

asyncio.run(run_with_retry())

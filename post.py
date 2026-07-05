# -*- coding: utf-8 -*-
"""
Eigenstaendiger Instagram-Karussell-Poster fuer GitHub Actions (kein PC noetig).
EINZIGER Post-Weg fuer @kiai1977 (der lokale Weg ist dauerhaft deaktiviert).

Idempotent gegen den 403-trotz-Live-Quirk der Graph API:
  - Persistentes Ledger (published_ledger.json) aller je veroeffentlichten
    Caption-Signaturen -> ein Inhalt wird NIE zweimal gepostet.
  - Vor dem Posten: Ledger UND Live-Account pruefen.
  - Nach (gemeldetem) Fehler: mehrfach pruefen, ob der Post TROTZDEM live ging.
  - Max. 1 Post / 12h.

Benoetigt IG_ACCESS_TOKEN und IG_USER_ID (Actions-Secrets).
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://graph.instagram.com/v21.0"
REPO_RAW = "https://raw.githubusercontent.com/lionelhutz77-tech/ig-media/main"
ROOT = Path(__file__).parent
LEDGER = ROOT / "published_ledger.json"


# --- Caption-Signatur + Ledger -------------------------------------------

def caption_core(text: str) -> str:
    """Stabile, normalisierte Caption-Signatur (erste 90 Zeichen)."""
    return re.sub(r"[^a-zäöüß0-9 ]", "", (text or "").lower()).strip()[:90]


def load_ledger() -> set:
    try:
        return set(json.load(open(LEDGER, encoding="utf-8")).get("cores", []))
    except Exception:
        return set()


def ledger_add(core: str) -> None:
    if not core:
        return
    cores = load_ledger()
    cores.add(core)
    json.dump({"cores": sorted(cores)}, open(LEDGER, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)


def ledger_has(core: str) -> bool:
    return bool(core) and core in load_ledger()


def telegram(msg: str) -> None:
    """Sendet eine Telegram-Notiz (still, wenn Secrets fehlen)."""
    tok = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": msg}, timeout=15)
    except Exception as e:
        print(f"  WARN Telegram: {e}")


def rest_vorrat(account_cores) -> list:
    """Freigegebene, noch nicht veroeffentlichte Karussells (echter Restvorrat)."""
    rest = []
    for d in sorted((ROOT / "queue").glob("item_*")):
        if not (d / "APPROVED").exists():
            continue
        cap = d / "caption.txt"
        if not cap.exists() or not sorted(d.glob("slide_*.jpg")):
            continue
        core = caption_core(cap.read_text(encoding="utf-8").strip())
        if (d / "PUBLISHED.txt").exists() or ledger_has(core) or ist_live(core, account_cores):
            continue
        rest.append(d.name)
    return rest


def warn_if_low(account_cores) -> None:
    """Telegram-Frühwarnung, wenn der Restvorrat knapp wird (<=2)."""
    rest = rest_vorrat(account_cores)
    n = len(rest)
    if n == 0:
        telegram("⚠️ kiai-Vorrat LEER: keine freigegebenen Karussells mehr — bald kein Post mehr! Bitte Nachschub bauen.")
    elif n <= 2:
        telegram(f"⚠️ kiai-Vorrat niedrig: nur noch {n} Karussell(s) in der Queue. Bitte Nachschub bauen.")


# --- Account-Abgleich (Quelle der Wahrheit) ------------------------------

def account_caption_cores(uid: str, token: str, limit: int = 50):
    """(cores, neueste_ts) der letzten Account-Posts; (None, None) bei API-Fehler."""
    try:
        r = requests.get(f"{API}/{uid}/media", params={
            "fields": "caption,timestamp", "limit": limit,
            "access_token": token}, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
        cores = [caption_core(m.get("caption", "")) for m in data if m.get("caption")]
        neueste = data[0].get("timestamp") if data else None
        return cores, neueste
    except Exception as e:
        print(f"  WARN Account-Abgleich nicht moeglich: {e}")
        return None, None


def ist_live(core: str, cores) -> bool:
    if not core or not cores:
        return False
    return any(core == a or core in a or a in core for a in cores)


def stunden_seit(ts_iso: str):
    if not ts_iso:
        return None
    try:
        dt = datetime.strptime(ts_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


# --- Auswahl + Publish ----------------------------------------------------

def next_item(account_cores):
    """Aeltestes freigegebenes, noch NICHT veroeffentlichtes Karussell.
    Bereits gepostete (Ledger ODER Live-Account ODER PUBLISHED.txt) werden
    uebersprungen und dabei sauber markiert."""
    qdir = ROOT / "queue"
    if not qdir.exists():
        return None, None, None
    for d in sorted(qdir.glob("item_*")):
        if not (d / "APPROVED").exists():
            continue
        cap_file = d / "caption.txt"
        slides = sorted(d.glob("slide_*.jpg"))
        if not slides or not cap_file.exists():
            continue
        core = caption_core(cap_file.read_text(encoding="utf-8").strip())
        if (d / "PUBLISHED.txt").exists() or ledger_has(core) or ist_live(core, account_cores):
            # schon gepostet -> sicherstellen, dass es markiert + im Ledger ist
            if not (d / "PUBLISHED.txt").exists():
                (d / "PUBLISHED.txt").write_text(
                    f"{time.strftime('%Y-%m-%d %H:%M')} bereits veroeffentlicht (Reconcile)\n",
                    encoding="utf-8")
            ledger_add(core)
            continue
        return d, slides, core
    return None, None, None


def publish(uid, token, urls, caption):
    children = []
    for i, u in enumerate(urls, 1):
        r = requests.post(f"{API}/{uid}/media", data={
            "image_url": u, "is_carousel_item": "true",
            "access_token": token}, timeout=60)
        r.raise_for_status()
        children.append(r.json()["id"])
        print(f"  Slide {i}/{len(urls)} -> {children[-1]}")

    r = requests.post(f"{API}/{uid}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children),
        "caption": caption, "access_token": token}, timeout=60)
    r.raise_for_status()
    cid = r.json()["id"]
    print(f"  Karussell-Container: {cid}")

    for _ in range(24):
        time.sleep(5)
        s = requests.get(f"{API}/{cid}", params={
            "fields": "status_code", "access_token": token}, timeout=30)
        status = s.json().get("status_code")
        print(f"  Status: {status}")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise SystemExit("Container-Verarbeitung fehlgeschlagen (ERROR).")

    p = requests.post(f"{API}/{uid}/media_publish", data={
        "creation_id": cid, "access_token": token}, timeout=60)
    p.raise_for_status()
    return p.json()["id"]


def main():
    token = os.environ.get("IG_ACCESS_TOKEN")
    uid = os.environ.get("IG_USER_ID")
    if not token or not uid:
        raise SystemExit("FEHLER: IG_ACCESS_TOKEN / IG_USER_ID fehlen (Secrets).")

    account_cores, neueste_ts = account_caption_cores(uid, token)

    # GUARD: max. 1 Post / 12h (gegen Cron-Drift / Doppellaeufe)
    std = stunden_seit(neueste_ts)
    if account_cores is not None and std is not None and std < 12:
        print(f"Vor {std:.1f}h wurde bereits gepostet — uebersprungen (max 1/Tag).")
        warn_if_low(account_cores)
        return

    d, slides, core = next_item(account_cores)
    if not d:
        print("Kein freigegebenes, ungepostetes Karussell in der Warteschlange.")
        warn_if_low(account_cores)
        return

    rel = d.relative_to(ROOT).as_posix()
    urls = [f"{REPO_RAW}/{rel}/{s.name}" for s in slides]
    if len(urls) > 10:
        print(f"  WARN: {len(urls)} Slides > 10 -> kuerze auf die ersten 10.")
        urls = urls[:10]
    caption = (d / "caption.txt").read_text(encoding="utf-8").strip()
    print(f"Veroeffentliche {d.name} mit {len(urls)} Slides...")

    post_id = None
    fehler = None
    try:
        post_id = publish(uid, token, urls, caption)
        print(f"VEROEFFENTLICHT! Post-ID: {post_id}")
    except Exception as e:
        fehler = e
        print(f"  WARN publish meldete Fehler: {e}")
        # GUARD: ging der Post TROTZDEM live? (403-trotz-Live-Quirk, evtl. verzoegert)
        for wartezeit in (15, 30, 60):
            time.sleep(wartezeit)
            caps2, _ = account_caption_cores(uid, token)
            if ist_live(core, caps2):
                print(f"  {d.name} ging trotz Fehler live — als veroeffentlicht markiert.")
                post_id = "recovered"
                break

    if post_id:
        (d / "PUBLISHED.txt").write_text(
            f"{time.strftime('%Y-%m-%d %H:%M')} post_id={post_id}\n", encoding="utf-8")
        ledger_add(core)
        warn_if_low(account_cores)
    else:
        raise SystemExit(f"FEHLER: {d.name} wurde NICHT veroeffentlicht ({fehler}). Nicht markiert.")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Eigenstaendiger Instagram-Karussell-Poster fuer GitHub Actions (kein PC noetig).

Sucht in queue/ das aelteste freigegebene (APPROVED), noch nicht gepostete
Karussell, laedt die bereits im Repo liegenden Slides als oeffentliche raw-URLs
und veroeffentlicht sie ueber die Instagram Graph API. Danach wird PUBLISHED.txt
geschrieben (der Workflow committet das zurueck, damit nichts doppelt postet).

Benoetigt die Umgebungsvariablen IG_ACCESS_TOKEN und IG_USER_ID (Actions-Secrets).
"""
import os
import sys
import time
from pathlib import Path

import requests

API = "https://graph.instagram.com/v21.0"
REPO_RAW = "https://raw.githubusercontent.com/lionelhutz77-tech/ig-media/main"
ROOT = Path(__file__).parent


def next_item():
    qdir = ROOT / "queue"
    if not qdir.exists():
        return None, None
    for d in sorted(qdir.glob("item_*")):
        if (d / "APPROVED").exists() and not (d / "PUBLISHED.txt").exists():
            slides = sorted(d.glob("slide_*.jpg"))
            if slides and (d / "caption.txt").exists():
                return d, slides
    return None, None


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

    d, slides = next_item()
    if not d:
        print("Kein freigegebenes, ungepostetes Karussell in der Warteschlange.")
        return

    rel = d.relative_to(ROOT).as_posix()
    urls = [f"{REPO_RAW}/{rel}/{s.name}" for s in slides]
    caption = (d / "caption.txt").read_text(encoding="utf-8").strip()
    print(f"Veroeffentliche {d.name} mit {len(urls)} Slides...")
    post_id = publish(uid, token, urls, caption)
    print(f"VEROEFFENTLICHT! Post-ID: {post_id}")
    (d / "PUBLISHED.txt").write_text(
        f"{time.strftime('%Y-%m-%d %H:%M')} post_id={post_id}\n", encoding="utf-8")


if __name__ == "__main__":
    main()

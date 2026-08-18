#!/usr/bin/env python3
"""
把 Google Takeout 的「已儲存」清單（CSV）＋「已加上標籤的地點」(住家/工作…) 轉成座標，
再用密碼加密成 places.enc 放進 App。

用法：
  python3 tools/build_places.py <takeout.zip 或已解壓的 Takeout 資料夾> --password '你的密碼'

需要：tools/.secrets 內有 PLACES_KEY=（Places API (New) 專用金鑰）
輸出：places.enc（加密，可公開）、tools/places_raw.json（明碼，勿上傳，已 gitignore）
"""
import sys, os, re, csv, json, base64, struct, zipfile, argparse, hashlib, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
CACHE = TOOLS / 'places_cache.json'   # place_id -> {lat,lng,addr}，避免重複查（免費額度）

def load_key():
    for line in (TOOLS / '.secrets').read_text().splitlines():
        if line.startswith('PLACES_KEY='):
            return line.split('=', 1)[1].strip()
    sys.exit('tools/.secrets 缺 PLACES_KEY')

def ftid_to_place_id(ftid):
    a, b = ftid.split(':')
    raw = b'\x0a\x12\x09' + struct.pack('<Q', int(a, 16)) + b'\x11' + struct.pack('<Q', int(b, 16))
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')

def parse_url(url):
    """回 (place_id, lat, lng, name)；能拿到什麼給什麼"""
    pid = lat = lng = None
    m = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url)
    if m: pid = ftid_to_place_id(m.group(1))
    m = re.search(r'!3d(-?[0-9.]+)!4d(-?[0-9.]+)', url)
    if m: lat, lng = float(m.group(1)), float(m.group(2))
    m = re.search(r'/@(-?[0-9.]+),(-?[0-9.]+)', url)
    if m and lat is None: lat, lng = float(m.group(1)), float(m.group(2))
    m = re.search(r'/place/([^/]+)/', url)
    name = urllib.parse.unquote_plus(m.group(1)) if m else None
    return pid, lat, lng, name

def place_details(pid, key):
    req = urllib.request.Request(
        f'https://places.googleapis.com/v1/places/{pid}?languageCode=zh-TW',
        headers={'X-Goog-Api-Key': key, 'X-Goog-FieldMask': 'id,location,formattedAddress'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    return {'lat': d['location']['latitude'], 'lng': d['location']['longitude'], 'addr': d.get('formattedAddress', '')}

def read_takeout(src):
    src = Path(src)
    if src.suffix == '.zip':
        out = TOOLS / 'takeout'
        out.mkdir(exist_ok=True)
        zipfile.ZipFile(src).extractall(out)
        src = out
    base = src / 'Takeout' if (src / 'Takeout').exists() else src
    saved = base / '已儲存'
    lists = []
    for f in sorted(saved.glob('*.csv')):
        rows = []
        with open(f, encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                title = (r.get('標題') or r.get('Title') or '').strip()
                url = (r.get('網址') or r.get('URL') or '').strip()
                note = (r.get('筆記') or r.get('Note') or '').strip()
                if not url: continue
                rows.append({'title': title, 'url': url, 'note': note})
        if rows: lists.append({'name': f.stem, 'items': rows})
    labeled = base / '地圖' / '已加上標籤的地點' / '已加上標籤的地點.json'
    lab = []
    if labeled.exists():
        for ft in json.load(open(labeled, encoding='utf-8'))['features']:
            lng, lat = ft['geometry']['coordinates']
            lab.append({'title': ft['properties'].get('name', ''), 'lat': lat, 'lng': lng,
                        'addr': ft['properties'].get('address', ''), 'url': f'https://www.google.com/maps/search/?api=1&query={lat},{lng}'})
    if lab: lists.insert(0, {'name': '標籤地點', 'items': lab})
    return lists

def encrypt(plaintext: bytes, password: str) -> dict:
    """AES-256-GCM，PBKDF2-SHA256 200k 次；跟網頁 WebCrypto 對得起來"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16); iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 200_000, 32)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': 200000, 'salt': b64(salt), 'iv': b64(iv), 'data': b64(ct)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('--password', required=True)
    a = ap.parse_args()
    key = load_key()
    cache = json.load(open(CACHE)) if CACHE.exists() else {}
    lists = read_takeout(a.src)
    n_api = n_ok = n_fail = 0
    for L in lists:
        for it in L['items']:
            if it.get('lat'): n_ok += 1; continue
            pid, lat, lng, name = parse_url(it['url'])
            if not it['title'] and name: it['title'] = name
            if lat is not None:
                it['lat'], it['lng'] = lat, lng; n_ok += 1; continue
            if not pid:
                it['fail'] = 'no id'; n_fail += 1; continue
            if pid not in cache:
                try:
                    cache[pid] = place_details(pid, key); n_api += 1
                except Exception as e:
                    it['fail'] = str(e)[:80]; n_fail += 1; continue
                json.dump(cache, open(CACHE, 'w'), ensure_ascii=False)
            it.update(cache[pid]); n_ok += 1
    # 清掉沒座標的
    for L in lists:
        bad = [i for i in L['items'] if not i.get('lat')]
        for i in bad: print('  ✗ 沒座標：', L['name'], '|', i['title'], '|', i.get('fail'))
        L['items'] = [i for i in L['items'] if i.get('lat')]
    lists = [L for L in lists if L['items']]
    raw = {'lists': lists}
    json.dump(raw, open(TOOLS / 'places_raw.json', 'w'), ensure_ascii=False, indent=1)
    enc = encrypt(json.dumps(raw, ensure_ascii=False).encode(), a.password)
    json.dump(enc, open(ROOT / 'places.enc', 'w'))
    print(f'清單 {len(lists)} 個、地點 {sum(len(L["items"]) for L in lists)} 個；API 查了 {n_api} 次；失敗 {n_fail}')
    for L in lists: print(f'  {L["name"]}: {len(L["items"])}')
    print('→ places.enc 已產生（加密），tools/places_raw.json 明碼（勿上傳）')

if __name__ == '__main__':
    main()

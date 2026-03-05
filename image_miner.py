import sys
import json
import os
import re
import fitz  # PyMuPDF
import pandas as pd
import cloudscraper

# --- CONFIGURATION ---
LOGIN_URL = "https://devbackend.succeedquiz.com/api/v1/auth/login"
UPLOAD_URL = "https://devbackend.succeedquiz.com/api/v1/upload"

scraper = cloudscraper.create_scraper()

# ----------------- AUTH & UPLOAD -----------------

def login_and_get_token():
    email = "odavies@readwriteds.com"
    password = "2862008June28?"
    
    if not email or not password: 
        print("Missing hardcoded email or password.")
        return None

    try:
        response = scraper.post(LOGIN_URL, json={"email": email, "password": password})
        if response.status_code in [200, 201]:
            print("✅ Login Successful!")
            return response.json().get('data', {}).get('accessToken')
            
        print(f"❌ Login Failed: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"❌ Login Exception occurred: {e}")
        return None

def upload_image_api(image_bytes, filename, token):
    headers = {'Authorization': f'Bearer {token}'}
    if "." not in filename: filename += ".jpg"
    files = [('file', (filename, image_bytes, 'image/jpeg'))]

    try:
        response = scraper.post(UPLOAD_URL, headers=headers, files=files)
        if response.status_code in [200, 201]:
            data = response.json()
            if 'data' in data and 'files' in data['data']: return data['data']['files'][0].get('url')
            if 'url' in data: return data['url']
            if 'secure_url' in data: return data['secure_url']
        return None
    except: return None

# ----------------- THE GEOMETRIC ANCHOR ENGINE -----------------

def crop_image_via_text_anchoring(doc, q_text):
    """
    PRIMARY V1 Logic: Searches the PDF for the question text.
    Once found, it calculates the Y-coordinate of the text and crops 
    a rectangular area immediately below it, bypassing all header/logo traps.
    """
    if not q_text or len(q_text) < 15: return None
    
    # Clean text to prevent regex/tagging conflicts
    clean = re.sub(r"<<.*?>>", "", q_text).strip()
    
    # Try a highly specific search first, then fall back to a shorter snippet
    search_targets = [clean[:80], clean[:40]]

    for target in search_targets:
        target = target.strip()
        if len(target) < 10: continue
            
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            # Search the page for the target text
            rects = page.search_for(target)
            
            if rects:
                # Find the bottom-most Y coordinate of the matched text
                bottom_y = max([r.y1 for r in rects])
                w, h = page.rect.width, page.rect.height
                
                # Crop a box from just below the text down to 350 pixels (or page bottom)
                # 350px is typically the perfect height to capture a standard exam diagram
                y0 = min(bottom_y + 10, h) 
                y1 = min(y0 + 350, h)
                
                clip_rect = fitz.Rect(0, y0, w, y1)
                try:
                    # High DPI ensures text inside the diagram remains readable
                    return page.get_pixmap(clip=clip_rect, dpi=200).tobytes("jpg")
                except:
                    return None
    return None

# ----------------- MAIN -----------------

def main():
    # Accepts 3 or 4 arguments seamlessly to prevent GitHub Actions from crashing
    if len(sys.argv) < 4: 
        print("❌ Missing arguments. Expects: excel, pdf, output")
        return 

    input_excel = sys.argv[1]
    pdf_path = sys.argv[2]
    output_json = sys.argv[4] if len(sys.argv) == 5 else sys.argv[3]

    token = login_and_get_token()
    if not token: 
        print("❌ Exiting: Could not obtain auth token.")
        return

    try:
        df = pd.read_excel(input_excel)
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"\n🚨 CRITICAL ERROR LOADING FILES 🚨\n{e}\n")
        with open(output_json, 'w', encoding='utf-8') as f: json.dump({}, f)
        return

    result_map = {} 
    stats = {"anchor_success": 0, "failures": 0}

    print(f"\n--- Starting V1 Geometric Image Miner ---")

    for idx, row in df.iterrows():
        q_text_raw = str(row.get('Question', ''))
        q_text_clean = re.sub(r"<<IMAGE_REF_\d+>>", "", q_text_raw).strip()
        
        has_image_raw = str(row.get('has_image', '')).lower()
        is_has_image_true = has_image_raw in ['true', '1', 'yes']
        
        if is_has_image_true:
            print(f"🔍 Q{idx+1}: Searching PDF for anchor text...")
            img_bytes = crop_image_via_text_anchoring(doc, q_text_clean)
                
            if img_bytes:
                url = upload_image_api(img_bytes, f"q{idx+1}_anchor.jpg", token)
                if url:
                    print(f"✅ Q{idx+1}: Anchor Crop Uploaded -> {url}")
                    stats["anchor_success"] += 1
                    result_map[q_text_raw] = url
                else:
                    print(f"❌ Q{idx+1}: Crop successful, but Upload Failed.")
                    stats["failures"] += 1
            else:
                print(f"❌ Q{idx+1}: Failed to locate question text in PDF.")
                stats["failures"] += 1

    # Save Final Map
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result_map, f, indent=4)

    print("\n" + "="*40)
    print("📊 V1 GEOMETRIC MINER SUMMARY")
    print("="*40)
    print(f"Total 'has_image' Flags: {stats['anchor_success'] + stats['failures']}")
    print(f"✅ Successful Anchors  : {stats['anchor_success']}")
    print(f"❌ Search/Crop Failures: {stats['failures']}")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()

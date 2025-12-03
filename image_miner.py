import sys
import json
import os
import fitz  # PyMuPDF
import pandas as pd
import cloudscraper 
from fuzzywuzzy import fuzz

# --- CONFIGURATION ---
LOGIN_URL = "https://backend.succeedquiz.com/api/v1/auth/email/login"
UPLOAD_URL = "https://backend.succeedquiz.com/api/v1/upload"

scraper = cloudscraper.create_scraper()

def login_and_get_token():
    print("Attempting to log in...")
    email = os.environ.get("SUCCEED_EMAIL")
    password = os.environ.get("SUCCEED_PASSWORD")
    
    if not email or not password:
        print("Error: Missing Email/Password secrets.")
        return None

    try:
        response = scraper.post(LOGIN_URL, json={"email": email, "password": password})
        if response.status_code in [200, 201]:
            data = response.json()
            if 'data' in data and 'accessToken' in data['data']:
                print("Login Successful! Token acquired.")
                return data['data']['accessToken']
    except Exception as e:
        print(f"Login Error: {e}")
    
    print(f"Login Failed. Status: {response.status_code}, Response: {response.text}")
    return None

def upload_image_api(image_bytes, filename, token):
    headers = {'Authorization': f'Bearer {token}'}
    # Force filename to have an extension if missing
    if "." not in filename: filename += ".png"
        
    files = [('file', (filename, image_bytes, 'image/png'))]

    try:
        response = scraper.post(UPLOAD_URL, headers=headers, files=files)
        
        # --- DEBUG SECTION STARTED ---
        # print(f"DEBUG: Upload Status {response.status_code}")
        # print(f"DEBUG: Response Body: {response.text[:300]}") # Print first 300 chars
        # --- DEBUG SECTION END ---

        if response.status_code in [200, 201]:
            data = response.json()
            
            # 1. Try "url"
            if 'url' in data: return data['url']
            
            # 2. Try "data.url" or "data.link"
            if 'data' in data and isinstance(data['data'], dict):
                if 'url' in data['data']: return data['data']['url']
                if 'link' in data['data']: return data['data']['link']
                # NEW: Try "data" if it's a direct string
                if isinstance(data['data'], str) and data['data'].startswith('http'):
                    return data['data']

            # 3. Try "secure_url" (Cloudinary style)
            if 'secure_url' in data: return data['secure_url']
            
            # If we get here, we connected but couldn't find the key
            print(f"  -> ERROR: Key not found! JSON structure: {data}")
            return None
        else:
            print(f"  -> API Error ({response.status_code}): {response.text}")
            return None
            
    except Exception as e:
        print(f"  -> Exception during upload: {e}")
        return None

def find_image_below_text(doc, text_query):
    best_match_page = -1
    best_rect = None
    highest_ratio = 0
    query_short = str(text_query)[:100]
    
    for page_num, page in enumerate(doc):
        text_blocks = page.get_text("blocks")
        for block in text_blocks:
            ratio = fuzz.partial_ratio(query_short, block[4])
            if ratio > 85 and ratio > highest_ratio:
                highest_ratio = ratio
                best_match_page = page_num
                best_rect = fitz.Rect(block[:4])

    if best_match_page == -1: return None

    page = doc[best_match_page]
    images = page.get_images(full=True)
    text_bottom = best_rect.y1
    candidate_xref, min_dist = None, 1000
    
    for img in images:
        xref = img[0]
        rects = page.get_image_rects(xref)
        if not rects: continue
        if rects[0].y0 >= text_bottom:
            dist = rects[0].y0 - text_bottom
            if dist < min_dist:
                min_dist = dist
                candidate_xref = xref

    if candidate_xref:
        base = doc.extract_image(candidate_xref)
        return {"bytes": base["image"], "ext": base["ext"]}
    return None

def main():
    input_excel = sys.argv[1]
    pdf_path = sys.argv[2]
    output_json = sys.argv[3]

    api_token = login_and_get_token()
    if not api_token: return

    try:
        df = pd.read_excel(input_excel)
        questions = df.to_dict(orient='records')
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"File Error: {e}")
        return

    lookup_map = {}
    print("Starting Image Mining...")

    for i, q in enumerate(questions):
        has_img = str(q.get('has_image', False)).lower() in ['true', '1']
        if has_img:
            q_text = str(q.get('Question', ''))
            print(f"Searching Q{i}...")
            img_data = find_image_below_text(doc, q_text)
            
            if img_data:
                filename = f"q_{i}.{img_data['ext']}"
                url = upload_image_api(img_data['bytes'], filename, api_token)
                if url:
                    print(f"  -> Uploaded: {url}")
                    lookup_map[q_text] = url
            else:
                print("  -> No image found visually below text")

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(lookup_map, f, indent=4)
    print(f"Mining Complete. Saved {len(lookup_map)} images.")

if __name__ == "__main__":
    main()

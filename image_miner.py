import sys
import json
import os
import fitz  # PyMuPDF
import pandas as pd
import cloudscraper 
from fuzzywuzzy import fuzz

# --- CONFIGURATION ---
# Updated based on your successful login logs
LOGIN_URL = "https://devbackend.succeedquiz.com/api/v1/auth/login" 
UPLOAD_URL = "https://devbackend.succeedquiz.com/api/v1/upload"

# Initialize CloudScraper to bypass Cloudflare protection
scraper = cloudscraper.create_scraper()

def login_and_get_token():
    print("Attempting to log in...")
    email = os.environ.get("SUCCEED_EMAIL")
    password = os.environ.get("SUCCEED_PASSWORD")
    
    if not email or not password:
        print("Error: Missing Email/Password secrets in GitHub.")
        return None

    try:
        # payload for login
        payload = {
            "email": email,
            "password": password
        }
        
        response = scraper.post(LOGIN_URL, json=payload)
        
        if response.status_code in [200, 201]:
            data = response.json()
            # Extract Token based on known API structure
            if 'data' in data and 'accessToken' in data['data']:
                print("Login Successful! Token acquired.")
                return data['data']['accessToken']
            else:
                print(f"Login Failed: Token not found. Structure: {data.keys()}")
                return None
        else:
            print(f"Login Failed ({response.status_code}): {response.text}")
            return None
            
    except Exception as e:
        print(f"Login Connection Error: {e}")
        return None

def upload_image_api(image_bytes, filename, token):
    headers = {
        'Authorization': f'Bearer {token}'
    }
    
    # Ensure filename has an extension
    if "." not in filename: filename += ".png"

    # File tuple for requests/scraper
    files = [
        ('file', (filename, image_bytes, 'image/png')) 
    ]

    try:
        response = scraper.post(UPLOAD_URL, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            data = response.json()
            
            # --- FIXED RESPONSE PARSING ---
            # Your API returns: { data: { files: [ { url: "..." } ] } }
            
            # Logic 1: Check for the nested 'files' array
            if 'data' in data and isinstance(data['data'], dict):
                inner_data = data['data']
                
                # Check if 'files' list exists and has items
                if 'files' in inner_data and isinstance(inner_data['files'], list):
                    if len(inner_data['files']) > 0:
                        return inner_data['files'][0].get('url')
                
                # Fallback: Check for direct 'url' in data object
                if 'url' in inner_data: return inner_data['url']
                if 'link' in inner_data: return inner_data['link']

            # Logic 2: Check root level
            if 'url' in data: return data['url']
            if 'secure_url' in data: return data['secure_url']

            # Debugging Output if we can't find it
            print(f"  -> ERROR: URL key not found! Response: {data}")
            return None
            
        else:
            print(f"  -> API Error ({response.status_code}): {response.text}")
            return None
            
    except Exception as e:
        print(f"  -> Exception during upload: {e}")
        return None

def find_image_below_text(doc, text_query):
    query_short = str(text_query)[:100]
    best_match_page = -1
    best_rect = None
    highest_ratio = 0
    
    # 1. Find Text
    for page_num, page in enumerate(doc):
        text_blocks = page.get_text("blocks")
        for block in text_blocks:
            ratio = fuzz.partial_ratio(query_short, block[4])
            if ratio > 85 and ratio > highest_ratio:
                highest_ratio = ratio
                best_match_page = page_num
                best_rect = fitz.Rect(block[:4])

    if best_match_page == -1: return None

    # --- SEARCH STRATEGY ---
    
    # Function to scan a specific page
    def scan_page(page_idx, min_y, max_dist):
        try:
            page = doc[page_idx]
        except IndexError: return None # End of doc
        
        images = page.get_images(full=True)
        candidate = None
        current_min_dist = max_dist
        
        for img in images:
            xref = img[0]
            rects = page.get_image_rects(xref)
            if not rects: continue
            rect = rects[0]
            
            # Check if image is below the threshold (min_y)
            if rect.y0 >= min_y:
                dist = rect.y0 - min_y
                if dist < current_min_dist:
                    current_min_dist = dist
                    candidate = xref
        return candidate

    # 1. Look on SAME Page (Below text)
    text_bottom = best_rect.y1
    found_xref = scan_page(best_match_page, text_bottom, 800) # Look down 800px
    
    # 2. Look on NEXT Page (Top of page)
    # If nothing found, check the very top of the next page (first 300px)
    if not found_xref:
        # print("  -> checking next page...") 
        found_xref = scan_page(best_match_page + 1, 0, 300)

    # 3. Extract if found
    if found_xref:
        base = doc.extract_image(found_xref)
        return {"bytes": base["image"], "ext": base["ext"]}
    
    return None

def main():
    # Arguments passed by GitHub Actions YAML
    input_excel = sys.argv[1]
    pdf_path = sys.argv[2]
    output_json = sys.argv[3]

    # 1. Authenticate
    api_token = login_and_get_token()
    if not api_token:
        # Create empty file so next steps don't crash
        with open(output_json, 'w') as f: json.dump({}, f)
        return

    print(f"Reading Excel: {input_excel}")
    try:
        df = pd.read_excel(input_excel)
        questions = df.to_dict(orient='records')
    except Exception as e:
        print(f"Excel Read Error: {e}")
        return

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"PDF Read Error: {e}")
        return

    lookup_map = {}
    print("Starting Image Mining...")

    # 2. Loop through questions
    for i, q in enumerate(questions):
        # Handle various boolean formats (True, "True", "true", "1")
        has_img_val = q.get('has_image', False)
        is_flagged = str(has_img_val).lower() in ['true', '1']
        
        if is_flagged:
            q_text = str(q.get('Question', ''))
            print(f"Searching Q{i}...")
            
            img_data = find_image_below_text(doc, q_text)
            
            if img_data:
                filename = f"q_{i}.{img_data['ext']}"
                # Upload using the session token
                url = upload_image_api(img_data['bytes'], filename, api_token)
                
                if url:
                    print(f"  -> Uploaded: {url}")
                    # Save to map: Question Text -> Image URL
                    lookup_map[q_text] = url
                else:
                    print("  -> Upload failed (Check logs)")
            else:
                print("  -> No image found visually below text")

    # 3. Save Results
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(lookup_map, f, indent=4)
    
    print(f"Mining Complete. Saved {len(lookup_map)} images.")

if __name__ == "__main__":
    main()

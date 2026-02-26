import sys
import json
import fitz  # PyMuPDF
import pandas as pd
import cloudscraper

# --- CONFIGURATION ---
LOGIN_URL = "https://devbackend.succeedquiz.com/api/v1/auth/login"
UPLOAD_URL = "https://devbackend.succeedquiz.com/api/v1/upload"

scraper = cloudscraper.create_scraper()

# ----------------- AUTH & UPLOAD -----------------

def login_and_get_token():
    # --- HARDCODED CREDENTIALS ---
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

# ----------------- NATIVE PDF EXTRACTION (V1 LOGIC) -----------------

def extract_all_native_images(pdf_path):
    """
    V1 Logic: Scans the PDF and extracts all natively embedded images in order.
    Does NOT rely on CirraScale or coordinates.
    """
    doc = fitz.open(pdf_path)
    extracted_images = []
    
    for page_index in range(len(doc)):
        page = doc[page_index]
        image_list = page.get_images(full=True)
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            extracted_images.append(image_bytes)
            
    print(f"✅ Found {len(extracted_images)} native images embedded in the PDF.")
    return extracted_images

# ----------------- MAIN -----------------

def main():
    # V1 usually only expects 3 arguments, but we accept 4 just in case 
    # your GitHub Actions workflow still passes the 'coords.json' argument.
    if len(sys.argv) < 4: 
        print("❌ Missing arguments. Expects: excel, pdf, output")
        return 

    input_excel = sys.argv[1]
    pdf_path = sys.argv[2]
    # Handle both 3-arg and 4-arg setups seamlessly
    output_json = sys.argv[4] if len(sys.argv) == 5 else sys.argv[3]

    token = login_and_get_token()
    if not token: 
        print("❌ Exiting: Could not obtain auth token.")
        return

    try:
        df = pd.read_excel(input_excel)
        # Extract all images from the PDF upfront
        available_images = extract_all_native_images(pdf_path)
    except Exception as e:
        print(f"\n🚨 CRITICAL ERROR LOADING FILES 🚨\n{e}\n")
        with open(output_json, 'w', encoding='utf-8') as f: json.dump({}, f)
        return

    result_map = {} 
    image_counter = 0

    print(f"\n--- Starting V1 Native Image Mapping ---")

    for idx, row in df.iterrows():
        q_text_raw = str(row.get('Question', ''))
        
        # V1 Logic: Check the LLM's 'has_image' flag
        has_image_raw = str(row.get('has_image', '')).lower()
        is_has_image_true = has_image_raw in ['true', '1', 'yes']
        
        if is_has_image_true:
            if image_counter < len(available_images):
                # Pop the next available image in the sequence
                img_bytes = available_images[image_counter]
                image_counter += 1
                
                url = upload_image_api(img_bytes, f"q{idx+1}_v1_auto.jpg", token)
                
                if url:
                    print(f"✅ Q{idx+1}: Image Uploaded -> {url}")
                    result_map[q_text_raw] = url
                else:
                    print(f"❌ Q{idx+1}: Upload Failed to Succeed Quiz backend.")
            else:
                print(f"⚠️ Q{idx+1}: Flagged 'has_image=True', but ran out of images in the PDF!")

    # Save Final Map
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result_map, f, indent=4)

    print("\n" + "="*40)
    print("📊 V1 IMAGE MINER SUMMARY")
    print("="*40)
    print(f"Total Native Images Found: {len(available_images)}")
    print(f"Total Images Mapped      : {image_counter}")
    print(f"Successfully Uploaded    : {len(result_map)}")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()

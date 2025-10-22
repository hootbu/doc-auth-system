import re
import cv2
import pytesseract
import uvicorn
import shutil
import tempfile
import os
from PIL import Image
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from typing import Dict, Any
import numpy as np

app = FastAPI(title="Belge Doğrulama Servisi")

def metni_temizle(metin: str) -> str:
    return re.sub(r'[\n\t\f\r\s]+', ' ', metin).strip()

def kimlik_icin_on_isle(img: np.ndarray) -> Image:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    thresh = cv2.threshold(denoised, 128, 255, cv2.THRESH_BINARY)[1]
    return Image.fromarray(thresh)

def kimlik_isle(dosya_yolu: str) -> Dict[str, str]:
    try:
        img = cv2.imread(dosya_yolu)
        if img is None:
            return {"ham_metin": ""}
        pil_image = kimlik_icin_on_isle(img)
        custom_config = r'--psm 3 lang="tur"'
        ham_metin = pytesseract.image_to_string(pil_image, config=custom_config)
        return {"ham_metin": ham_metin.upper()}
    except Exception as e:
        print(f"Hata (kimlik_isle): {e}")
        return {"ham_metin": ""}

def form_isle(dosya_yolu: str) -> Dict[str, str]:
    try:
        img = cv2.imread(dosya_yolu)
        if img is None: return {"ad_soyad": "", "tckn": ""}
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
        pil_image = Image.fromarray(denoised)
        custom_config = r'--psm 6 lang="tur"'
        ham_metin = pytesseract.image_to_string(pil_image, config=custom_config)
        ad_soyad = ""
        tckn = ""
        tckn_matches = re.findall(r'\b[1-9][0-9]{10}\b', ham_metin)
        if tckn_matches:
            tckn = tckn_matches[-1]
            pattern_str = r'([^\n]+)\n+\s*' + re.escape(tckn)
            ad_soyad_match = re.search(pattern_str, ham_metin, re.IGNORECASE | re.MULTILINE)
            if ad_soyad_match:
                ad_soyad = ad_soyad_match.group(1).strip()
        return {"ad_soyad": ad_soyad.upper().strip(), "tckn": tckn.strip()}
    except Exception as e:
        print(f"Hata (form_isle): {e}")
        return {"ad_soyad": "", "tckn": ""}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try:
        return FileResponse("index.html")
    except RuntimeError:
        return HTMLResponse("<html><body><h1>Hata: index.html bulunamadı.</h1></body></html>")

@app.post("/dogrula")
async def dogrula_belgeler(kimlik: UploadFile = File(...), form: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as kimlik_temp:
        shutil.copyfileobj(kimlik.file, kimlik_temp)
        kimlik_yolu = kimlik_temp.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as form_temp:
        shutil.copyfileobj(form.file, form_temp)
        form_yolu = form_temp.name
    try:
        kimlik_data = kimlik_isle(kimlik_yolu)
        kimlik_ham_metin = kimlik_data.get("ham_metin", "")
        form_verisi = form_isle(form_yolu)
        form_tckn = form_verisi.get("tckn", "")
        form_ad_soyad = form_verisi.get("ad_soyad", "")
        hatalar_json = []
        hatalar_konsol = []
        sonuc_mesaji = "Olumlu"
        tckn_hata_mesaji = "Belgedeki TC Kimlik Numarası Hatalı"
        if not form_tckn:
            hatalar_json.append(tckn_hata_mesaji)
            hatalar_konsol.append(tckn_hata_mesaji)
        elif form_tckn not in kimlik_ham_metin:
            hatalar_json.append(tckn_hata_mesaji)
            hatalar_konsol.append(tckn_hata_mesaji)
        ad_soyad_hata_mesaji = "Belgedeki Ad Soyad Hatalı"
        if not form_ad_soyad:
            hatalar_json.append(ad_soyad_hata_mesaji)
            hatalar_konsol.append(ad_soyad_hata_mesaji)
        else:
            name_parts = form_ad_soyad.split()
            bulunamayan_parcalar = []
            for part in name_parts:
                clean_part = re.sub(r'[^\w]', '', part)
                if clean_part and clean_part not in kimlik_ham_metin:
                    bulunamayan_parcalar.append(part)
            if bulunamayan_parcalar:
                hatalar_json.append(ad_soyad_hata_mesaji)
                hatalar_konsol.append(ad_soyad_hata_mesaji)
        if hatalar_json:
            sonuc_mesaji = "Olumsuz"
        print("\n--- DOĞRULAMA KONSOL ÇIKTISI ---")
        if not hatalar_konsol:
            print("Olumlu")
        else:
            for hata in sorted(list(set(hatalar_konsol))):
                print(hata)
        print("----------------------------------\n")
        return {
            "sonuc": sonuc_mesaji,
            "detaylar": sorted(list(set(hatalar_json))) if hatalar_json else ["Tüm bilgiler eşleşti."]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sunucu hatası: {e}")
    finally:
        os.remove(kimlik_yolu)
        os.remove(form_yolu)

if __name__ == "__main__":
    print("FastAPI sunucusu http://127.0.0.1:8000 adresinde başlatılıyor...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
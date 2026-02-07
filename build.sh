#!/bin/bash
echo "🔧 Rozpoczynam instalację DPD Bota..."

# Instalacja systemowych zależności
echo "📦 Instaluję Tesseract OCR..."
apt-get update
apt-get install -y tesseract-ocr
apt-get install -y tesseract-ocr-eng
apt-get install -y tesseract-ocr-pol

# Sprawdź czy Tesseract jest zainstalowany
echo "✅ Tesseract wersja:"
tesseract --version

# Instalacja zależności Pythona
echo "🐍 Instaluję zależności Pythona..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎉 Instalacja zakończona!"

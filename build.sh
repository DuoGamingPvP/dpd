#!/bin/bash
echo "Installing Tesseract..."
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-eng

echo "Installing Python packages..."
pip install -r requirements.txt

# Sprawdź czy tesseract działa
echo "Tesseract version:"
tesseract --version

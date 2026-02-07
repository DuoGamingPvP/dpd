import os
import logging
import re
from io import BytesIO
from PIL import Image
import pytesseract
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
import asyncio
from datetime import datetime

# ========== KONFIGURACJA ==========
TELEGRAM_TOKEN = "TWÓJ_TOKEN_BOTA"  # ⚠️ Zastąp swoim tokenem
ALLOWED_USER_IDS = []  # Pusta lista = dostęp dla wszystkich

# Konfiguracja przetwarzania
BOTTOM_AREA_PERCENT = 0.18  # Tylko 18% od dołu
CONTRAST_THRESHOLD = 140

# ========== KONFIGURACJA LOGOWANIA ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== FUNKCJE PRZETWARZANIA OBRAZÓW ==========
def preprocess_image(image_bytes):
    """Przygotowuje obraz do OCR - wycina tylko dół i zwiększa kontrast"""
    try:
        # Otwórz obraz z bajtów
        image = Image.open(BytesIO(image_bytes))
        
        # Konwertuj na RGB jeśli trzeba
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        img_width, img_height = image.size
        
        # WYCIĄGNIJ TYLKO DÓŁ (18%)
        bottom_height = int(img_height * BOTTOM_AREA_PERCENT)
        start_y = img_height - bottom_height
        
        # Przytnij obraz do dolnej części
        cropped = image.crop((0, start_y, img_width, img_height))
        
        # Zwiększ kontrast (binaryzacja)
        grayscale = cropped.convert('L')
        pixels = grayscale.load()
        
        for y in range(grayscale.height):
            for x in range(grayscale.width):
                if pixels[x, y] > CONTRAST_THRESHOLD:
                    pixels[x, y] = 255  # Biały
                else:
                    pixels[x, y] = 0    # Czarny
        
        return grayscale, image
        
    except Exception as e:
        logger.error(f"Błąd przetwarzania obrazu: {e}")
        raise

def extract_dpd_number(image_bytes):
    """Główna funkcja ekstrakcji numeru DPD z obrazu"""
    try:
        # Przetwórz obraz
        processed_image, original_image = preprocess_image(image_bytes)
        
        # Wykonaj OCR na przetworzonym obrazie
        text = pytesseract.image_to_string(
            processed_image,
            config='--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        )
        
        logger.info(f"OCR rozpoznał tekst: {text}")
        
        # Znajdź numer DPD
        dpd_number = find_dpd_number_in_text(text)
        
        if dpd_number:
            # Popraw numer
            corrected_number = correct_dpd_number(dpd_number)
            return corrected_number, original_image, processed_image
        
        return None, original_image, processed_image
        
    except Exception as e:
        logger.error(f"Błąd ekstrakcji: {e}")
        return None, None, None

def find_dpd_number_in_text(text):
    """Algorytm wyszukiwania numeru DPD w tekście"""
    if not text:
        return None
    
    clean_text = re.sub(r'\s+', ' ', text).upper().strip()
    
    # 1. Szukaj 13 cyfr + opcjonalna litera
    pattern_13 = r'\b\d{13}[A-Z]?\b'
    match_13 = re.search(pattern_13, clean_text)
    if match_13:
        return match_13.group()
    
    # 2. Szukaj 12-14 cyfr
    pattern_long = r'\b\d{12,14}\b'
    match_long = re.search(pattern_long, clean_text)
    if match_long:
        return match_long.group()
    
    # 3. Szukaj 10+ cyfr
    pattern_10 = r'\b\d{10,}\b'
    match_10 = re.search(pattern_10, clean_text)
    if match_10:
        num = match_10.group()
        if len(num) >= 12:
            return num[:13]
        return num
    
    # 4. Szukaj w pobliżu kluczowych słów
    keywords = ['DPD', 'NR', 'TRACKING', 'PRZESYLKA', 'NUMER']
    for keyword in keywords:
        if keyword in clean_text:
            parts = clean_text.split(keyword)
            for part in parts:
                numbers = re.findall(r'\d+', part)
                if numbers:
                    for num in numbers:
                        if len(num) >= 10:
                            return num[:13] if len(num) >= 13 else num
    
    return None

def correct_dpd_number(number):
    """Poprawia numer DPD zgodnie z regułami"""
    if not number:
        return None
    
    corrected = str(number).upper()
    
    # 1. ZAMIEŃ 18 NA 10 NA POCZĄTKU
    if corrected.startswith('18') and len(corrected) >= 3:
        corrected = '10' + corrected[2:]
    
    # 2. Zostaw tylko cyfry
    digits = re.sub(r'[^0-9]', '', corrected)
    
    # 3. Weź pierwsze 13 cyfr
    if len(digits) > 13:
        digits = digits[:13]
    
    # 4. DODAJ U NA KOŃCU (jeśli ma 13 cyfr)
    if len(digits) == 13:
        return digits + 'U'
    elif len(digits) == 12:
        # Jeśli 12 cyfr, dodaj 0 na końcu i U
        return digits + '0U'
    else:
        return digits

# ========== FUNKCJE BOTA TELEGRAM ==========
async def start(update: Update, context: CallbackContext):
    """Obsługa komendy /start"""
    welcome_text = """
    🤖 *DPD Extractor Bot* 🤖

    *Witaj!* Jestem botem, który automatycznie:
    1. 📸 Analizuje etykiety DPD ze zdjęć
    2. 🔧 Naprawia błędy OCR (18→10)
    3. ➕ Dodaje literę "U" na końcu numeru
    4. 📄 Eksportuje do pliku TXT

    *Jak używać:*
    • Wyślij mi zdjęcie etykiety DPD (JPG/PNG)
    • Mogę przetwarzać wiele zdjęć na raz
    • Użyj /txt aby pobrać wszystkie numery jako plik TXT
    • Użyj /clear aby wyczyścić listę numerów

    *Działanie:*
    Bot analizuje tylko *dolną część* etykiety (18%), gdzie znajduje się kod kreskowy i numer.
    
    Przykład poprawy:
    `1855747430248` → `1055747430248U`
    """
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def handle_photo(update: Update, context: CallbackContext):
    """Obsługa przesyłanych zdjęć"""
    try:
        user_id = update.message.from_user.id
        
        # Sprawdź czy użytkownik ma dostęp
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("❌ Nie masz dostępu do tego bota.")
            return
        
        # Wyślij wiadomość o rozpoczęciu przetwarzania
        status_msg = await update.message.reply_text(
            "🔍 *Analizuję dół etykiety (18%)...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Pobierz największą dostępną wersję zdjęcia
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        
        # Pobierz zdjęcie jako bajty
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Przetwórz zdjęcie
        dpd_number, original_image, processed_image = extract_dpd_number(photo_bytes)
        
        if dpd_number:
            # Zapisz numer w kontekście użytkownika
            if 'dpd_numbers' not in context.user_data:
                context.user_data['dpd_numbers'] = []
            
            context.user_data['dpd_numbers'].append({
                'number': dpd_number,
                'date': datetime.now(),
                'filename': f"dpd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            })
            
            # Przygotuj miniaturki do pokazania
            original_thumbnail = original_image.copy()
            original_thumbnail.thumbnail((200, 200))
            
            processed_thumbnail = processed_image.copy()
            processed_thumbnail.thumbnail((200, 200))
            
            # Stwórz collage porównawczy
            collage = Image.new('RGB', (420, 200), (255, 255, 255))
            collage.paste(original_thumbnail, (10, 10))
            collage.paste(processed_thumbnail, (210, 10))
            
            # Zapisz collage do bajtów
            collage_bytes = BytesIO()
            collage.save(collage_bytes, format='JPEG')
            collage_bytes.seek(0)
            
            # Wyślij wynik z miniaturkami
            result_text = f"""
✅ *Numer DPD znaleziony!*

📦 *Oryginalny:* `{dpd_number[:-1] if len(dpd_number) > 1 else dpd_number}`
🔧 *Poprawiony:* `{dpd_number}`

📊 *Statystyki:*
• Znalezionych numerów: *{len(context.user_data['dpd_numbers'])}*
• Użyj /txt aby pobrać wszystkie

*Co zrobiono:*
1. Przeanalizowano tylko dół etykiety (18%)
2. Poprawiono 18→10 na początku
3. Dodano literę "U" na końcu
            """
            
            await update.message.reply_photo(
                photo=InputFile(collage_bytes, filename='comparison.jpg'),
                caption=result_text,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Aktualizuj wiadomość statusu
            await status_msg.edit_text(
                f"✅ Znaleziono numer: `{dpd_number}`",
                parse_mode=ParseMode.MARKDOWN
            )
            
        else:
            await status_msg.edit_text(
                "❌ *Nie znaleziono numeru DPD*\n\nUpewnij się, że zdjęcie jest wyraźne "
                "i pokazuje dół etykiety z kodem kreskowym.",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Błąd przetwarzania zdjęcia: {e}")
        await update.message.reply_text(
            f"❌ *Wystąpił błąd:*\n`{str(e)}`\n\nSpróbuj ponownie z innym zdjęciem.",
            parse_mode=ParseMode.MARKDOWN
        )

async def export_txt(update: Update, context: CallbackContext):
    """Eksportuje wszystkie numery do pliku TXT"""
    try:
        user_id = update.message.from_user.id
        
        if 'dpd_numbers' not in context.user_data or not context.user_data['dpd_numbers']:
            await update.message.reply_text(
                "📭 *Brak numerów do eksportu!*\n\nNajpierw wyślij mi zdjęcia etykiet DPD.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Przygotuj zawartość pliku TXT
        numbers = [item['number'] for item in context.user_data['dpd_numbers']]
        txt_content = "\n".join(numbers)
        
        # Dodaj nagłówek z informacjami
        header = f"""# Numery DPD - wygenerowane przez bota
# Data eksportu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Ilość numerów: {len(numbers)}

"""
        full_content = header + txt_content
        
        # Stwórz plik w pamięci
        txt_bytes = BytesIO(full_content.encode('utf-8'))
        txt_bytes.seek(0)
        
        # Wyślij plik
        filename = f"numery_dpd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await update.message.reply_document(
            document=InputFile(txt_bytes, filename=filename),
            caption=f"📄 *Plik z numerami DPD*\n\nZawiera *{len(numbers)}* numerów.\nKażdy numer został automatycznie poprawiony.",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Błąd eksportu TXT: {e}")
        await update.message.reply_text(
            f"❌ *Błąd eksportu:*\n`{str(e)}`",
            parse_mode=ParseMode.MARKDOWN
        )

async def clear_numbers(update: Update, context: CallbackContext):
    """Czyści wszystkie zapisane numery"""
    if 'dpd_numbers' in context.user_data:
        count = len(context.user_data['dpd_numbers'])
        context.user_data['dpd_numbers'] = []
        
        await update.message.reply_text(
            f"🗑️ *Wyczyściono {count} numerów!*\n\nMożesz zacząć od nowa przesyłając zdjęcia.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "📭 *Brak numerów do wyczyszczenia!*",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_stats(update: Update, context: CallbackContext):
    """Pokazuje statystyki"""
    if 'dpd_numbers' in context.user_data and context.user_data['dpd_numbers']:
        numbers = context.user_data['dpd_numbers']
        
        # Znajdź unikalne numery
        unique_numbers = set(item['number'] for item in numbers)
        
        stats_text = f"""
📊 *Statystyki DPD Extractor*

• Łącznie przetworzonych: *{len(numbers)}*
• Unikalnych numerów: *{len(unique_numbers)}*
• Ostatni numer: `{numbers[-1]['number']}`

*Ostatnie 5 numerów:*
"""
        
        # Dodaj ostatnie 5 numerów
        for i, item in enumerate(numbers[-5:], 1):
            stats_text += f"{i}. `{item['number']}`\n"
        
        stats_text += f"\nUżyj /txt aby pobrać wszystkie."
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            "📭 *Brak danych statystycznych!*\n\nWyślij najpierw zdjęcia etykiet.",
            parse_mode=ParseMode.MARKDOWN
        )

async def help_command(update: Update, context: CallbackContext):
    """Pokazuje pomoc"""
    help_text = """
🆘 *Pomoc - DPD Extractor Bot*

*Dostępne komendy:*
/start - Rozpocznij pracę z botem
/help - Pokazuje tę wiadomość pomocy
/txt - Eksportuje wszystkie numery do pliku TXT
/stats - Pokazuje statystyki
/clear - Czyści wszystkie zapisane numery

*Jak używać:*
1. Wyślij zdjęcie etykiety DPD (JPG/PNG)
2. Bot automatycznie:
   • Analizuje tylko dół etykiety (18%)
   • Poprawia błąd OCR: 18→10
   • Dodaje "U" na końcu numeru
3. Zbieraj numery i eksportuj do TXT

*Przykład:*
Wysyłasz zdjęcie → Bot znajduje numer → Zapisuje go
Po zebraniu kilku → /txt → Pobierasz plik z numerami

*Wymagania:*
• Zdjęcie powinno być wyraźne
• Pokazywać dół etykiety z kodem
• Format: JPG lub PNG
"""
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: Update, context: CallbackContext):
    """Obsługa błędów"""
    logger.error(f"Błąd: {context.error}")
    
    if update and update.message:
        await update.message.reply_text(
            "❌ *Wystąpił nieoczekiwany błąd!*\n\nSpróbuj ponownie lub skontaktuj się z administratorem.",
            parse_mode=ParseMode.MARKDOWN
        )

# ========== GŁÓWNA FUNKCJA ==========
def main():
    """Uruchamia bota"""
    # Sprawdź czy Tesseract jest zainstalowany
    try:
        pytesseract.get_tesseract_version()
    except:
        print("❌ Tesseract OCR nie jest zainstalowany!")
        print("Instalacja:")
        print("  Ubuntu/Debian: sudo apt-get install tesseract-ocr")
        print("  Windows: Pobierz z https://github.com/UB-Mannheim/tesseract/wiki")
        print("  Mac: brew install tesseract")
        return
    
    print("🤖 Uruchamianie DPD Extractor Bot...")
    print("📸 Bot będzie analizować tylko DÓŁ etykiet (18%)")
    print("🔧 Automatycznie poprawia 18→10 i dodaje U")
    
    # Stwórz aplikację bota
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Dodaj handlerów
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("txt", export_txt))
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CommandHandler("clear", clear_numbers))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)
    
    # Uruchom bota
    print("✅ Bot jest gotowy! Szukaj go na Telegramie...")
    print("📞 Użyj /start w rozmowie z botem")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
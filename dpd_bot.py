import os
import sys
import logging
import re
import asyncio
from io import BytesIO
from PIL import Image
import pytesseract
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# Sprawdź czy jesteśmy na Renderze
ON_RENDER = os.environ.get('RENDER', False)

if ON_RENDER:
    print("🚀 Uruchamiam na Render.com")
    # Ustaw odpowiednie ustawienia dla Render
    os.environ['DISABLE_SSL'] = 'True'
# ========== KONFIGURACJA ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
PORT = int(os.environ.get("PORT", 8080))

# Konfiguracja przetwarzania
BOTTOM_AREA_PERCENT = 0.18
CONTRAST_THRESHOLD = 140

# ========== HEALTH CHECK SERVER ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'DPD Bot is running!')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    print(f"🩺 Health server running on port {PORT}")
    server.serve_forever()

# ========== KONFIGURACJA LOGOWANIA ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== FUNKCJE PRZETWARZANIA ==========
def preprocess_image(image_bytes):
    """Przygotowuje obraz do OCR"""
    try:
        image = Image.open(BytesIO(image_bytes))
        
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        img_width, img_height = image.size
        bottom_height = int(img_height * BOTTOM_AREA_PERCENT)
        start_y = img_height - bottom_height
        
        cropped = image.crop((0, start_y, img_width, img_height))
        grayscale = cropped.convert('L')
        pixels = grayscale.load()
        
        for y in range(grayscale.height):
            for x in range(grayscale.width):
                if pixels[x, y] > CONTRAST_THRESHOLD:
                    pixels[x, y] = 255
                else:
                    pixels[x, y] = 0
        
        return grayscale, image
        
    except Exception as e:
        logger.error(f"Błąd przetwarzania obrazu: {e}")
        raise

def extract_dpd_number(image_bytes):
    """Ekstrakcja numeru DPD z obrazu"""
    try:
        processed_image, original_image = preprocess_image(image_bytes)
        
        text = pytesseract.image_to_string(
            processed_image,
            config='--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        )
        
        logger.info(f"OCR rozpoznał: {text[:50]}...")
        
        dpd_number = find_dpd_number_in_text(text)
        
        if dpd_number:
            corrected_number = correct_dpd_number(dpd_number)
            return corrected_number, original_image, processed_image
        
        return None, original_image, processed_image
        
    except Exception as e:
        logger.error(f"Błąd ekstrakcji: {e}")
        return None, None, None

def find_dpd_number_in_text(text):
    """Wyszukuje numer DPD w tekście"""
    if not text:
        return None
    
    clean_text = re.sub(r'\s+', ' ', text).upper().strip()
    
    patterns = [
        r'\b\d{13}[A-Z]?\b',
        r'\b\d{12,14}\b',
        r'\b\d{10,}\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, clean_text)
        if match:
            num = match.group()
            return num[:13] if len(num) >= 13 else num
    
    keywords = ['DPD', 'NR', 'TRACKING']
    for keyword in keywords:
        if keyword in clean_text:
            parts = clean_text.split(keyword)
            for part in parts:
                numbers = re.findall(r'\d+', part)
                for num in numbers:
                    if len(num) >= 10:
                        return num[:13]
    
    return None

def correct_dpd_number(number):
    """Poprawia numer DPD"""
    if not number:
        return None
    
    corrected = str(number).upper()
    
    if corrected.startswith('18') and len(corrected) >= 3:
        corrected = '10' + corrected[2:]
    
    digits = re.sub(r'[^0-9]', '', corrected)
    
    if len(digits) > 13:
        digits = digits[:13]
    
    if len(digits) == 13:
        return digits + 'U'
    elif len(digits) == 12:
        return digits + '0U'
    else:
        return digits

# ========== HANDLERY TELEGRAM ==========
async def start(update: Update, context: CallbackContext):
    """Komenda /start"""
    welcome = """
🤖 *DPD Extractor Bot* v2.0
    
*Co potrafię:*
1. 📸 Analizuję etykiety DPD
2. 🔧 Naprawiam błędy OCR (18→10)
3. ➕ Dodaję "U" na końcu
4. 📄 Eksportuję do TXT
    
*Jak używać:*
• Wyślij zdjęcie etykiety
• Bot znajdzie i poprawi numer
• Użyj /txt aby pobrać wszystkie
    
*Przykład:*
`1855747430248` → `1055747430248U`
"""
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)

async def handle_photo(update: Update, context: CallbackContext):
    """Obsługa zdjęć"""
    try:
        status_msg = await update.message.reply_text(
            "🔍 *Analizuję dół etykiety (18%)...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()
        
        dpd_number, original_image, processed_image = extract_dpd_number(photo_bytes)
        
        if dpd_number:
            if 'dpd_numbers' not in context.user_data:
                context.user_data['dpd_numbers'] = []
            
            context.user_data['dpd_numbers'].append({
                'number': dpd_number,
                'date': datetime.now()
            })
            
            result_text = f"""
✅ *Numer DPD znaleziony!*

📦 *Poprawiony:* `{dpd_number}`

📊 *Statystyki:*
• Znalezionych: *{len(context.user_data['dpd_numbers'])}*
• /txt - pobierz wszystkie
• /stats - statystyki
"""
            await status_msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await status_msg.edit_text(
                "❌ *Nie znaleziono numeru DPD*\n\nUpewnij się, że zdjęcie pokazuje dół etykiety.",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Błąd: {e}")
        await update.message.reply_text(f"❌ Błąd: {str(e)}")

async def export_txt(update: Update, context: CallbackContext):
    """Komenda /txt"""
    try:
        if 'dpd_numbers' not in context.user_data or not context.user_data['dpd_numbers']:
            await update.message.reply_text("📭 *Brak numerów!* Wyślij najpierw zdjęcia.")
            return
        
        numbers = [item['number'] for item in context.user_data['dpd_numbers']]
        txt_content = "\n".join(numbers)
        
        txt_bytes = BytesIO(txt_content.encode('utf-8'))
        txt_bytes.seek(0)
        
        filename = f"dpd_numbers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await update.message.reply_document(
            document=InputFile(txt_bytes, filename=filename),
            caption=f"📄 *{len(numbers)} numerów DPD*"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Błąd eksportu: {str(e)}")

async def show_stats(update: Update, context: CallbackContext):
    """Komenda /stats"""
    if 'dpd_numbers' in context.user_data and context.user_data['dpd_numbers']:
        numbers = context.user_data['dpd_numbers']
        stats = f"""
📊 *Statystyki*

• Łącznie: *{len(numbers)}*
• Ostatni: `{numbers[-1]['number']}`

*Ostatnie 5:*
"""
        for i, item in enumerate(numbers[-5:], 1):
            stats += f"{i}. `{item['number']}`\n"
        
        await update.message.reply_text(stats, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("📭 *Brak statystyk*")

async def clear_numbers(update: Update, context: CallbackContext):
    """Komenda /clear"""
    if 'dpd_numbers' in context.user_data:
        count = len(context.user_data['dpd_numbers'])
        context.user_data['dpd_numbers'] = []
        await update.message.reply_text(f"🗑️ *Wyczyściono {count} numerów*")
    else:
        await update.message.reply_text("📭 *Brak numerów do wyczyszczenia*")

async def help_command(update: Update, context: CallbackContext):
    """Komenda /help"""
    help_text = """
🆘 *Pomoc - DPD Bot*

*Komendy:*
/start - Start bota
/help - Ta pomoc
/txt - Eksport do TXT
/stats - Statystyki
/clear - Czyść numery

*Wysyłanie zdjęć:*
• Wyślij zdjęcie etykiety DPD
• Bot analizuje tylko DÓŁ (18%)
• Automatycznie poprawia numery

*Przykład działania:*
1. Wysyłasz zdjęcie
2. Bot znajduje numer
3. Poprawia 18→10
4. Dodaje U na końcu
5. Zapisuje numer
6. /txt - pobierasz plik
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# ========== GŁÓWNA FUNKCJA ==========
def main():
    """Uruchomienie bota"""
    if not TELEGRAM_TOKEN:
        print("❌ BRAK TOKENU! Ustaw zmienną środowiskową TELEGRAM_TOKEN")
        return
    
    print("🤖 Uruchamianie DPD Bot...")
    print(f"🔧 Port: {PORT}")
    print("📸 OCR: Tesseract")
    print("⚡ Render.com ready!")
    
    # Uruchom health server w tle
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Stwórz aplikację bota
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Dodaj handlerów
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("txt", export_txt))
    application.add_handler(CommandHandler("stats", show_stats))
    application.add_handler(CommandHandler("clear", clear_numbers))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Uruchom bota
    print("✅ Bot starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()



import os
import re
import sys
import json
import logging
import traceback
from typing import Optional, Dict, Any, Union, Tuple
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import tkinter.messagebox as messagebox
try:
    import fitz
except ImportError:
    print("❌ PyMuPDF не установлен. Установите его командой: pip install PyMuPDF")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('logs', 'pdf_editor.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Создание директорий
os.makedirs('logs', exist_ok=True)

# Пути
current_dir = os.path.dirname(os.path.abspath(__file__))

# Загрузка конфигурации
try:
    with open(os.path.join(current_dir, 'config.json'), 'r', encoding='utf-8') as f:
        config = json.load(f)
except Exception as e:
    logger.error(f"Ошибка загрузки конфигурации: {e}")
    config = {
        "fonts": {
            "tahoma": "fonts/tahoma.ttf",
            "times": "fonts/times.ttf"
        },
        "source_pdf": "source_pdf_path.pdf",
        "result_file": "modified.pdf",
        "upload_dir": "uploads",
        "max_file_size": 10485760
    }

def find_first_pdf(exclude: Optional[set] = None) -> Optional[str]:
    exclude = exclude or set()
    for fname in os.listdir(current_dir):
        if fname.lower().endswith('.pdf') and fname not in exclude:
            return os.path.join(current_dir, fname)
    return None

# Получаем имя входного PDF из аргумента командной строки или используем source_pdf_path.pdf
if len(sys.argv) > 1:
    pdf_path = os.path.join(current_dir, sys.argv[1])
else:
    pdf_path = os.path.join(current_dir, "source_pdf_path.pdf")
    if not os.path.exists(pdf_path):
        print("❌ Файл source_pdf_path.pdf не найден!")
        exit(1)

output_pdf = os.path.join(current_dir, "modified.pdf")

# Константы для расширения патчей
EXTRA_LEFT = 60   # можно увеличить при необходимости
EXTRA_RIGHT = 60
EXTRA_TOP = 2
EXTRA_BOTTOM = 2

# Загрузка путей к шрифтам из конфигурации
tahoma_font_path = os.path.join(current_dir, config["fonts"]["tahoma"])
times_font_path = os.path.join(current_dir, config["fonts"]["times"])

if not os.path.exists(tahoma_font_path) or not os.path.exists(times_font_path):
    logger.error(f"❌ Не найдены файлы шрифтов в {os.path.dirname(tahoma_font_path)}")
    raise FileNotFoundError("Отсутствуют необходимые файлы шрифтов")

# Загружаем координаты из JSON файла
coordinates_path = os.path.join(current_dir, "coordinates.json")
try:
    with open(coordinates_path, 'r', encoding='utf-8') as f:
        coordinates = json.load(f)
except Exception as e:
    print(f"❌ Ошибка при загрузке координат: {e}")
    coordinates = {}

# Шаблоны для определения типов текста
text_patterns = {
    "имя": r'^[А-ЯЁӘІҢҒҮҰҚӨҺ]{2,}$',  # Имя на кириллице заглавными буквами
    "фамилия": r'^[А-ЯЁӘІҢҒҮҰҚӨҺ]{3,}$',  # Фамилия на кириллице заглавными буквами
    "отчество": r'^[А-ЯЁӘІҢҒҮҰҚӨҺ]+ҰЛЫ$|^[А-ЯЁӘІҢҒҮҰҚӨҺ]+ОВНА$|^[А-ЯЁӘІҢҒҮҰҚӨҺ]+ЕВНА$|^[А-ЯЁӘІҢҒҮҰҚӨҺ]+ОВИЧ$|^[А-ЯЁӘІҢҒҮҰҚӨҺ]+ЕВИЧ$',  # Отчество
    "дата": r'^\d{2}\.\d{2}\.\d{4}(?:\s*-\s*\d{2}\.\d{2}\.\d{4})?$',  # Даты в формате DD.MM.YYYY или диапазон дат
    "номер": r'^\d{9,12}$',  # Номера документов
    "город": r'^[А-ЯЁӘІҢҒҮҰҚӨҺ]+$',  # Название города
    "национальность": r'^[А-ЯЁӘІҢҒҮҰҚӨҺ]+$',  # Национальность
    "машиночитаемая_строка": r'^[A-Z<]{2,}$'  # Машиночитаемая строка в загранпаспорте
}

# Замены по умолчанию для каждого типа текста
default_replacements = {
    "имя": "EXAMPLE_NAME",
    "фамилия": "EXAMPLE_SURNAME",
    "отчество": "EXAMPLE_PATRONYMIC",
    "дата": "01.01.2000",
    "номер": "000000000000",
    "город": "EXAMPLE_CITY",
    "национальность": "EXAMPLE_NATIONALITY",
    "машиночитаемая_строка": "SURNAME<<NAME<<<<<<<<<<<<<<<<<<<<",
}

# Конкретные замены (приоритетнее шаблонов)
specific_replacements = {
    # Здесь можно добавить конкретные замены при необходимости
    # Формат: "исходный_текст": "замена"
}

def determine_text_type(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Определяет тип текста и его замену на основе шаблонов и конкретных замен.
    
    Args:
        text: Исходный текст для анализа
        
    Returns:
        Tuple[Optional[str], Optional[str]]: Кортеж (тип текста, замена)
        Если текст не определен, возвращает (None, None)
    """
    # Сначала проверяем конкретные замены
    if text in specific_replacements:
        return "specific", specific_replacements[text]
    
    # Затем проверяем по шаблонам (регулярным выражениям)
    for text_type, pattern in text_patterns.items():
        if re.match(pattern, text):
            return text_type, default_replacements.get(text_type)
    
    return None, None

def get_page_dpi(page):
    """Безопасное получение DPI страницы"""
    try:
        images = page.get_images(full=True)
        if images:
            return images[0][1].get("dpi", (300, 300))
        return (300, 300)  # значение по умолчанию
    except Exception:
        return (300, 300)  # значение по умолчанию

def apply_patch(page: fitz.Page, patch_path: str, text: str, x: float, y: float, font_size: float) -> bool:
    """Применяет патч к заданной позиции на странице с учетом DPI и масштабирования."""
    if not os.path.exists(patch_path):
        logger.error(f"Файл патча не найден: {patch_path}")
        return False
        
    try:
        if text in coordinates:
            bbox = coordinates[text]["bbox"]
            
            # Используем разные размеры для машиночитаемой строки и обычного текста
            if re.match(r'^[A-Z<]{2,}$', text):
                MRZ_EXTRA_TOP = 4  # Увеличенное смещение вверх для MRZ
                MRZ_EXTRA_BOTTOM = 4  # Увеличенное смещение вниз для MRZ
                patch_rect = fitz.Rect(
                    bbox[0] - EXTRA_LEFT,
                    bbox[1] - MRZ_EXTRA_TOP,
                    bbox[2] + EXTRA_RIGHT,
                    bbox[3] + MRZ_EXTRA_BOTTOM
                )
            else:
                patch_rect = fitz.Rect(
                    bbox[0],
                    bbox[1] - font_size * 0.1,
                    bbox[2],
                    bbox[3] + font_size * 0.1
                )
            
            patch_doc = fitz.open(patch_path)
            patch_page = patch_doc[0]
            
            src_rect = patch_page.rect
            zoom_x = patch_rect.width / src_rect.width
            zoom_y = patch_rect.height / src_rect.height
            matrix = fitz.Matrix(zoom_x, zoom_y)
            
            page.show_pdf_page(
                patch_rect,
                patch_doc,
                0,
                matrix,
                clip=patch_page.rect
            )
            
            patch_doc.close()
            return True
            
    except Exception as e:
        print(f"❌ Ошибка при применении патча: {e}")
        return False

def safe_filename(text):
    """Создает безопасное имя файла из текста"""
    # Заменяем специальные символы на их текстовые представления
    replacements = {
        '<': 'LT',
        '>': 'GT',
        ':': '_',
        '"': '_',
        '/': '_',
        '\\': '_',
        '|': '_',
        '?': '_',
        '*': '_',
        ' ': '_'
    }
    
    # Приводим к безопасному имени файла
    safe_name = text
    for char, replacement in replacements.items():
        safe_name = safe_name.replace(char, replacement)
        
    # Дополнительная обработка для машиночитаемой строки
    if 'LTLT' in safe_name:  # Признак машиночитаемой строки
        safe_name = 'mrz_' + safe_name.replace('LT', '')
    
    # Убираем все символы, кроме букв, цифр и некоторых знаков
    safe_name = ''.join(c for c in safe_name if c.isalnum() or c in '_-.')
    
    # Ограничиваем длину имени файла
    if len(safe_name) > 100:
        safe_name = safe_name[:100]
    
    return safe_name

def extract_patches(source_pdf: str, patches_dir: str, coordinates: dict) -> int:
    """Извлекает патчи из чистого PDF с учетом DPI."""
    try:
        os.makedirs(patches_dir, exist_ok=True)
        doc = fitz.open(source_pdf)
        page = doc[0]
        
        # Получаем разрешение исходного документа безопасным способом
        page_dpi = get_page_dpi(page)
        
        extracted_count = 0
        for text, coord in coordinates.items():
            if "bbox" in coord:
                bbox = coord["bbox"]
                
                # Расширяем область патча в зависимости от типа текста
                if re.match(r'^[A-Z<]{2,}$', text):
                    # Машиночитаемая строка
                    rect = fitz.Rect(
                        bbox[0] - EXTRA_LEFT,
                        bbox[1] - EXTRA_TOP,
                        bbox[2] + EXTRA_RIGHT,
                        bbox[3] + EXTRA_BOTTOM
                    )
                else:
                    # Обычный текст
                    rect = fitz.Rect(
                        bbox[0] - 1,
                        bbox[1] - 1,
                        bbox[2] + 1,
                        bbox[3] + 1
                    )
                
                # Создаем безопасное имя файла для патча
                safe_name = safe_filename(text)
                patch_path = os.path.join(patches_dir, f"patch_{safe_name}.pdf")
                
                try:
                    # Создаем новый PDF для патча
                    patch_doc = fitz.open()
                    patch_page = patch_doc.new_page(width=rect.width, height=rect.height)
                    
                    # Копируем область с учетом DPI
                    matrix = fitz.Matrix(page_dpi[0]/72, page_dpi[1]/72)
                    
                    patch_page.show_pdf_page(
                        patch_page.rect,
                        doc,
                        0,
                        matrix,
                        clip=rect
                    )
                    
                    patch_doc.save(patch_path, deflate=True, garbage=4)
                    patch_doc.close()
                    extracted_count += 1
                    print(f"✅ Создан патч для текста: {text}")
                except Exception as e:
                    print(f"❌ Ошибка при создании патча для {text}: {e}")
                    continue
        
        doc.close()
        return extracted_count
        
    except Exception as e:
        print(f"❌ Ошибка при извлечении патчей: {e}")
        return 0

class PDFError(Exception):
    """Базовый класс для ошибок при работе с PDF"""
    pass

class FontNotFoundError(PDFError):
    """Ошибка отсутствия шрифта"""
    pass

class InvalidPDFError(PDFError):
    """Ошибка некорректного PDF файла"""
    pass

class PatchExtractor:
    def __init__(self, source_pdf_path: Optional[str] = None):
        """Инициализация класса с основными параметрами"""
        self.logger = logging.getLogger(__name__)
        self.source_pdf_path = source_pdf_path
        self.patches_dir = os.path.join(current_dir, "patches")
        self.coordinates = coordinates
        self.status_var = None

        # Проверка наличия исходного PDF
        if source_pdf_path and not os.path.exists(source_pdf_path):
            raise FileNotFoundError(f"Исходный PDF файл не найден: {source_pdf_path}")
            
        # Создание директории для патчей
        os.makedirs(self.patches_dir, exist_ok=True)

        # Проверка наличия шрифтов
        self.tahoma_font_path = os.path.join(current_dir, config["fonts"]["tahoma"])
        self.times_font_path = os.path.join(current_dir, config["fonts"]["times"])
        if not os.path.exists(self.tahoma_font_path):
            raise FontNotFoundError(f"Шрифт Tahoma не найден: {self.tahoma_font_path}")
        if not os.path.exists(self.times_font_path):
            raise FontNotFoundError(f"Шрифт Times не найден: {self.times_font_path}")

    def process_pdf_custom(self, input_pdf: str, output_pdf: str, user_data: dict):
        """
        Обработка PDF с подстановкой пользовательских данных по ключам coordinates.json.
        user_data: dict с ключами (name, surname, patronymic, iin, date, city, nationality, issuer, mrz)
        """
        self.logger.info("🔄 Начинаем обработку PDF с пользовательскими данными...")
        doc = fitz.open(input_pdf)
        processed_texts = set()
        # Сопоставление ключей user_data с ключами coordinates.json
        field_map = {
            "surname": "surname",
            "name": "name",
            "patronymic": "patronymic",
            "iin": "iin",
            "date": "date",
            "city": "city",
            "nationality": "nationality",
            "issuer": "issuer",
            "mrz": "mrz"
        }
        for page_num in range(len(doc)):
            page = doc[page_num]
            for field, coord_key in field_map.items():
                if coord_key in self.coordinates and coord_key not in processed_texts:
                    coord_info = self.coordinates[coord_key]
                    bbox = coord_info["bbox"]
                    font_size = coord_info.get("font_size", 16)
                    font_name = coord_info.get("font_name", "Times")
                    replacement = user_data.get(field)
                    if not replacement:
                        continue
                    safe_name = safe_filename(coord_key)
                    patch_path = os.path.join(self.patches_dir, f"patch_{safe_name}.pdf")
                    # Патч
                    if os.path.exists(patch_path):
                        if re.match(r'^[A-Z<]{2,}$', replacement):
                            patch_rect = fitz.Rect(
                                bbox[0] - EXTRA_LEFT,
                                bbox[1] - EXTRA_TOP,
                                bbox[2] + EXTRA_RIGHT,
                                bbox[3] + EXTRA_BOTTOM
                            )
                        else:
                            patch_rect = fitz.Rect(
                                bbox[0],
                                bbox[1] - font_size * 0.1,
                                bbox[2],
                                bbox[3] + font_size * 0.1
                            )
                        patch_doc = fitz.open(patch_path)
                        patch_page = patch_doc[0]
                        zoom_x = patch_rect.width / patch_page.rect.width
                        zoom_y = patch_rect.height / patch_page.rect.height
                        matrix = fitz.Matrix(zoom_x, zoom_y)
                        page.show_pdf_page(
                            patch_rect,
                            patch_doc,
                            0,
                            matrix,
                            clip=patch_page.rect
                        )
                        patch_doc.close()
                    # Вставка текста
                    if "Tahoma" in font_name:
                        page.insert_font(fontname="CustomFont", fontfile=tahoma_font_path)
                        used_font = "CustomFont"
                    else:
                        page.insert_font(fontname="CustomFont", fontfile=times_font_path)
                        used_font = "CustomFont"
                    # Для MRZ и других строк — корректируем вертикальное смещение
                    if coord_key == "mrz":
                        # Для MRZ используем специальное позиционирование
                        font_size = 18.0  # Увеличенный размер для MRZ
                        y_pos = bbox[1] + font_size * 0.85  # Увеличили смещение для MRZ
                    else:
                        y_pos = bbox[1] + font_size * 0.9  # Увеличили смещение для обычного текста
                    page.insert_text(
                        (bbox[0], y_pos),
                        replacement,
                        fontsize=font_size,
                        fontname=used_font,
                        color=(0, 0, 0)
                    )
                    processed_texts.add(coord_key)
        doc.save(
            output_pdf,
            deflate=True,
            garbage=4,
            clean=True
        )
        doc.close()
        print(f"✅ Готово! PDF с пользовательскими заменами сохранён как: {output_pdf}")
    def set_status_var(self, status_var):
        """Установка переменной для отображения статуса"""
        self.status_var = status_var
        
    def set_status_var(self, status_var):
        """Установка переменной для отображения статуса"""
        self.status_var = status_var
        
    def update_patches_list(self):
        """Обновление списка патчей"""
        try:
            if os.path.exists(self.patches_dir):
                patches = [f for f in os.listdir(self.patches_dir) if f.endswith('.pdf')]
                if self.status_var:
                    self.status_var.set(f"Найдено патчей: {len(patches)}")
                else:
                    print(f"Найдено патчей: {len(patches)}")
        except Exception as e:
            print(f"❌ Ошибка при обновлении списка патчей: {e}")
    
    def extract_patches(self):
        if not self.source_pdf_path:
            if self.status_var:
                messagebox.showerror("Ошибка", "Выберите исходный PDF файл!")
            else:
                print("❌ Ошибка: Выберите исходный PDF файл!")
            return
            
        try:
            # Извлекаем патчи с учетом DPI
            extracted_count = extract_patches(
                self.source_pdf_path,
                self.patches_dir,
                self.coordinates
            )
            
            self.update_patches_list()
            
            if self.status_var:
                self.status_var.set(f"Извлечено патчей: {extracted_count}")
                messagebox.showinfo("Готово", f"Успешно извлечено {extracted_count} патчей!")
            else:
                print(f"✅ Успешно извлечено {extracted_count} патчей!")
            
        except Exception as e:
            error_msg = f"Ошибка при извлечении патчей: {str(e)}"
            if self.status_var:
                messagebox.showerror("Ошибка", error_msg)
            else:
                print(f"❌ {error_msg}")
    
    def process_pdf(self, input_pdf: str, output_pdf: str):
        print("🔄 Начинаем обработку PDF...")
        doc = fitz.open(input_pdf)
        
        # Множество для отслеживания уже замененных текстов
        processed_texts = set()
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Сначала обрабатываем машиночитаемую строку
            machine_readable = "SURNAME<<NAME<<<<<<<<<<<<<<<<<<<<<<"
            if machine_readable in coordinates and machine_readable not in processed_texts:
                bbox = coordinates[machine_readable]["bbox"]
                
                # Используем расширенную область для машиночитаемой строки
                inst = fitz.Rect(
                    bbox[0] - EXTRA_LEFT,
                    bbox[1] - EXTRA_TOP,
                    bbox[2] + EXTRA_RIGHT,
                    bbox[3] + EXTRA_BOTTOM
                )
                
                # Сначала накладываем патч
                safe_name = safe_filename(machine_readable)
                patch_path = os.path.join(self.patches_dir, f"patch_{safe_name}.pdf")
                
                if os.path.exists(patch_path):
                    patch_doc = fitz.open(patch_path)
                    patch_page = patch_doc[0]
                    
                    # Вычисляем матрицу масштабирования
                    zoom_x = inst.width / patch_page.rect.width
                    zoom_y = inst.height / patch_page.rect.height
                    matrix = fitz.Matrix(zoom_x, zoom_y)
                    
                    # Накладываем патч с масштабированием
                    page.show_pdf_page(
                        inst,
                        patch_doc,
                        0,
                        matrix
                    )
                    patch_doc.close()
                
                # Получаем информацию о шрифте из области
                text_info = page.get_text("dict", clip=inst)
                if text_info["blocks"]:
                    font_info = text_info["blocks"][0]["lines"][0]["spans"][0]
                    font_name = font_info["font"]
                    font_size = font_info["size"]
                else:
                    font_name = "Times"
                    font_size = inst.height * 0.7
                
                # Определяем шрифт и вставляем текст
                if "Tahoma" in font_name:
                    page.insert_font(fontname="CustomFont", fontfile=tahoma_font_path)
                else:
                    page.insert_font(fontname="CustomFont", fontfile=times_font_path)
                
                # Вставляем новый текст с корректировкой позиции
                replacement = specific_replacements[machine_readable]
                vertical_offset = font_size * 0.9  # Вертикальное смещение для точного позиционирования
                page.insert_text(
                    (inst.x0 + EXTRA_LEFT, inst.y0 + vertical_offset),  # Компенсируем смещение влево
                    replacement,
                    fontsize=font_size,
                    fontname="CustomFont",
                    color=(0, 0, 0)
                )
                
                # Отмечаем текст как обработанный
                processed_texts.add(machine_readable)

            # --- Новый проход: замена всех строк из coordinates.json ---
            for coord_text, coord_info in coordinates.items():
                if coord_text in processed_texts:
                    continue
                bbox = coord_info["bbox"]
                font_size = coord_info.get("font_size", 16)
                font_name = coord_info.get("font_name", "Times")
                replacement = coord_info.get("replacement")
                if not replacement:
                    text_type, replacement = determine_text_type(coord_text)
                if not replacement:
                    continue
                safe_name = safe_filename(coord_text)
                patch_path = os.path.join(self.patches_dir, f"patch_{safe_name}.pdf")
                if not os.path.exists(patch_path):
                    text_type, _ = determine_text_type(coord_text)
                    if text_type:
                        patch_path = os.path.join(self.patches_dir, f"patch_{text_type}.pdf")
                if os.path.exists(patch_path):
                    # --- СТАРАЯ ЛОГИКА расчёта patch_rect ---
                    if re.match(r'^[A-Z<]{2,}$', coord_text):
                        patch_rect = fitz.Rect(
                            bbox[0] - EXTRA_LEFT,
                            bbox[1] - EXTRA_TOP,
                            bbox[2] + EXTRA_RIGHT,
                            bbox[3] + EXTRA_BOTTOM
                        )
                    else:
                        patch_rect = fitz.Rect(
                            bbox[0],
                            bbox[1] - font_size * 0.1,
                            bbox[2],
                            bbox[3] + font_size * 0.1
                        )
                    patch_doc = fitz.open(patch_path)
                    patch_page = patch_doc[0]
                    zoom_x = patch_rect.width / patch_page.rect.width
                    zoom_y = patch_rect.height / patch_page.rect.height
                    matrix = fitz.Matrix(zoom_x, zoom_y)
                    page.show_pdf_page(
                        patch_rect,
                        patch_doc,
                        0,
                        matrix,
                        clip=patch_page.rect
                    )
                    patch_doc.close()
                # Вставляем текст
                if "Tahoma" in font_name:
                    page.insert_font(fontname="CustomFont", fontfile=tahoma_font_path)
                    used_font = "CustomFont"
                else:
                    page.insert_font(fontname="CustomFont", fontfile=times_font_path)
                    used_font = "CustomFont"
                page.insert_text(
                    (bbox[0], bbox[1] + font_size * 0.9),  # Увеличили смещение для обычного текста
                    replacement,
                    fontsize=font_size,
                    fontname=used_font,
                    color=(0, 0, 0)
                )
                processed_texts.add(coord_text)
            # --- Конец нового прохода ---

            # Затем обрабатываем остальной текст
            text_blocks = page.get_text("dict")["blocks"]
            
            for block in text_blocks:
                if "lines" not in block:
                    continue
                    
                for line in block["lines"]:
                    for span in line["spans"]:
                        original_text = span["text"]
                        
                        # Пропускаем уже обработанные тексты
                        if original_text in processed_texts:
                            continue
                            
                        font_size = span["size"]
                        font_name = span["font"]
                        x, y = span["origin"]
                        
                        text_type, replacement = determine_text_type(original_text)
                        if replacement:
                            # Определяем путь к патчу
                            safe_name = safe_filename(original_text)
                            patch_path = os.path.join(self.patches_dir, f"patch_{safe_name}.pdf")
                            
                            # Если патч отсутствует, пробуем взять патч по типу текста
                            if not os.path.exists(patch_path) and text_type:
                                patch_path = os.path.join(self.patches_dir, f"patch_{text_type}.pdf")
                            
                            if os.path.exists(patch_path):
                                success = apply_patch(page, patch_path, original_text, x, y, font_size)
                                
                                if success:
                                    if "Tahoma" in font_name:
                                        page.insert_font(fontname="CustomFont", fontfile=tahoma_font_path)
                                        used_font = "CustomFont"
                                    else:
                                        page.insert_font(fontname="CustomFont", fontfile=times_font_path)
                                        used_font = "CustomFont"
                                    
                                    # Вставляем текст
                                    page.insert_text(
                                        (x, y),
                                        replacement,
                                        fontsize=font_size,
                                        fontname=used_font,
                                        color=(0, 0, 0)
                                    )
                                    
                                    # Отмечаем текст как обработанный
                                    processed_texts.add(original_text)
        
        # Сохраняем с оптимизацией
        doc.save(
            output_pdf,
            deflate=True,
            garbage=4,
            clean=True
        )
        doc.close()
        print(f"✅ Готово! PDF с заменами сохранён как: {output_pdf}")

if __name__ == "__main__":
    try:
        print("🔄 Инициализация...")
        
        # Проверяем наличие исходного файла
        if not os.path.exists(pdf_path):
            print(f"❌ Входной файл не найден: {pdf_path}")
            exit(1)
            
        if not os.path.exists("source_pdf_path.pdf"):
            print("❌ Файл с чистым PDF (source_pdf_path.pdf) не найден!")
            exit(1)
            
        # Инициализируем экстрактор патчей
        extractor = PatchExtractor(source_pdf_path="source_pdf_path.pdf")
        
        # Проверяем наличие патчей
        existing_patches = os.listdir(extractor.patches_dir) if os.path.exists(extractor.patches_dir) else []
        required_patches = [f"patch_{text}.pdf" for text in coordinates.keys()]
        missing_patches = [patch for patch in required_patches if patch not in existing_patches]
        
        # Если есть отсутствующие патчи, создаем их
        if missing_patches:
            print(f"ℹ️ Отсутствует {len(missing_patches)} патчей. Создаём...")
            extractor.extract_patches()
        
        print("🔄 Начинаем обработку PDF...")
        
        # Обрабатываем PDF
        extractor.process_pdf(pdf_path, output_pdf)
        
        print(f"✅ Готово! PDF с заменами сохранён как: {output_pdf}")
        
    except Exception as e:
        print(f"❌ Произошла ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
import os
import json
import uuid
import asyncio
import logging
from dotenv import load_dotenv
from pathlib import Path

# Создание необходимых директорий до импорта модулей
os.makedirs('/tmp/logs', exist_ok=True)
os.makedirs('/tmp/uploads', exist_ok=True)
os.makedirs('/tmp/patches', exist_ok=True)

# Aiogram imports
from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ContentType
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Local imports
from pdf_editor import PatchExtractor, coordinates

# Функция для проверки и создания патчей
async def ensure_patches_exist(bot):
    """Проверяет наличие патчей и создает их при необходимости"""
    try:
        from config_loader import Config
        config = Config().get_config()
        
        logger.info("Инициализация PatchExtractor...")
        extractor = PatchExtractor(source_pdf_path=config['paths']['source_pdf'])
        patches_dir = config['paths']['patches_dir']
        
        # Проверяем наличие патчей
        existing_patches = os.listdir(patches_dir) if os.path.exists(patches_dir) else []
        required_patches = [f"patch_{text}.pdf" for text in coordinates.keys()]
        missing_patches = [patch for patch in required_patches if patch not in existing_patches]
        
        if missing_patches:
            logger.info(f"Отсутствует {len(missing_patches)} патчей. Создаём...")
            logger.info(f"Отсутствующие патчи: {', '.join(missing_patches)}")
            extractor.extract_patches()
            
            # Проверяем результат создания
            created_patches = [p for p in missing_patches if os.path.exists(os.path.join(patches_dir, p))]
            failed_patches = [p for p in missing_patches if not os.path.exists(os.path.join(patches_dir, p))]
            
            logger.info(f"Успешно создано патчей: {len(created_patches)}")
            if failed_patches:
                logger.warning(f"Не удалось создать патчи: {', '.join(failed_patches)}")
            
    except Exception as e:
        logger.error(f"Ошибка при создании патчей: {e}")

# Функция для периодического обновления патчей
async def periodic_patches_update(bot):
    """Периодически проверяет и обновляет патчи"""
    while True:
        await ensure_patches_exist(bot)
        # Проверяем каждые 6 часов
        await asyncio.sleep(6 * 60 * 60)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/logs/bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

UPLOAD_DIR = '/tmp/uploads'
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

bot = Bot(token=TOKEN)
dp = Dispatcher()

class PDFData(StatesGroup):
    selecting_fields = State()  # Новое состояние для выбора полей
    waiting_for_input = State()  # Ожидание ввода значения для выбранного поля
    waiting_for_pdf = State()    # Ожидание PDF файла

# Словарь с описанием полей
FIELDS = {
    'name': 'Имя',
    'surname': 'Фамилия',
    'patronymic': 'Отчество',
    'iin': 'ИИН',
    'date': 'Дата рождения',
    'city': 'Город',
    'nationality': 'Национальность',
    'issuer': 'Орган выдачи'
}

def get_fields_keyboard(state_data: dict = None) -> InlineKeyboardMarkup:
    """Создает клавиатуру с полями для изменения, исключая уже измененные поля"""
    builder = InlineKeyboardBuilder()
    
    # Добавляем только неизмененные поля
    for field_id, field_name in FIELDS.items():
        if state_data is None or field_id not in state_data:
            builder.add(InlineKeyboardButton(text=field_name, callback_data=f"field_{field_id}"))
            
    # Добавляем управляющие кнопки
    builder.add(InlineKeyboardButton(text="✅ Готово", callback_data="done"))
    builder.add(InlineKeyboardButton(text="🔄 Начать сначала", callback_data="restart"))
    
    # Размещаем кнопки по 2 в ряд
    builder.adjust(2)
    return builder.as_markup()

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()  # Очищаем предыдущие данные
    await message.answer(
        "Выберите поля, которые хотите изменить:",
        reply_markup=get_fields_keyboard()
    )
    await state.set_state(PDFData.selecting_fields)

@dp.callback_query(lambda c: c.data == "restart", PDFData.selecting_fields)
async def process_restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "Начинаем сначала. Выберите поля, которые хотите изменить:",
        reply_markup=get_fields_keyboard()
    )
    await state.set_state(PDFData.selecting_fields)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('field_'), PDFData.selecting_fields)
async def process_field_selection(callback: types.CallbackQuery, state: FSMContext):
    field_id = callback.data.replace('field_', '')
    field_name = FIELDS[field_id]
    
    # Сохраняем текущее поле
    await state.update_data(current_field=field_id)
    await state.set_state(PDFData.waiting_for_input)
    
    # Запрашиваем значение для выбранного поля
    await callback.message.edit_text(f"Уже изменено: {await get_changed_fields_text(state)}")
    await callback.message.answer(f"Введите {field_name.lower()}:")
    await callback.answer()

async def get_changed_fields_text(state: FSMContext) -> str:
    """Возвращает текст с списком измененных полей"""
    data = await state.get_data()
    changed = []
    for field_id, value in data.items():
        if field_id in FIELDS:
            changed.append(f"✅ {FIELDS[field_id]}: {value}")
    return "\n".join(changed) if changed else "Пока ничего не изменено"

@dp.message(PDFData.waiting_for_input)
async def process_field_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_field = data.get('current_field')
    
    # Специальная проверка для ИИН
    if current_field == 'iin':
        if not message.text or not message.text.isdigit() or len(message.text) != 12:
            await message.answer(
                "❌ Ошибка: ИИН должен содержать ровно 12 цифр.\n\n"
                "ℹ️ Структура ИИН (12 цифр):\n"
                "Первые 6 цифр - это дата рождения:\n"
                "1️⃣2️⃣ - год рождения (последние 2 цифры)\n"
                "3️⃣4️⃣ - месяц рождения (01-12)\n"
                "5️⃣6️⃣ - день рождения (01-31)\n\n"
                "📝 Пример:\n"
                "Для человека, родившегося 15 марта 1990 года:\n"
                "Первые 6 цифр ИИН будут: 900315\n"
                "(90 - год, 03 - март, 15 - день)\n\n"
                "⚠️ Важно: Убедитесь, что вводите правильную дату рождения!\n\n"
                "Пожалуйста, введите ИИН повторно (все 12 цифр):"
            )
            return
            
        # Проверка корректности даты в ИИН
        year = int(message.text[0:2])
        month = int(message.text[2:4])
        day = int(message.text[4:6])
        
        if month < 1 or month > 12 or day < 1 or day > 31:
            await message.answer(
                "❌ Ошибка: Некорректная дата в ИИН!\n\n"
                "ℹ️ В вашем ИИН:\n"
                f"• Первые 2 цифры (год): {year:02d}\n"
                f"• Следующие 2 цифры (месяц): {month:02d} ❌\n"
                f"• Следующие 2 цифры (день): {day:02d} ❌\n\n"
                "📝 Правильный формат:\n"
                "• Год - последние 2 цифры года рождения\n"
                "• Месяц должен быть от 01 до 12\n"
                "• День должен быть от 01 до 31\n\n"
                "Например, для даты рождения 15 марта 1990 года первые 6 цифр ИИН будут: 900315\n\n"
                "⚠️ Пожалуйста, введите ИИН повторно, учитывая правильный формат даты рождения."
            )
            return
    
    # Специальная проверка для даты рождения
    if current_field == 'date':
        import re
        # Проверяем формат дд.мм.гггг
        if not re.match(r'^\d{2}\.\d{2}\.\d{4}$', message.text):
            await message.answer(
                "❌ Ошибка: неверный формат даты!\n\n"
                "📝 Дата должна быть в формате ДД.ММ.ГГГГ\n"
                "Например: 15.03.1990\n\n"
                "⚠️ Пожалуйста, введите дату рождения повторно:"
            )
            return
        
        try:
            day, month, year = map(int, message.text.split('.'))
            # Проверяем корректность даты
            if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
                raise ValueError
        except ValueError:
            await message.answer(
                "❌ Ошибка: некорректная дата!\n\n"
                "• День должен быть от 01 до 31\n"
                "• Месяц должен быть от 01 до 12\n"
                "• Год должен быть от 1900 до 2025\n\n"
                "Пожалуйста, введите дату рождения повторно:"
            )
            return
        text_to_save = message.text  # Сохраняем дату как есть
    else:
        # Преобразуем текст в верхний регистр перед сохранением (кроме ИИН и даты)
        text_to_save = message.text
        if message.text and current_field not in ['iin', 'date']:  # Не преобразовываем ИИН и дату
            text_to_save = message.text.upper()
    
    # Сохраняем значение
    await state.update_data({current_field: text_to_save})
    
    # Получаем обновленные данные для клавиатуры
    updated_data = await state.get_data()
    
    # Показываем список изменённых полей и возвращаемся к выбору полей
    changed_fields = await get_changed_fields_text(state)
    await message.answer(
        f"Изменённые поля:\n{changed_fields}\n\nВыберите следующее поле для изменения или нажмите 'Готово':",
        reply_markup=get_fields_keyboard(updated_data)
    )
    await state.set_state(PDFData.selecting_fields)

@dp.callback_query(lambda c: c.data == "done", PDFData.selecting_fields)
async def process_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Проверяем, были ли выбраны какие-либо поля
    if not any(key in data for key in FIELDS.keys()):
        await callback.message.answer("Вы не выбрали ни одного поля для изменения.")
        return
    
    # Если есть имя и фамилия, генерируем MRZ
    if 'name' in data and 'surname' in data:
        mrz = generate_mrz(data['surname'], data['name'])
        await state.update_data(mrz=mrz)
        await callback.message.answer(f"MRZ строка сгенерирована автоматически:\n{mrz}")
    
    await callback.message.answer("Теперь отправьте PDF-файл для обработки.")
    await state.set_state(PDFData.waiting_for_pdf)
    await callback.answer()

def generate_mrz(surname: str, name: str) -> str:
    """
    Генерирует MRZ строку из фамилии и имени точно в 36 символов.
    """
    # Транслитерация в английские буквы
    def transliterate(text: str) -> str:
        kazakh_russian_to_english = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'iu', 'я': 'ia',
            # Казахские буквы
            'ә': 'a', 'і': 'i', 'ң': 'n', 'ғ': 'g', 'ү': 'u', 'ұ': 'u', 
            'қ': 'k', 'ө': 'o', 'һ': 'h', 'й': 'y'  # изменили 'й' на 'y'
        }
        return ''.join(kazakh_russian_to_english.get(c.lower(), c) for c in text).upper()

    # Транслитерация
    eng_surname = transliterate(surname)
    eng_name = transliterate(name)
    
    # Обрезаем фамилию и имя, если они слишком длинные
    available_space = 36 - 2  # 2 символа для разделителя <<
    max_surname_len = min(len(eng_surname), available_space // 2)
    max_name_len = available_space - max_surname_len
    
    eng_surname = eng_surname[:max_surname_len]
    eng_name = eng_name[:max_name_len]
    
    # Формирование базовой MRZ строки
    mrz = f"{eng_surname}<<{eng_name}"
    
    # Добавляем оставшиеся символы '<' чтобы получить ровно 36 символов
    padding_needed = 36 - len(mrz)
    mrz = mrz + '<' * padding_needed
    
    return mrz  # Теперь гарантированно 36 символов

def get_selected_fields_message(data: dict) -> str:
    """Формирует сообщение с выбранными полями"""
    selected = []
    for field_id, field_name in FIELDS.items():
        if field_id in data:
            selected.append(f"{field_name}: {data[field_id]}")
    if 'mrz' in data:
        selected.append(f"MRZ: {data['mrz']}")
    return "Выбранные поля для изменения:\n" + "\n".join(selected)

@dp.message(PDFData.waiting_for_pdf)
async def handle_pdf(message: types.Message, state: FSMContext):
    """
    Обработчик для загрузки и обработки PDF файла.
    
    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    input_file = None
    output_file = None
    
    # Начальные проверки
    if not message.document:
        await message.answer('Пожалуйста, отправьте PDF-файл.')
        return
        
    if message.document.mime_type != 'application/pdf':
        await message.answer('Файл должен быть в формате PDF.')
        return
        
    if message.document.file_size and message.document.file_size > MAX_FILE_SIZE:
        await message.answer(
            f'Размер файла превышает {MAX_FILE_SIZE // (1024*1024)}MB. '
            f'Пожалуйста, отправьте файл меньшего размера.'
        )
        return
        
    # Проверка наличия исходного PDF и патчей
    source_pdf = "source_pdf_path.pdf"
    if not os.path.exists(source_pdf):
        logger.error(f"Файл {source_pdf} не найден")
        await message.answer('Ошибка конфигурации сервера. Пожалуйста, обратитесь к администратору.')
        return
        
    # Проверяем патчи перед обработкой
    try:
        await ensure_patches_exist(bot)
    except Exception as e:
        logger.error(f"Ошибка при проверке патчей: {e}")
        await message.answer("Произошла ошибка при подготовке к обработке файла. Попробуйте позже.")
        
    # Генерируем уникальные имена для файлов
    unique_id = str(uuid.uuid4())
    input_file = os.path.join(UPLOAD_DIR, f"input_{unique_id}.pdf")
    output_pdf = os.path.join(UPLOAD_DIR, f"output_{unique_id}.pdf")
    output_png = os.path.join(UPLOAD_DIR, f"output_{unique_id}.png")
    
    try:
        # Создаем директорию если её нет
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # Импортируем fitz (PyMuPDF) для конвертации PDF в PNG
        try:
            import fitz
        except ImportError:
            await message.answer("Подождите, устанавливаю необходимые компоненты...")
            await message.answer("Установка PyMuPDF...")
            import subprocess
            subprocess.check_call(["pip", "install", "PyMuPDF"])
            import fitz
        
        # Загружаем файл
        try:
            data = await state.get_data()
            await message.answer('Файл получен. Обрабатываю...')
            await bot.download(message.document, destination=input_file)
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла: {e}")
            await message.answer("Не удалось загрузить файл. Пожалуйста, попробуйте ещё раз.")
            return
            
        # Обрабатываем PDF
        try:
            loop = asyncio.get_event_loop()
            def run_patch_custom():
                extractor = PatchExtractor(source_pdf_path="source_pdf_path.pdf")
                if hasattr(extractor, "process_pdf_custom"):
                    extractor.process_pdf_custom(input_file, output_pdf, data)
                else:
                    extractor.process_pdf(input_file, output_pdf)
                    
                # Конвертируем PDF в PNG
                pdf_document = fitz.open(output_pdf)
                page = pdf_document[0]  # Берем первую страницу
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # Рендерим с разрешением 300 DPI
                pix.save(output_png)
                pdf_document.close()
                    
            await loop.run_in_executor(None, run_patch_custom)
            await message.answer("PDF успешно обработан и конвертирован в PNG")
        except Exception as e:
            logger.error(f"Ошибка при обработке файла: {e}")
            await message.answer("Произошла ошибка при обработке файла. Пожалуйста, убедитесь, что файл корректен.")
            return
            
        # Отправляем результаты
        if os.path.exists(output_pdf) and os.path.exists(output_png):
            try:
                # Отправляем PDF
                pdf_file = FSInputFile(output_pdf)
                await message.answer_document(pdf_file, caption='Ваш документ в PDF формате')
                
                # Отправляем PNG
                png_file = FSInputFile(output_png)
                await message.answer_document(png_file, caption='Ваш документ в PNG формате')
                
                await message.answer("✅ Готово! Отправлены оба формата файла.")
            except Exception as e:
                logger.error(f"Ошибка при отправке файлов: {e}")
                await message.answer("❌ Ошибка при отправке файлов.")
        else:
            logger.error("Выходные файлы не были созданы")
            await message.answer("❌ Ошибка: не удалось создать файлы.")
            
    except FileNotFoundError as e:
        logger.error(f"Файл не найден: {e}")
        await message.answer("Ошибка: один из необходимых файлов не найден.")
    except PermissionError as e:
        logger.error(f"Ошибка доступа: {e}")
        await message.answer("Ошибка доступа к файлам. Пожалуйста, попробуйте позже.")
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}")
        await message.answer("Произошла непредвиденная ошибка при обработке файла.")
    finally:
        # Очищаем временные файлы
        try:
            for file in [input_file, output_pdf, output_png]:
                if file and os.path.exists(file):
                    os.remove(file)
                    logger.debug(f"Удален временный файл: {file}")
        except Exception as e:
            logger.error(f"Ошибка при удалении временных файлов: {e}")
        await state.clear()

async def main():
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)
    
    # Создаем патчи при запуске
    await ensure_patches_exist(bot)
    
    # Запускаем периодическое обновление патчей в фоновом режиме
    asyncio.create_task(periodic_patches_update(bot))
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

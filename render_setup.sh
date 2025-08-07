#!/bin/bash

# Функция для логирования
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "=== Начало настройки ==="

# Вывод текущей директории и списка файлов для диагностики
log "Текущая директория:"
pwd
log "Содержимое корневой директории:"
ls -la

log "Содержимое директории fonts:"
ls -la fonts/ || log "Директория fonts не найдена"

log "Содержимое директории patches:"
ls -la patches/ || log "Директория patches не найдена"

# Проверка наличия необходимых исходных файлов
log "Проверка наличия исходных файлов..."

if [ -f source_pdf_path.pdf ]; then
    log "✓ source_pdf_path.pdf найден"
else
    log "❌ ОШИБКА: source_pdf_path.pdf не найден!"
    exit 1
fi

if [ -d fonts ] && [ -f fonts/tahoma.ttf ] && [ -f fonts/times.ttf ]; then
    log "✓ Шрифты найдены"
else
    log "❌ ОШИБКА: Не найдены необходимые шрифты в директории fonts!"
    ls -la fonts/
    exit 1
fi

# Создание временных директорий
log "Создание временных директорий..."
mkdir -p /tmp/logs && log "✓ Создана директория /tmp/logs"
mkdir -p /tmp/uploads && log "✓ Создана директория /tmp/uploads"
mkdir -p /tmp/patches && log "✓ Создана директория /tmp/patches"

# Копирование патчей
log "Копирование патчей..."
if [ -d patches ]; then
    cp -r patches/* /tmp/patches/ && log "✓ Патчи скопированы"
    log "Содержимое /tmp/patches:"
    ls -la /tmp/patches/
else
    log "❌ ОШИБКА: Директория patches не найдена!"
    exit 1
fi

# Установка прав доступа
log "Установка прав доступа..."
chmod -R 755 /tmp/logs && log "✓ Права установлены для /tmp/logs"
chmod -R 755 /tmp/uploads && log "✓ Права установлены для /tmp/uploads"
chmod -R 755 /tmp/patches && log "✓ Права установлены для /tmp/patches"
chmod -R 755 /tmp/fonts && log "✓ Права установлены для /tmp/fonts"

log "=== Настройка завершена ==="

# Вывод финальной проверки
log "Финальная проверка:"
log "Структура временных директорий:"
ls -la /tmp/logs/ || log "⚠️ /tmp/logs пуст"
ls -la /tmp/uploads/ || log "⚠️ /tmp/uploads пуст"
ls -la /tmp/patches/ || log "⚠️ /tmp/patches пуст"

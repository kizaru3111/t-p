#!/bin/bash

# Создание необходимых директорий
mkdir -p /tmp/logs
mkdir -p /tmp/uploads
mkdir -p /tmp/patches
mkdir -p /tmp/fonts

# Копирование исходных файлов
cp source_pdf_path.pdf /tmp/source_pdf_path.pdf
cp modified.pdf /tmp/modified.pdf 2>/dev/null || :

# Копирование шрифтов
cp fonts/*.ttf /tmp/fonts/

# Копирование патчей
cp -r patches/* /tmp/patches/

# Установка прав доступа
chmod -R 755 /tmp/logs
chmod -R 755 /tmp/uploads
chmod -R 755 /tmp/patches
chmod -R 755 /tmp/fonts

import aiohttp
import glob
import sys
import os
import asyncio
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from pars.DataBaseWb.database import DatabaseManager
from pars.tg_bot.config import BOT_TOKEN, CHANNEL_ID, ADMIN_IDS, PROXY_URL


class TgPostingBot:

    def __init__(self):
        self.bot = None
        self.dp = None
        self._parsing_lock = threading.Lock()

    async def _create_bot(self):
        if PROXY_URL:
            session = AiohttpSession(proxy=PROXY_URL)
            self.bot = Bot(token=BOT_TOKEN, session=session)
            logger.info(f"Прокси: {PROXY_URL}")
        else:
            self.bot = Bot(token=BOT_TOKEN)

        self.dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self):
        # Команды
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(Command("post"))(self.cmd_post)
        self.dp.message(Command("preview"))(self.cmd_preview)
        self.dp.message(Command("tables"))(self.cmd_tables)
        self.dp.message(Command("parsing"))(self.cmd_parsing)
        self.dp.message(Command("images"))(self.cmd_images)


        @self.dp.callback_query(F.data.startswith('img_save_'))
        async def callback_img_save(callback):
            await self._on_save_one_photo(callback)

        @self.dp.callback_query(F.data.startswith('img_all_'))
        async def callback_img_all(callback):
            await self._on_save_all_photos(callback)

        @self.dp.callback_query(F.data == 'img_cancel')
        async def callback_img_cancel(callback):
            await callback.message.answer('Отменено')
            await callback.answer()

        @self.dp.callback_query(F.data.startswith('postphoto_'))
        async def callback_post_photo(callback):
            await self._on_post_with_photo(callback)

        @self.dp.callback_query(F.data == 'post_nophoto')
        async def callback_post_nophoto(callback):
            await self._on_post_without_photo(callback)

        @self.dp.callback_query(F.data == 'post_cancel')
        async def callback_post_cancel(callback):
            await callback.message.answer('❌ Отменено')
            await callback.answer()

    async def cmd_start(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer(
                "<b>ДОСТУП ЗАПРЕЩЁН</b>",
                parse_mode=ParseMode.HTML
            )
            return

        await message.answer(
            "⌨️ <b>Команды:</b>\n\n"
            "/parsing запрос — запустить парсер\n"
            "/post таблица номер — запостить\n"
            "/preview таблица номер — предпросмотр\n"
            "/images таблица номер — скачать фото\n"
            "/tables — список таблиц",
            parse_mode=ParseMode.HTML
        )

    async def cmd_tables(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return

        try:
            with DatabaseManager() as db:
                tables = db.list_tables()

            if not tables:
                await message.answer("Таблиц нет")
                return

            text = f"<b>Таблицы ({len(tables)}):</b>\n\n"

            for i, table in enumerate(tables[:20], 1):
                with DatabaseManager() as db_count:
                    count = db_count.get_count(table)
                text += f"{i}. <code>{table}</code> ({count})\n"

            await message.answer(text, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer(f"Ошибка: {e}")

    async def cmd_images(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer(
                "Формат:\n<code>/images таблица номер</code>",
                parse_mode=ParseMode.HTML
            )
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer(
                f"Не найдено: <code>{table_name}</code> строка {row_num}",
                parse_mode=ParseMode.HTML
            )
            return

        item_id = data.get('id', '-')
        name = data.get('name', 'Без названия')[:50]
        images_str = data.get('images', '')

        await message.answer(
            f"📷 <b>Изображения товара</b>\n\n"
            f"🆔 Артикул: <code>{item_id}</code>\n"
            f"📦 {name}",
            parse_mode=ParseMode.HTML
        )

        if not images_str or images_str.strip() == '':
            await message.answer("<b>В БД нет изображений!</b>", parse_mode=ParseMode.HTML)
            return

        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        if not image_urls:
            await message.answer("<b>Ссылки пустые!</b>", parse_mode=ParseMode.HTML)
            return

        total_count = len(image_urls)

        preview_count = min(5, total_count)

        for i in range(preview_count):
            try:
                caption = f"{i+1}/{total_count}" if i == 0 else f"{i+1}/{total_count}"

                await self.bot.send_photo(
                    chat_id=message.chat.id,
                    photo=image_urls[i],
                    caption=caption
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"Превью {i+1} не загрузилось: {e}")

        buttons = []
        row = []

        max_buttons = min(total_count, 10)

        for i in range(max_buttons):
            row.append(
                InlineKeyboardButton(
                    text=f"📷 {i+1}",
                    callback_data=f"img_save_{table_name}_{row_num}_{item_id}_{i}"
                )
            )

            if len(row) == 5:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        buttons.append([
            InlineKeyboardButton(text="Все фото",
                              callback_data=f"img_all_{table_name}_{row_num}_{item_id}"),
            InlineKeyboardButton(text="Отмена", callback_data="img_cancel")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"<b>Выбери фото:</b>\n\n"
            f"Всего: <b>{total_count}</b> шт\n"
            f"Имя файла: <code>{table_name}_{row_num}_номер.webp</code>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    async def _on_save_one_photo(self, callback):
        data_str = callback.data.replace('img_save_', '')
        all_parts = data_str.split('_')

        if len(all_parts) < 4:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        try:
            img_index = int(all_parts[-1])
            item_id = int(all_parts[-2])
            row_num = int(all_parts[-3])
            table_name = '_'.join(all_parts[:-3])

        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("Товар не найден", show_alert=True)
            return

        images_str = data.get('images', '')
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        if not image_urls or img_index >= len(image_urls):
            await callback.answer("Фото не найдено", show_alert=True)
            return

        url = image_urls[img_index]
        total = len(image_urls)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')
        os.makedirs(save_dir, exist_ok=True)

        filename = f"{table_name}_{row_num}_{img_index + 1}.webp"
        filepath = os.path.join(save_dir, filename)

        await callback.message.answer(f"Скачиваю фото {img_index + 1}...")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content = await response.read()

                        with open(filepath, 'wb') as f:
                            f.write(content)

                        with open(filepath, 'rb') as file:
                            file_data = file.read()

                        photo_buffer = BufferedInputFile(file_data, filename=os.path.basename(filepath))

                        await callback.message.answer_photo(
                            photo=photo_buffer,
                            caption=(
                                f"<b>Сохранено!</b>\n\n"
                                f"<code>{filename}</code>\n"
                                f"Фото: {img_index + 1} / {total}\n"
                                f"Таблица: <code>{table_name}</code>"
                            ),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await callback.message.answer(f"Ошибка HTTP {response.status}")

        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            await callback.message.answer(f"Ошибка: {e}")

        await callback.answer("Готово!")

    async def _on_save_all_photos(self, callback):
        data_str = callback.data.replace('img_all_', '')
        all_parts = data_str.split('_')

        if len(all_parts) < 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        try:
            item_id = int(all_parts[-1])
            row_num = int(all_parts[-2])
            table_name = '_'.join(all_parts[:-2])

        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("Товар не найден", show_alert=True)
            return

        images_str = data.get('images', '')
        image_urls = [img.strip() for img in images_str.split(';') if img.strip()]

        total = len(image_urls)

        await callback.message.answer(f"Скачиваю все {total} фото...")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')
        os.makedirs(save_dir, exist_ok=True)

        saved = 0
        failed = 0

        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(image_urls):

                filename = f"{table_name}_{row_num}_{i + 1}.webp"
                filepath = os.path.join(save_dir, filename)

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            with open(filepath, 'wb') as f:
                                f.write(content)
                            saved += 1
                        else:
                            failed += 1

                except Exception as e:
                    failed += 1

                await asyncio.sleep(0.3)

        await callback.message.answer(
            f"<b>Готово!</b>\n\n"
            f"<code>{table_name}</code>\n"
            f"Папка: <code>maker_images/source_images/</code>\n"
            f"Сохранено: <b>{saved}</b> / {total}\n"
            f"Ошибок: <b>{failed}</b>",
            parse_mode=ParseMode.HTML
        )

        await callback.answer(f"Сохранено {saved} фото!")

    async def cmd_post(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer(
                "Формат:\n<code>/post таблица номер</code>",
                parse_mode=ParseMode.HTML
            )
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer(
                f"Не найдено: <code>{table_name}</code> строка {row_num}",
                parse_mode=ParseMode.HTML
            )
            return

        item_id = data.get('id', '-')
        post_text = self._format_post(data)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')

        available_photos = []

        patterns = [
            f"{table_name}_{row_num}_*.webp",
            f"{item_id}_*.webp",
            "*.webp"
        ]

        for pattern in patterns:
            full_pattern = os.path.join(save_dir, pattern)
            found = glob.glob(full_pattern)

            for f in found:
                is_file = os.path.isfile(f)
                size = os.path.getsize(f) if is_file else 0

                if is_file and size > 0:
                    available_photos.append({
                        'path': f,
                        'name': os.path.basename(f)
                    })

        seen_names = set()
        unique_photos = []

        for p in available_photos:
            if p['name'] not in seen_names:
                seen_names.add(p['name'])
                unique_photos.append(p)

        available_photos = unique_photos[:10]

        if not available_photos:
            try:
                msg = await self.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="+",
                        url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                    )]
                ])

                await message.answer(
                    f"Опубликовано! 📝\n\n"
                    f"<code>{table_name}</code>\n"
                    f"Строка: {row_num}\n\n"
                    f"Фото не найдено!\n"
                    f"Сначала: <code>/images {table_name} {row_num}</code>",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )

            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await message.answer(f"Ошибка: {e}")

            return

        await message.answer(
            f"<b>Выбери фото для поста:</b>\n\n"
            f"Артикул: <code>{item_id}</code>\n"
            f"{data.get('name', '')[:50]}\n\n"
            f"Доступно: <b>{len(available_photos)}</b> шт",
            parse_mode=ParseMode.HTML
        )
        for i, photo in enumerate(available_photos[:3]):
            try:
                with open(photo['path'], 'rb') as file:
                    file_data = file.read()

                from aiogram.types import BufferedInputFile
                photo_buf = BufferedInputFile(file_data, filename=photo['name'])

                caption = f"{i+1}/{len(available_photos)}" if i == 0 else f"{i+1}/{len(available_photos)}"

                await self.bot.send_photo(
                    chat_id=message.chat.id,
                    photo=photo_buf,
                    caption=caption
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"Превью не загрузилось: {e}")

        buttons = []
        row = []

        for i, photo in enumerate(available_photos):
            row.append(
                InlineKeyboardButton(
                    text=f"{i+1}",
                    callback_data=f"postphoto_{table_name}_{row_num}_{item_id}_{i}"
                )
            )

            if len(row) == 5:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        buttons.append([
            InlineKeyboardButton(text="Без фото", callback_data="post_nophoto"),
            InlineKeyboardButton(text="Отмена", callback_data="post_cancel")
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"<b>Выбери фото:</b>\n\n"
            f"Таблица: <code>{table_name}</code>\n"
            f"Строка: {row_num}",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    async def _on_post_with_photo(self, callback):
        data_str = callback.data.replace('postphoto_', '')
        all_parts = data_str.split('_')

        if len(all_parts) < 4:
            await callback.answer("Ошибка", show_alert=True)
            return

        try:
            img_index = int(all_parts[-1])
            item_id = int(all_parts[-2])
            row_num = int(all_parts[-3])
            table_name = '_'.join(all_parts[:-3])

        except (ValueError, IndexError):
            await callback.answer("Ошибка формата", show_alert=True)
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("Товар не найден", show_alert=True)
            return

        post_text = self._format_post(data)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'maker_images', 'source_images')

        photo_path = None
        photos_list = [
            f"{table_name}_{row_num}_*.webp",
            f"{item_id}_*.webp"
        ]

        found_files = []

        for pattern in photos_list:
            found_files.extend(glob.glob(os.path.join(save_dir, pattern)))

        valid_files = [f for f in found_files
                     if os.path.isfile(f) and os.path.getsize(f) > 0
        ]
        valid_files.sort()

        if img_index >= len(valid_files):
            await callback.answer("Фото не найдено", show_alert=True)
            return

        photo_path = valid_files[img_index]
        filename = os.path.basename(photo_path)

        try:
            with open(photo_path, 'rb') as file:
                file_data = file.read()

            photo_buffer = BufferedInputFile(file_data, filename=filename)

            msg = await self.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_buffer,
                caption=post_text,
                parse_mode=ParseMode.HTML
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="+",
                        url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                    ),
                    InlineKeyboardButton(text="🗑️", callback_data=f"del_{msg.message_id}")
                ]
            ])

            await callback.message.answer(
                f"Опубликовано! 📷\n\n"
                f"<code>{filename}</code>\n"
                f"<code>{table_name}</code>\n"
                f"Строка: {row_num}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            await callback.answer("Готово!")

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback.message.answer(f"Ошибка: {e}")

    async def _on_post_without_photo(self, callback):
        data_str = callback.data.replace('post_nophoto_', '')
        parts = data_str.split('_')

        if len(parts) < 2:
            table_name = data_str
            row_num = 1
        else:
            row_num = int(parts[-1])
            table_name = '_'.join(parts[:-1])

        data = self._get_row(table_name, row_num)

        if not data:
            await callback.answer("Товар не найден", show_alert=True)
            return

        post_text = self._format_post(data)

        try:
            msg = await self.bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="+",
                    url=f"https://t.me/{CHANNEL_ID.lstrip('@')}/{msg.message_id}"
                )]
            ])

            await callback.message.answer(
                f"Опубликовано! 📝\n\n"
                f"<code>{table_name}</code>\n"
                f"Строка: {row_num}",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            await callback.answer("Готово!")

        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback.message.answer(f"Ошибка: {e}")

    async def cmd_preview(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return

        args = message.text.split(maxsplit=2)

        if len(args) < 3:
            await message.answer(
                "Формат:\n<code>/preview таблица номер</code>",
                parse_mode=ParseMode.HTML
            )
            return

        table_name = args[1]

        try:
            row_num = int(args[2])
        except ValueError:
            await message.answer("Номер — число!")
            return

        data = self._get_row(table_name, row_num)

        if not data:
            await message.answer("Не найдено")
            return

        post_text = self._format_post(data)

        await message.answer(
            f"<b>PREVIEW</b>\n\n{post_text}",
            parse_mode=ParseMode.HTML
        )

    async def cmd_parsing(self, message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Нет доступа")
            return

        if not self._parsing_lock.acquire(blocking=False):
            await message.answer("⏳ Парсинг уже запущен! Дождись окончания.")
            return

        args = message.text.split(maxsplit=1)

        if len(args) < 2:
            self._parsing_lock.release()
            await message.answer(
                "Формат:\n<code>/parsing запрос</code>",
                parse_mode=ParseMode.HTML
            )
            return

        query = args[1].strip()

        status_msg = await message.answer(
            f"<b>Запускаю парсинг...</b>\n\n"
            f"Запрос: <code>{query}</code>\n\n"
            f"Ожидайте...",
            parse_mode=ParseMode.HTML
        )

        def do_parse():
            try:
                from pars.main import parse

                logger.info(f"Запуск парсинга: {query}")
                result = parse(search_phrase=query)

                return {"success": True, "query": query, "result": result}

            except Exception as e:
                logger.error(f"Ошибка парсинга: {e}")
                return {"success": False, "error": str(e)}

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, do_parse)

        while not future.done():
            await asyncio.sleep(3)

        parsing_result = future.result()
        self._parsing_lock.release()

        if parsing_result.get("success"):
            result_data = parsing_result["result"]

            if result_data and len(result_data) > 0:
                table_name = query.lower().replace(' ', '_').replace('-', '_')

                with DatabaseManager() as db:
                    db_count = db.get_count(table_name)

                await status_msg.edit_text(
                    f"<b>ПАРСИНГ ЗАВЕРШЁН!</b>\n\n"
                    f"Запрос: <code>{query}</code>\n"
                    f"Таблица: <code>{table_name}</code>\n"
                    f"Товаров: <b>{db_count}</b> шт\n\n"
                    f"Постить:\n<code>/post {table_name} 1</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await status_msg.edit_text(
                    f"<b>ПАРСИНГ ЗАВЕРШЁН!</b>\n\n"
                    f"Запрос: <code>{query}</code>\n"
                    f"Товаров: <b>0</b>",
                    parse_mode=ParseMode.HTML
                )
        else:
            error = parsing_result.get("error", "Неизвестная ошибка")
            await status_msg.edit_text(
                f"<b>ОШИБКА ПАРСИНГА</b>\n\n{error[:500]}",
                parse_mode=ParseMode.HTML
            )

    def _get_row(self, table_name: str, row_num: int) -> dict | None:
        try:
            with DatabaseManager() as db:
                rows = db.get_all(table_name, limit=10000)

                if row_num < 1 or row_num > len(rows):
                    return None

                return rows[row_num - 1]

        except Exception as e:
            logger.error(f"Ошибка _get_row: {e}")
            return None

    def _escape_html(self, text: str) -> str:
        if not text:
            return ''
        return (str(text)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))

    def _format_post(self, data: dict) -> str:

        item_id = self._escape_html(data.get('id', '-'))
        name = self._escape_html(data.get('name', 'Без названия'))
        brand = self._escape_html(data.get('brand', '-'))
        price = data.get('price')
        sale_price = data.get('sale_price')
        wb_wallet = data.get('wb_wallet')
        rating = self._escape_html(data.get('rating', '-'))
        quantity = data.get('quantity', 0)
        supplier = self._escape_html(data.get('supplier_name', '-'))
        feedbacks = data.get('feedbacks', 0)
        entity = self._escape_html(data.get('entity', ''))
        link = data.get('link', '#')

        parts = [f"🆔 <b>Артикул: {item_id}</b>"]

        prefix = '🔥' if sale_price else ''
        parts.append(f"\n{prefix} <b>{name}</b>")

        price_lines = []
        if price:
            if sale_price and sale_price != price:
                discount = int(100 - (sale_price / price * 100))
                price_lines.append(
                    f"💰 ~~{int(price):,}~~ → "
                    f"<b>{int(sale_price):,} ₽</b> (-{discount}%)"
                )
                if wb_wallet:
                    price_lines.append(f"🛒 WB кошелёк: <b>{int(wb_wallet):,} ₽</b>")
            else:
                price_lines.append(f"💰 <b>{int(price):,} ₽</b>")

        if price_lines:
            parts.append("\n" + "\n".join(price_lines))

        info = (
            f"\n🏷 Бренд: {brand}"
            f"\n⭐ Рейтинг: {rating} ({feedbacks} отзывов)"
            f"\n📦 В наличии: {quantity} шт"
            f"\n🏪 Продавец: {supplier}"
        )

        if entity:
            info += f"\n📂 Категория: {entity}"

        parts.append(info)

        clean_link = link.replace('\u200B', '')
        parts.append(f"\n\n🔗 <a href=\"{clean_link}\">🛒 ПЕРЕЙТИ НА WILDBERRIES 🛒</a>")

        return "\n".join(parts)

    async def run(self):
        await self._create_bot()

        logger.info("Бот запущен")

        await self.bot.delete_webhook(drop_pending_updates=True)
        await self.dp.start_polling(self.bot)


if __name__ == '__main__':

    bot = TgPostingBot()

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
import asyncio

from loguru import logger

from add_images import add_images
from add_price_wb_wallet import add_price_with_wb_wallet
from get_price_range import WbSearchPhraseParserRange
from get_token import get_token
from DataBaseWb.saver import Items, Saver
from wb_catalog_parser import WbCatalogAsyncFetcher


def parse(search_phrase):
    cookies = {
        'x_wbaas_token': "1.1000.47e3db263f2541b0b5890da8bd1a57fd.MHw3Ny4yMjIuOTYuMTAzfE1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEwLjA7IFdpbjY0OyB4NjQpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xNDcuMC4wLjAgU2FmYXJpLzUzNy4zNnwxNzc4MDA4MzgyfHJldXNhYmxlfDJ8ZXlKb1lYTm9Jam9pSW4wPXwwfDN8MTc3NzQwMzU4Mnwx.MEQCIDLw3aLgjRS3YZvmAv60AvhVeBMIc6AQD+C6Vxip3NziAiAgnjzzs9AJbr53Wm6wjYQfdTqSP+ZBYFLjkJtHiG4zCg==; _wbauid=6072866381776798807",
        '_wbauid': '625729131775405841',
        '_cp': '1',
    }

    logger.info(f"Получаем диапазоны цен для: {search_phrase}")
    price_ranges = WbSearchPhraseParserRange(search_phrase=search_phrase, cookies=cookies).parse()

    if not price_ranges:
        logger.error("Не удалось получить диапазоны цен. Проверь cookies или попробуй позже.")
        return []

    logger.info(f"Диапазоны получены: {price_ranges}")

    fetcher = WbCatalogAsyncFetcher(search_phrase=search_phrase, pages=price_ranges, cookies=cookies)
    results = asyncio.run(fetcher.fetch_all())

    if not results:
        logger.error("Не получены данные из каталога")
        return []

    logger.info("Сырые json получены, перехожу к валидации")

    product_models = []
    for raw_data in results:
        items_info = Items.model_validate(raw_data)
        if items_info.products:
            product_models.extend(items_info.products)

    if not product_models:
        logger.warning("Нет товаров после валидации")
        return []

    logger.info(f"Валидация завершена, товаров: {len(product_models)}")

    logger.info("Добавляем картинки")
    product_models = add_images(product_models)

    logger.info("Добавляем цену с WB-кошельком")
    product_models = add_price_with_wb_wallet(product_models)

    logger.info("Данные добавлены, перехожу к сохранению")

    with Saver(search_phrase) as s:
        count = s.save_many(product_models)
        logger.success(f"✓ Готово! {count} товаров → таблица '{s.table}'")

    return product_models


if __name__ == "__main__":
    parse(search_phrase="Baldy sempai")


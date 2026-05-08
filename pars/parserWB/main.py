import asyncio

from loguru import logger

from add_images import add_images
from add_price_wb_wallet import add_price_with_wb_wallet
from get_price_range import WbSearchPhraseParserRange
from get_token import get_token
from DataBaseWb.saver import Items, AsyncSaver
from wb_catalog_parser import WbCatalogAsyncFetcher


async def parse(search_phrase):
    cookies = {
        'x_wbaas_token': "1.1000.5e39f0cede474d3e98e89a9cdafc87bc.MHw3Ny4yMjIuOTYuMTAzfE1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEwLjA7IFdpbjY0OyB4NjQpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xNDcuMC4wLjAgU2FmYXJpLzUzNy4zNiBFZGcvMTQ3LjAuMC4wfDE3Nzk0NDcyMTN8cmV1c2FibGV8MnxleUpvWVhOb0lqb2lJbjA9fDB8M3wxNzc4ODQyNDEzfDE=.MEUCIF0Se5GFua9G/Vmr7s8SYDK+dcovPHs/mrC0LKRtj7LxAiEAhsUX6qeKq+TCXtbR2dLfDQTXxYoNAIqPBx+wwKAckqE=",
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
    results = await fetcher.fetch_all()

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

    async with AsyncSaver(search_phrase) as s:
        count = await s.save_many(product_models)
        logger.success(f"✓ Готово! {count} товаров → таблица '{s.table}'")

    return product_models


if __name__ == "__main__":
    asyncio.run(parse(search_phrase="Предтрен reqfull"), loop_factory=asyncio.SelectorEventLoop)
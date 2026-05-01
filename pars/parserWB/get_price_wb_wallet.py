import requests
from decimal import Decimal, ROUND_FLOOR
from loguru import logger


DEFAULT_PAYMENT_URL = (
    "https://static-basket-01.wbbasket.ru/vol1/global-payment/default-payment.json"
)
SETTINGS_URL = (
    "https://static-basket-01.wbbasket.ru/vol0/data/settings-front.json"
)


def get_wallet_discount_percent() -> Decimal:
    logger.info(
        "WB Wallet: получаем процент скидки для типа «Незалогиненный кошелёк»"
    )

    try:
        resp = requests.get(DEFAULT_PAYMENT_URL, timeout=5)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        logger.exception(
            "WB Wallet: ошибка при получении default-payment.json"
        )
        return Decimal("0")

    logger.debug(
        "WB Wallet: ответ default-payment.json → {}",
        payload
    )

    if payload.get("state") != 0:
        logger.warning(
            "WB Wallet: state={} → скидка не применяется",
            payload.get("state")
        )
        return Decimal("0")

    for item in payload.get("data", []):
        logger.debug(
            "WB Wallet: проверяем тип оплаты → {} (active={}, discount={}%)",
            item.get("wc_type"),
            item.get("is_active"),
            item.get("discount_value"),
        )

        if (
            item.get("wc_type") == "Незалогиненный кошелёк"
            and item.get("is_active") is True
        ):
            try:
                discount = Decimal(item["discount_value"])
            except Exception:
                logger.warning(
                    "WB Wallet: некорректное discount_value → {}",
                    item.get("discount_value")
                )
                return Decimal("0")

            logger.success(
                "WB Wallet: найдена скидка для «Незалогиненный кошелёк» → {}%",
                discount
            )
            return discount

    logger.warning(
        "WB Wallet: скидка для «Незалогиненный кошелёк» не найдена → не применяем"
    )
    return Decimal("0")


def get_discount_settings() -> tuple[Decimal, Decimal]:
    logger.info("WB Wallet: получаем настройки скидок (settings-front.json)")

    try:
        resp = requests.get(SETTINGS_URL, timeout=5)
        resp.raise_for_status()
        settings = resp.json().get("variables")
    except Exception:
        logger.exception("WB Wallet: ошибка при получении settings-front.json")
        return Decimal("0"), Decimal("0")

    logger.debug("WB Wallet: settings-front.json → {}", settings)

    try:
        max_price = Decimal(settings.get("wlt1DiscountDisplayMaxPrice", 0))
        min_delta = Decimal(settings.get("pricesDeltaToShowSale", 0))
    except Exception:
        logger.exception("WB Wallet: ошибка парсинга настроек скидок")
        return Decimal("0"), Decimal("0")

    return max_price, min_delta


def calc_price_with_wb_wallet(price: int | float | Decimal,
                              discount_percent: int | float | Decimal,
                              max_price: int | float | Decimal) -> int:

    price = Decimal(price)

    if max_price and price > max_price:
        return int(price)

    discounted_price = (
        price * (Decimal("100") - discount_percent) / Decimal("100")
    ).quantize(Decimal("1"), rounding=ROUND_FLOOR)


    return int(discounted_price)



from pydantic import BaseModel, model_validator
from typing import Optional
from loguru import logger

from .database import DatabaseManager

class Price(BaseModel):
    basic: Optional[float] = None
    product: Optional[float] = None


class Size(BaseModel):
    price: Optional[Price] = None


class Item(BaseModel):
    id: int
    name: str
    salePriceU: Optional[float] = None
    priceU: Optional[float] = None
    wb_wallet: Optional[float] = None
    brand: str
    sale: Optional[int] = None
    rating: int
    volume: int
    supplier: str = None
    supplierId: int
    supplierRating: Optional[float] = None
    totalQuantity: int
    nmReviewRating: Optional[float]
    nmFeedbacks: Optional[int]
    pics: int
    image_links: Optional[str] = None
    root: int
    feedback_count: Optional[int] = None
    valuation: Optional[str] = None
    description: Optional[str] = None
    characteristics: Optional[str] = None
    sizes: Optional[list[Size]] = None
    subj_root_name: Optional[str] = None
    subj_name: Optional[str] = None
    entity: Optional[str] = None

    @model_validator(mode="after")
    def fill_price_from_sizes(self):
        if self.sizes and len(self.sizes) > 0:
            size = self.sizes[0]
            if size.price:
                if self.priceU is None and size.price.basic is not None:
                    self.priceU = float(size.price.basic) / 100
                if self.salePriceU is None and size.price.product is not None:
                    self.salePriceU = float(size.price.product) / 100
        return self


class Items(BaseModel):
    products: list[Item]


class Saver:
    def __init__(self, query: str):
        self.query = query
        self.db = DatabaseManager()
        self.table_name = None

    def __enter__(self):
        self.db.connect()
        self.table_name = self.db.create_table(self.query)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def save(self, item: Item) -> bool:
        if not self.table_name:
            logger.error("Таблица не создана")
            return False
        return self.db.insert_product(self.table_name, item)

    def save_many(self, items: list[Item]) -> int:
        if not self.table_name:
            logger.error("Таблица не создана")
            return 0

        seen_ids = set()
        unique_items = []

        for item in items:
            if not item or item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            unique_items.append(item)

        if not unique_items:
            return 0

        return self.db.insert_many(self.table_name, unique_items)

    @property
    def count(self) -> int:
        if not self.table_name:
            return 0
        return self.db.get_count(self.table_name)

    @property
    def table(self) -> str | None:
        return self.table_name



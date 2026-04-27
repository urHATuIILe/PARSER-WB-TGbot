from dataclasses import dataclass


@dataclass
class DataPage:
    min_price: int
    max_price: int
    total: int
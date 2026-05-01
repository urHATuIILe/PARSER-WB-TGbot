
# актуализировать можно из источника https://cdn.wbbasket.ru/api/v3/upstreams

from bisect import bisect

BASKET_ENDS = [
    143, 287, 431, 719, 1007, 1061, 1115, 1169, 1313, 1601,
    1655, 1919, 2045, 2189, 2405, 2621, 2837, 3053, 3269, 3485,
    3701, 3917, 4133, 4349, 4565, 4877, 5189, 5501, 5813, 6125,
    6437, 6749, 7061, 7373, 7685, 7997, 8309, 8741, 9173, 9605
]

def calc_numb_basket(short_id: int) -> str:
    basket = bisect(BASKET_ENDS, short_id) + 1
    return f"{basket:02d}"


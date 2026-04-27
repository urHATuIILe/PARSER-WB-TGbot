from dataclasses import dataclass
from common_data import headers

from dto import DataPage

import requests
from loguru import logger
import json


cookies = {
    'x_wbaas_token': '_wbauid=625729131775405841; _cp=1; x_wbaas_token=1.1000.ef12fb695b4f4e81b77ea905af166c6f.MHw3Ny4yMjIuOTYuMTAzfE1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEwLjA7IFdpbjY0OyB4NjQpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xNDcuMC4wLjAgU2FmYXJpLzUzNy4zNiBFZGcvMTQ3LjAuMC4wfDE3Nzc5MjYyNDR8cmV1c2FibGV8MnxleUpvWVhOb0lqb2lJbjA9fDB8M3wxNzc3MzIxNDQ0fDE=.MEUCIDmFhIvh4xdi3Xo8/c3sLKxvgMNQ8tXFrYtyC/RF5FxBAiEAw0uyEX3EXl+oA4WmpdxGDKdxN4pbvMH58k4T/ggAhJA=',
    '_wbauid': '625729131775405841',
    '_cp': '1',
}


class WbSearchPhraseParserRange:
    
    def __init__(self, search_phrase: str, cookies: dict = None):
        self.search_phrase = search_phrase
        self.cookies = cookies
        
        self.default_step = 5000 * 100
        self.max_count_of_good = 5000
        
        self.min_step = 10 * 100
        self.max_step = 50000 * 100
        
        self.max_split_depth = 10
        self.low_goods_threshold = 500
        
        
    def fetch_data(self, add_params: dict = None):
        params = {
            'ab_online_reranking': 'seara',
            'appType': '1',
            'autoselectFilters': 'false',
            'curr': 'rub',
            'dest': '-1581744',
            'hide_vflags': '4294967296',
            'inheritFilters': 'false',
            'lang': 'ru',
            'query': self.search_phrase,
            'resultset': 'filters',
            'scale': '3',
            'spp': '30',
            'suppressSpellcheck': 'false',
        } 
        if add_params:
            params.update(add_params)
            logger.debug(add_params)
        
        response = requests.get(
            'https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search',
            params=params,
            cookies=self.cookies,
            headers=headers,
        )
        
        if response.status_code == 200:
            return response.json()   
        logger.error(f"WB status: {response.status_code}")
        return None
    
    @staticmethod
    def _get_total(data: json):
        return data.get("data", {}).get("total")
    
    @staticmethod
    def _get_min_max_price(data: json)-> tuple:
        filters = data.get("data",{}).get("filters", [])
        
        for _filter in filters:
            if _filter.get("name") == "Цена":
                return _filter.get("minPriceU"), _filter.get("maxPriceU")
        return None, None
    
    def get_price_range(self, data: json)-> DataPage | None:
        if not data:
            return
        
        total = self._get_total(data=data)
        min_price, max_price = self._get_min_max_price(data)
        
        if not all([total, min_price, max_price]):
            return None
        
        return DataPage(min_price=min_price, max_price=max_price, total=total)
    
    def split_price_range(self, min_price, max_price, depth=0)-> list[DataPage]:
        if depth > self.max_split_depth:
            logger.warning("Превышена глубина дробления")
            return []
        
        if max_price - min_price <= self.min_step:
            logger.warning("Минимальный шаг достигнут")
            res = self.fetch_data(add_params={"priceU": f"{min_price};{max_price}"})
            data = self.get_price_range(res)
            
            return [DataPage(min_price, max_price, data.total) if data else 0]
        
        res = self.fetch_data(add_params={"priceU": f"{min_price};{max_price}"})
        data = self.get_price_range(res)
        
        if not data:
            logger.error("Нет данных")
            return []
        
        if data.total <= self.max_count_of_good:
            logger.info(f"ok - {data.total}")
            return [DataPage(min_price, max_price, data.total)]
        
        logger.warning(f"Дробим - {data.total}")
        
        mid = (min_price + max_price) // 2
        left = self.split_price_range(min_price=min_price, max_price=mid, depth=depth + 1)
        right = self.split_price_range(min_price=mid + 1, max_price=max_price, depth=depth + 1)
        
        return left + right
        
    
    def parse(self):
        logger.info(f"Начинаем парсинг <{self.search_phrase}>")
        
        base_data = self.get_price_range(data=self.fetch_data())
        if not base_data:   
            logger.error("Не удалось получить данные")
            return
        
        result: list[DataPage] = []
        
        step = self.default_step
        
        start_price = base_data.min_price
        
        while start_price < base_data.max_price:
            finish_price = min(start_price + step, base_data.max_price)
            
            logger.info(f"Диапазон: {start_price / 100} - {finish_price / 100}. Шаг {step / 100}")
            
            res = self.fetch_data(
                add_params={"priceU": f"{start_price};{finish_price}"}
            )
            data = self.get_price_range(data=res)
            
            if not data:
                logger.warning("Нет данных")
                start_price = finish_price
                
                step = self.max_step
                continue
            
            if data.total > self.max_count_of_good:
                logger.warning(f"{data.total} - дробим диапазон")
                
                sub_ranges = self.split_price_range(start_price, finish_price)
                result.extend(sub_ranges)
                
                start_price = finish_price
                step = self.default_step
                continue
            
            if data.total < self.low_goods_threshold:
                logger.info("Мало товаров")
                step = self.max_step
                
            else:
                step = self.default_step
                
            logger.info(f"Принят диапазон: {data.total}")
            result.append(DataPage(start_price, finish_price, data.total))
            start_price = finish_price
            
        logger.info(f"Получилось {len(result)} диапазонов") 
        logger.info(result[1:5])
        return result
    
    
if __name__ == "__main__":
     
    WbSearchPhraseParserRange(search_phrase="носки", cookies=cookies).parse()           
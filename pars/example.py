import requests

cookies = {
    'x_wbaas_token': '1.1000.5be5eb25b4d54f5cbca8c7e7394c9efc.MHw3Ny4yMjIuOTYuMTAzfE1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEwLjA7IFdpbjY0OyB4NjQpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xNDYuMC4wLjAgU2FmYXJpLzUzNy4zNiBFZGcvMTQ2LjAuMC4wfDE3NzY2MTU0MzZ8cmV1c2FibGV8MnxleUpvWVhOb0lqb2lJbjA9fDB8M3wxNzc2MDEwNjM2fDE=.MEUCICbiUh0zfnsrWL2cbWWvV/NHbsAYf1TlptC96jE0Jb/jAiEAzz0lafE9LwCwz2nc3NCcQZorJZO6MTQ6Kir5sqYX2vg=',
    '_wbauid': '625729131775405841',
    '_cp': '1',
}

params = {
    'ab_online_reranking': 'seara',
    'appType': '1',
    'curr': 'rub',
    'dest': '-1581744',
    'hide_vflags': '4294967296',
    'inheritFilters': 'false',
    'lang': 'ru',
    'query': 'кроссовки мужские',
    'resultset': 'catalog',
    'sort': 'popular',
    'spp': '30',
    'suppressSpellcheck': 'false',
}

response = requests.get(
    'https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search',
    params=params,
    cookies=cookies,
    headers=headers,
)

print(response.status_code)
#print(response.json())
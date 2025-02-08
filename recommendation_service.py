import logging
import pandas as pd
from fastapi import FastAPI
from contextlib import asynccontextmanager
import requests

logger = logging.getLogger("uvicorn.error")

class Recommendations:

    def __init__(self):

        self._recs = {"personal": None, "default": None}
        self._stats = {
            "request_personal_count": 0,
            "request_default_count": 0,
        }

    def load(self, type, path, **kwargs):
        """
        Загружает рекомендации из файла
        """

        logger.info(f"Loading recommendations, type: {type}")
        self._recs[type] = pd.read_parquet(path, **kwargs)
        if type == "personal":
            self._recs[type] = self._recs[type].set_index("user_id")
        logger.info(f"Loaded")

    def get(self, user_id: int, k: int=100):
        """
        Возвращает список рекомендаций для пользователя
        """
        try:
            recs = self._recs["personal"].loc[user_id]
            recs = recs["item_id"].to_list()[:k]
            self._stats["request_personal_count"] += 1
        except KeyError:
            recs = self._recs["default"]
            recs = recs["item_id"].to_list()[:k]
            self._stats["request_default_count"] += 1
        except:
            logger.error("No recommendations found")
            recs = []

        return recs

    def stats(self):

        logger.info("Stats for recommendations")
        for name, value in self._stats.items():
            logger.info(f"{name:<30} {value} ")

rec_store = Recommendations()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # код ниже (до yield) выполнится только один раз при запуске сервиса
    logger.info("Starting")

    rec_store.load(
        "personal",
        path='final_recommendations_feat.parquet',
        columns=["user_id", "item_id", "rank"],
    )

    rec_store.load(
        "default",
        path='top_recs.parquet',
        columns=["item_id", "rank"],
    )

    yield 

    # этот код выполнится только один раз при остановке сервиса
    logger.info("Stopping")

    rec_store.stats()
    
# создаём приложение FastAPI
app = FastAPI(title="recommendations", lifespan=lifespan)


@app.post("/recommendations")
async def recommendations(user_id: int, k: int = 100):
    """
    Возвращает список рекомендаций длиной k для пользователя user_id
    """

    recs = rec_store.get(user_id, k)

    return {"recs": recs}

_ = '''
@app.post("/recommendations_online")
async def recommendations_online(user_id: int, k: int = 100):
    """
    Возвращает список онлайн-рекомендаций длиной k для пользователя user_id
    """

    headers = {"Content-type": "application/json", "Accept": "text/plain"}

    features_store_url = "http://127.0.0.1:8010"
    events_store_url = "http://127.0.0.1:8020"

    # получаем последнее событие пользователя
    params = {"user_id": user_id, "k": 1}
    resp = requests.post(events_store_url + "/get", headers=headers, params=params)
    events = resp.json()
    events = events["events"]

    # получаем список похожих объектов
    if len(events) > 0:
        item_id = events[0]
        params = {"item_id": item_id, "k": k}
        # ваш код здесь
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        resp = requests.post(features_store_url +"/similar_items", headers=headers, params=params)
        if resp.status_code == 200:
            item_similar_items = resp.json()
            #print(type(item_similar_items))
            #print(item_similar_items)
            item_similar_items = item_similar_items['item_id_2']
        else:
            item_similar_items = None
            print(f"status code: {resp.status_code}")

        recs = item_similar_items[:k]
    else:
        recs = []

    return {"recs": recs}    
'''
    
def dedup_ids(ids):
    """
    Дедублицирует список идентификаторов, оставляя только первое вхождение
    """
    seen = set()
    ids = [id for id in ids if not (id in seen or seen.add(id))]

    return ids

@app.post("/recommendations_online")
async def recommendations_online(user_id: int, k: int = 100):
    """
    Возвращает список онлайн-рекомендаций длиной k для пользователя user_id
    """
    features_store_url = "http://127.0.0.1:8010"
    events_store_url = "http://127.0.0.1:8020"

    headers = {"Content-type": "application/json", "Accept": "text/plain"}

    # получаем список последних событий пользователя, возьмём три последних
    params = {"user_id": user_id, "k": 3}
    # ваш код здесь
    resp = requests.post(events_store_url + "/get", 
                        headers=headers, 
                        params=params)

    if resp.status_code == 200:
        events = resp.json()['events']

    # получаем список айтемов, похожих на последние три, с которыми взаимодействовал пользователь
    items = []
    scores = []
    for item_id in events:
        # для каждого item_id получаем список похожих в item_similar_items
        # ваш код здесь
        params = {"item_id": item_id, "k": 3}
        resp = requests.post(features_store_url +"/similar_items", headers=headers, params=params)
        if resp.status_code == 200:
            item_similar_items = resp.json()
        else:
            item_similar_items = None
            print(f"status code: {resp.status_code}")

        items += item_similar_items["item_id_2"]
        scores += item_similar_items["score"]
    # сортируем похожие объекты по scores в убывающем порядке
    # для старта это приемлемый подход
    combined = list(zip(items, scores))
    combined = sorted(combined, key=lambda x: x[1], reverse=True)
    combined = [item for item, _ in combined]

    # удаляем дубликаты, чтобы не выдавать одинаковые рекомендации
    recs = dedup_ids(combined)[:k]

    return {"recs": recs}
    

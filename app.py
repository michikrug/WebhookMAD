import logging
import os
import queue
import requests
from datetime import datetime, timezone
from queue import Queue
from threading import Thread
from typing import Dict, List, Optional, Tuple

from flask import Flask, Response, request
from mysql.connector import Error, errorcode
from mysql.connector.pooling import MySQLConnectionPool

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db_config = {
    'user': os.getenv('DB_USER', 'user'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'database'),
    'raise_on_warnings': True,
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'secret')

pool: Optional[MySQLConnectionPool] = None
query_queue = Queue(maxsize=1000)

query = (
    "INSERT INTO pokemon (id, pokestop_id, spawn_id, lat, lon, weight, height, size, "
    "expire_timestamp, updated, pokemon_id, move_1, move_2, gender, "
    "cp, atk_iv, def_iv, sta_iv, form, level, "
    "weather, costume, first_seen_timestamp, changed, "
    "expire_timestamp_verified, display_pokemon_id, seen_type, "
    "shiny, capture_1, capture_2, capture_3, is_event, iv "
    ") VALUES ("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
    ") ON DUPLICATE KEY UPDATE "
    "pokestop_id=VALUES(pokestop_id), spawn_id=VALUES(spawn_id), lat=VALUES(lat), "
    "lon=VALUES(lon), weight=VALUES(weight), height=VALUES(height), size=VALUES(size), "
    "expire_timestamp=VALUES(expire_timestamp), updated=VALUES(updated), pokemon_id=VALUES(pokemon_id), "
    "move_1=VALUES(move_1), move_2=VALUES(move_2), gender=VALUES(gender), cp=VALUES(cp), "
    "atk_iv=VALUES(atk_iv), def_iv=VALUES(def_iv), sta_iv=VALUES(sta_iv), "
    "form=VALUES(form), level=VALUES(level), weather=VALUES(weather), "
    "costume=VALUES(costume), first_seen_timestamp=VALUES(first_seen_timestamp), changed=VALUES(changed), "
    "expire_timestamp_verified=VALUES(expire_timestamp_verified), "
    "display_pokemon_id=VALUES(display_pokemon_id), seen_type=VALUES(seen_type), "
    "shiny=VALUES(shiny), capture_1=VALUES(capture_1), capture_2=VALUES(capture_2), "
    "capture_3=VALUES(capture_3), is_event=VALUES(is_event), iv=VALUES(iv)"
)


def init_db_pool() -> None:
    global pool
    try:
        pool = MySQLConnectionPool(pool_name="mypool", pool_size=3, **db_config)
        logger.info("Database pool initialized successfully.")
    except Error as err:
        error_message = "Unknown error"
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            error_message = "Invalid database credentials"
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            error_message = "Database does not exist"
        logger.error(f"Database initialization error: {error_message}")
        raise

def get_db_connection():
    global pool
    if pool is None:
        init_db_pool()

    try:
        return pool.get_connection()
    except Error as e:
        logger.error(f"Error getting connection from pool: {e}")
        pool = None
        raise

def send_to_pokealarm(data: List[Dict]) -> None:
    url = 'http://pokealarm:4000'
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to send data to PokeAlarm: {response.status_code} {response.text}")

@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret: str) -> Tuple[str | Response, int]:
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid webhook secret attempted: {secret}")
        return 'Invalid request', 403

    try:
        data = request.json
        parse_data(data)
        send_to_pokealarm(data)
        return 'Success', 200
    except Error as err:
        logger.error(f"Database error processing webhook: {err}")
        return 'Internal server error', 500
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}")
        return 'Internal server error', 500

def parse_data(data: List[Dict]) -> None:
    mon_args = []

    for message in data:
        if message.get("type") != "pokemon":
            continue

        mon = message.get("message")
        if not mon or not mon.get("spawnpoint_id"):
            continue

        try:
            spawnpoint_id = int(str(mon.get("spawnpoint_id", "0")), 16)
            current_time = int(datetime.now(timezone.utc).timestamp())

            mon_args.append((
                mon.get("encounter_id"),
                mon.get("pokestop_id"),
                spawnpoint_id,
                mon.get("latitude"),
                mon.get("longitude"),
                mon.get("weight"),
                mon.get("height"), 
                mon.get("size"),
                mon.get("disappear_time"),
                current_time,
                mon.get("pokemon_id"),
                mon.get("move_1"),
                mon.get("move_2"),
                mon.get("gender"),
                mon.get("cp"),
                mon.get("individual_attack"),
                mon.get("individual_defense"),
                mon.get("individual_stamina"),
                mon.get("form"),
                mon.get("pokemon_level"),
                mon.get("weather"),
                mon.get("costume"),
                mon.get("first_seen"),
                current_time,
                mon.get("disappear_time_verified"),
                mon.get("display_pokemon_id"),
                mon.get("seen_type"),
                mon.get("shiny"),
                mon.get("capture_1"),
                mon.get("capture_2"),
                mon.get("capture_3"),
                mon.get("is_event"),
                round((int(mon.get("individual_attack", 0)) + int(mon.get("individual_defense", 0)) + int(mon.get("individual_stamina", 0))) / 45 * 100, 2)
            ))

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing pokemon data: {e}")
            continue

    if mon_args:
        try:
            query_queue.put(mon_args, timeout=5)
            logger.info(f"Queued batch of {len(mon_args)} records")
        except queue.Full:
            logger.error("Queue is full, dropping batch")
        except Exception as e:
            logger.error(f"Error queuing query: {e}")

def query_worker() -> None:
    while True:
        try:
            args = query_queue.get(timeout=30)
            conn = None
            cursor = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.executemany(query, args)
                conn.commit()
                logger.info(f"Processed batch of {len(args)} records")
            except Error as err:
                logger.error(f"Database error in worker: {err}")
                if conn:
                    conn.rollback()
            except Exception as e:
                logger.error(f"Unexpected error in worker: {e}")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
                query_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Worker thread error: {e}")

if __name__ == '__main__':
    init_db_pool()
    worker = Thread(target=query_worker, daemon=True)
    worker.start()
    app.run(host='0.0.0.0', port=8000)

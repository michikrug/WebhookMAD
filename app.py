import logging
import os
import queue
import random
import time
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
    "INSERT INTO pokemon (encounter_id, spawnpoint_id, pokemon_id, latitude, longitude, disappear_time, "
    "individual_attack, individual_defense, individual_stamina, move_1, move_2, cp, cp_multiplier, "
    "weight, height, gender, catch_prob_1, catch_prob_2, catch_prob_3, rating_attack, rating_defense, "
    "weather_boosted_condition, last_modified, costume, form, size, seen_type"
    ") VALUES ("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
    ") ON DUPLICATE KEY UPDATE "
    "last_modified=VALUES(last_modified), disappear_time=VALUES(disappear_time), "
    "individual_attack=VALUES(individual_attack), individual_defense=VALUES(individual_defense), "
    "individual_stamina=VALUES(individual_stamina), move_1=VALUES(move_1), move_2=VALUES(move_2), "
    "cp=VALUES(cp), cp_multiplier=VALUES(cp_multiplier), weight=VALUES(weight), height=VALUES(height), "
    "gender=VALUES(gender), catch_prob_1=VALUES(catch_prob_1), catch_prob_2=VALUES(catch_prob_2), "
    "catch_prob_3=VALUES(catch_prob_3), rating_attack=VALUES(rating_attack), "
    "rating_defense=VALUES(rating_defense), weather_boosted_condition=VALUES(weather_boosted_condition), "
    "costume=VALUES(costume), form=VALUES(form), size=VALUES(size), pokemon_id=VALUES(pokemon_id), latitude=VALUES(latitude), "
    "longitude=VALUES(longitude), spawnpoint_id=VALUES(spawnpoint_id), seen_type=VALUES(seen_type)"
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

@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret: str) -> Tuple[str | Response, int]:
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Invalid webhook secret attempted: {secret}")
        return 'Invalid request', 403

    try:
        parse_data(request.json)
        return 'Success', 200
    except Error as err:
        logger.error(f"Database error processing webhook: {err}")
        return 'Internal server error', 500
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}")
        return 'Internal server error', 500

def calculate_mon_level(cp_multiplier: float) -> float:
    if cp_multiplier < 0.734:
        pokemon_level = 58.35178527 * cp_multiplier * \
            cp_multiplier - 2.838007664 * cp_multiplier + 0.8539209906
    else:
        pokemon_level = 171.0112688 * cp_multiplier - 95.20425243
    return round(pokemon_level * 2) / 2

def calculate_cp_multiplier(target_pokemon_level: float) -> Optional[float]:
    cp_multiplier = 0.4
    for _ in range(100):  # Limit iterations to avoid infinite loops
        pokemon_level = calculate_mon_level(cp_multiplier)
        if pokemon_level == target_pokemon_level:
            return round(cp_multiplier, 6)
        elif pokemon_level > target_pokemon_level:
            cp_multiplier -= random.randrange(1, 100) / 1000
        else:
            cp_multiplier += random.randrange(1, 100) / 1000
    return None  # No solution found within tolerance

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
            disappear_time = datetime.fromtimestamp(mon.get("disappear_time", time.time()), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            cp_multiplier = calculate_cp_multiplier(mon.get("pokemon_level", 0))

            mon_args.append((
                mon.get("encounter_id"),
                spawnpoint_id,
                mon.get("pokemon_id"),
                mon.get("latitude"),
                mon.get("longitude"),
                disappear_time,
                mon.get("individual_attack"),
                mon.get("individual_defense"), 
                mon.get("individual_stamina"),
                mon.get("move_1"),
                mon.get("move_2"),
                mon.get("cp"),
                cp_multiplier,
                mon.get("weight"),
                mon.get("height"), 
                mon.get("gender"),
                mon.get("base_catch") or mon.get("capture_1"),
                mon.get("great_catch") or mon.get("capture_2"),
                mon.get("ultra_catch") or mon.get("capture_3"),
                None,  # rating_attack
                None,  # rating_defense
                mon.get("boosted_weather") or mon.get("weather"),
                current_time,
                mon.get("costume"),
                mon.get("form"),
                mon.get("size"),
                "encounter"
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

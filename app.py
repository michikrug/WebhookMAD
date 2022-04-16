import logging
import time
from datetime import datetime

import mysql.connector
from flask import Flask, request
from mysql.connector import errorcode

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

db_config = {
    'user': 'user',
    'password': 'password',
    'host': 'localhost',
    'database': 'database',
    'raise_on_warnings': True
}

app = Flask(__name__)

conn = None


def connect_db():
    global conn
    try:
        conn = mysql.connector.connect(**db_config)
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            logging.error("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            logging.error("Database does not exist")
        else:
            logging.error(err)

        exit(1)


@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret: str):
    if secret != 'secret':
        return 'Invalid request', 403
    if request.method == 'POST':
        parse_data(request.json)
        return 'OK', 200


def parse_data(data: dict):
    mon_args = []
    now = datetime.utcfromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")

    for messages in data:
        if messages.get("type") == "pokemon":
            mon = messages.get("message", None)
            if mon is None or mon.get("spawnpoint_id", 0) == 0:
                continue

            mon_args.append(
                (
                    mon.get("encounter_id", None),
                    mon.get("spawnpoint_id", None),
                    mon.get("pokemon_id", None),
                    mon.get("latitude", None),
                    mon.get("longitude", None),
                    datetime.utcfromtimestamp(
                        mon.get("disappear_time", time.time())).strftime("%Y-%m-%d %H:%M:%S"),
                    mon.get("individual_attack", None),
                    mon.get("individual_defense", None),
                    mon.get("individual_stamina", None),
                    mon.get("move_1", None),
                    mon.get("move_2", None),
                    mon.get("cp", None),
                    mon.get("cp_multiplier", None),
                    mon.get("weight", None),
                    mon.get("height", None),
                    mon.get("gender", None),
                    mon.get("base_catch", None),
                    mon.get("great_catch", None),
                    mon.get("ultra_catch", None),
                    None,
                    None,
                    mon.get("boosted_weather", mon.get("weather", None)),
                    now,
                    mon.get("costume", None),
                    mon.get("form", None),
                    "encounter"
                )
            )

    query = (
        "INSERT INTO pokemon_test (encounter_id, spawnpoint_id, pokemon_id, latitude, longitude, disappear_time, "
        "individual_attack, individual_defense, individual_stamina, move_1, move_2, cp, cp_multiplier, "
        "weight, height, gender, catch_prob_1, catch_prob_2, catch_prob_3, rating_attack, rating_defense, "
        "weather_boosted_condition, last_modified, costume, form, seen_type) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE last_modified=VALUES(last_modified), disappear_time=VALUES(disappear_time), "
        "individual_attack=VALUES(individual_attack), individual_defense=VALUES(individual_defense), "
        "individual_stamina=VALUES(individual_stamina), move_1=VALUES(move_1), move_2=VALUES(move_2), "
        "cp=VALUES(cp), cp_multiplier=VALUES(cp_multiplier), weight=VALUES(weight), height=VALUES(height), "
        "gender=VALUES(gender), catch_prob_1=VALUES(catch_prob_1), catch_prob_2=VALUES(catch_prob_2), "
        "catch_prob_3=VALUES(catch_prob_3), rating_attack=VALUES(rating_attack), "
        "rating_defense=VALUES(rating_defense), weather_boosted_condition=VALUES(weather_boosted_condition), "
        "costume=VALUES(costume), form=VALUES(form), pokemon_id=VALUES(pokemon_id), fort_id=NULL, cell_id=NULL, "
        "latitude=VALUES(latitude), longitude=VALUES(longitude), spawnpoint_id=VALUES(spawnpoint_id), "
        "seen_type=VALUES(seen_type)"
    )

    logging.info("Will insert %s mons" % str(len(mon_args)))

    execute_query(query, mon_args)


def execute_query(query: str, args: tuple = None):
    if not args or not conn:
        return None

    cursor = conn.cursor()

    try:
        cursor.executemany(query, args)
        conn.commit()
    except mysql.connector.Error as err:
        logging.error("Failed executing query: %s" % str(err))
        if err.errno == errorcode.CR_CONNECTION_ERROR:
            connect_db()
            execute_query(query, args)
    except Exception as e:
        logging.error("Unspecified exception in dbWrapper: %s" % str(e))
    finally:
        cursor.close()

    return None


connect_db()
app.run(host='127.0.0.1', port=8088)

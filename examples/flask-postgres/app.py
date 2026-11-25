import os
from contextlib import closing

import psycopg2
from flask import Flask

app = Flask(__name__)


@app.get("/")
def index():
    return {"message": "Hello from Flask"}


@app.get("/db")
def database():
    with closing(psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=3)) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT 1")
        return {"database": cursor.fetchone()[0]}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

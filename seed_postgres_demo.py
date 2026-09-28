#!/usr/bin/env python3
"""Seed the free demo PostgreSQL database (Neon) with sample data.

Loads a small, deterministic, AdventureWorks-inspired dataset — business
schemas in the style of the `AdventureWorks` sample this project was built
against locally — so the public recruiter demo can answer the same kinds of
questions as the MS SQL Server development database:

    production.product_categories, production.products
    sales.sales_territories, sales.customers, sales.orders, sales.order_items

Everything is generated in-code (no external data files), seeded with fixed
random values so repeated runs produce identical data, and idempotent:
running it again wipes and reloads the demo schemas only.

Usage:
    python seed_postgres_demo.py

Reads the same environment variables as the app:
    DB_DIALECT=postgres (implicit — a postgres URL is required)
    DB_CONNECTION_STRING   (a postgres:// or postgresql:// URI; Neon's own
                            URI works as-is) — or the DB_HOST/DB_NAME/
                            DB_USER/DB_PASSWORD parts instead
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

# Make `app` importable when run from the project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.settings import load_settings  # noqa: E402
from app.database.uri import POSTGRES_DIALECT, resolve_dialect  # noqa: E402

DEMO_SCHEMAS = ("production", "sales")
SEED = 20260927  # fixed seed: identical data on every run

# ----------------------------------------------------------------------------
# Reference data (deliberately compact but realistic)
# ----------------------------------------------------------------------------

PRODUCT_CATEGORIES = [
    ("Bikes", "Complete bicycles for road, mountain, and touring."),
    ("Components", "Handlebars, saddles, wheels, and drivetrain parts."),
    ("Clothing", "Cycling jerseys, shorts, gloves, and helmets."),
    ("Accessories", "Pumps, locks, lights, and hydration gear."),
]

PRODUCTS = [
    # (category, name, list_price, standard_cost, weight_kg, color)
    ("Bikes", "Adventure Works Road-150 Red", 3578.27, 2275.19, 12.5, "Red"),
    ("Bikes", "Adventure Works Road-150 Black", 3578.27, 2275.19, 12.5, "Black"),
    ("Bikes", "Adventure Works Mountain-100 Silver", 2319.99, 1655.19, 14.2, "Silver"),
    ("Bikes", "Adventure Works Touring-1000 Yellow", 2384.07, 1700.99, 15.8, "Yellow"),
    ("Components", "Adventure Works Rear Derailleur", 121.46, 78.98, 0.35, None),
    ("Components", "Adventure Works Front Derailleur", 91.49, 60.19, 0.30, None),
    ("Components", "Adventure Works Carbon Saddle", 180.00, 104.71, 0.42, None),
    ("Components", "Adventure Works ML Road Wheel", 455.00, 300.11, 2.10, None),
    ("Clothing", "Adventure Works Classic Vest, L", 63.50, 34.99, 0.30, "Blue"),
    ("Clothing", "Adventure Works Jersey, XL", 49.99, 26.12, 0.28, "Yellow"),
    ("Clothing", "Adventure Works Racing Gloves, M", 27.75, 12.19, 0.12, "Red"),
    ("Clothing", "Adventure Works Sport Helmet", 34.99, 18.41, 0.55, "Black"),
    ("Accessories", "Adventure Works Floor Pump", 39.99, 19.79, 1.40, None),
    ("Accessories", "Adventure Works Cable Lock", 24.99, 11.50, 0.90, None),
    ("Accessories", "Adventure Works Headlight", 44.50, 21.07, 0.25, None),
    ("Accessories", "Adventure Works Water Bottle Cage", 12.99, 5.24, 0.15, None),
]

TERRITORIES = [
    # (name, country, region)
    ("Northwest", "United States", "North America"),
    ("Northeast", "United States", "North America"),
    ("Southwest", "United States", "North America"),
    ("Central", "United States", "North America"),
    ("Canada", "Canada", "North America"),
    ("France", "France", "Europe"),
    ("Germany", "Germany", "Europe"),
    ("United Kingdom", "United Kingdom", "Europe"),
    ("Australia", "Australia", "Pacific"),
]

FIRST_NAMES = [
    "Aiden", "Bianca", "Carlos", "Dana", "Elias", "Farah", "Gustavo", "Hana",
    "Ivan", "Julia", "Kofi", "Lena", "Marco", "Nadia", "Omar", "Priya",
    "Quentin", "Rosa", "Samir", "Tessa", "Umeko", "Viktor", "Wendy", "Xavier",
    "Yara", "Zane",
]
LAST_NAMES = [
    "Alvarez", "Berg", "Chen", "Dube", "Eriksen", "Fischer", "Garcia", "Haas",
    "Ibrahim", "Jansen", "Kim", "Laurent", "Moreau", "Novak", "Okafor",
    "Petrov", "Quintana", "Rossi", "Silva", "Tran", "Ueda", "Voss", "Weber",
    "Yilmaz", "Zhou",
]

# (description, share_of_customers, order_multiplier)
CUSTOMER_TYPES = [
    ("individual", 0.55, 1.0),
    ("online", 0.45, 1.3),
]


def generate_customers(rng: random.Random, count: int = 60):
    customers = []
    used_names = set()
    for i in range(1, count + 1):
        while True:
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            if (first, last) not in used_names:
                used_names.add((first, last))
                break
        company_type = "individual"
        if rng.random() > CUSTOMER_TYPES[0][1]:
            company_type = "online"
        territory = rng.choice(TERRITORIES)[0]
        year = rng.choice([2012, 2013, 2014])
        customers.append(
            {
                "customer_number": f"AW-{11000 + i}",
                "first_name": first,
                "last_name": last,
                "company_name": company_type.capitalize(),
                "customer_type": company_type,
                "territory": territory,
                "signup_date": date(year, rng.randint(1, 12), rng.randint(1, 28)),
            }
        )
    return customers


def generate_orders(rng: random.Random, customers, products, count: int = 420):
    orders = []
    order_items = []
    order_id = 1
    item_id = 1

    start = date(2012, 1, 1)
    end = date(2014, 12, 31)
    span_days = (end - start).days

    for _ in range(count):
        customer = rng.choice(customers)
        # Orders cluster in the 3 demo years (AdventureWorks-like period).
        order_date = start + timedelta(days=rng.randint(0, span_days))
        if order_date > end:
            order_date = end

        territory = customer["territory"]
        online = customer["customer_type"] == "online"
        n_items = rng.choices([1, 2, 3, 4], weights=[45, 30, 15, 10])[0]
        chosen = rng.sample(products, n_items)

        subtotal = 0.0
        for product in chosen:
            qty = max(1, int(rng.gauss(2, 1.5)))
            unit_price = round(product["list_price"] * rng.uniform(0.85, 1.05), 2)
            line_total = round(qty * unit_price, 2)
            subtotal += line_total
            order_items.append(
                {
                    "item_id": item_id,
                    "order_id": order_id,
                    "product_id": product["product_id"],
                    "order_qty": qty,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
            )
            item_id += 1

        discount = round(subtotal * rng.choice([0.0, 0.0, 0.0, 0.05, 0.10]), 2)
        tax = round((subtotal - discount) * 0.08, 2)
        freight = round(rng.uniform(5, 35), 2)
        orders.append(
            {
                "order_number": f"SO-{50000 + order_id}",
                "customer_id": customer["customer_id"],
                "order_date": order_date,
                "ship_date": order_date + timedelta(days=rng.randint(1, 9)),
                "online_order": online,
                "sales_territory": territory,
                "subtotal": round(subtotal, 2),
                "discount_amount": discount,
                "tax_amount": tax,
                "freight": freight,
                "total_due": round(subtotal - discount + tax + freight, 2),
            }
        )
        order_id += 1

    return orders, order_items


def main() -> int:
    settings = load_settings()
    if not settings.db_connection_string:
        print("ERROR: no database configured. Set DB_CONNECTION_STRING (or the")
        print("DB_HOST/DB_NAME/DB_USER/DB_PASSWORD parts) in .env, then rerun.")
        return 1

    if resolve_dialect(os.getenv("DB_DIALECT")) != POSTGRES_DIALECT:
        print("Refusing to run: this script targets PostgreSQL only.")
        print("Set DB_DIALECT=postgres and a postgres connection string.")
        return 1

    import psycopg2  # local import: only needed when actually seeding

    try:
        conn = psycopg2.connect(settings.db_connection_string)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not connect to PostgreSQL: {exc}")
        return 1

    rng = random.Random(SEED)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            print("Creating demo schemas (if missing)...")
            for schema in DEMO_SCHEMAS:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            print("Recreating tables (demo data only)...")
            cur.execute("DROP TABLE IF EXISTS sales.order_items, sales.orders, sales.customers, sales.sales_territories CASCADE")
            cur.execute("DROP TABLE IF EXISTS production.products, production.product_categories CASCADE")
            cur.execute("""
                CREATE TABLE production.product_categories (
                    category_id  INTEGER PRIMARY KEY,
                    name         TEXT NOT NULL,
                    description  TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE production.products (
                    product_id     INTEGER PRIMARY KEY,
                    name           TEXT NOT NULL,
                    category_id    INTEGER NOT NULL REFERENCES production.product_categories(category_id),
                    list_price     NUMERIC(10,2) NOT NULL,
                    standard_cost  NUMERIC(10,2) NOT NULL,
                    weight_kg      NUMERIC(6,3),
                    color          TEXT,
                    created_at     TIMESTAMP NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE sales.sales_territories (
                    territory_id INTEGER PRIMARY KEY,
                    name         TEXT NOT NULL,
                    country      TEXT NOT NULL,
                    region       TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE sales.customers (
                    customer_id     INTEGER PRIMARY KEY,
                    customer_number TEXT UNIQUE NOT NULL,
                    first_name      TEXT NOT NULL,
                    last_name       TEXT NOT NULL,
                    company_name    TEXT,
                    customer_type   TEXT NOT NULL,
                    signup_date     DATE NOT NULL,
                    territory_id    INTEGER NOT NULL REFERENCES sales.sales_territories(territory_id)
                )
            """)
            cur.execute("""
                CREATE TABLE sales.orders (
                    order_id        INTEGER PRIMARY KEY,
                    order_number    TEXT UNIQUE NOT NULL,
                    customer_id     INTEGER NOT NULL REFERENCES sales.customers(customer_id),
                    order_date      DATE NOT NULL,
                    ship_date       DATE,
                    online_order    BOOLEAN NOT NULL,
                    subtotal        NUMERIC(12,2) NOT NULL,
                    discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
                    tax_amount      NUMERIC(12,2) NOT NULL DEFAULT 0,
                    freight         NUMERIC(12,2) NOT NULL DEFAULT 0,
                    total_due       NUMERIC(12,2) NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE sales.order_items (
                    item_id    INTEGER PRIMARY KEY,
                    order_id   INTEGER NOT NULL REFERENCES sales.orders(order_id),
                    product_id INTEGER NOT NULL REFERENCES production.products(product_id),
                    order_qty  INTEGER NOT NULL,
                    unit_price NUMERIC(10,2) NOT NULL,
                    line_total NUMERIC(12,2) NOT NULL
                )
            """)

            print("Inserting reference data...")
            categories = [(i + 1, name, desc) for i, (name, desc) in enumerate(PRODUCT_CATEGORIES)]
            cur.executemany(
                "INSERT INTO production.product_categories VALUES (%s, %s, %s)",
                categories,
            )
            cat_by_name = {name: cid for cid, name, _ in categories}

            territories = [(i + 1, name, country, region) for i, (name, country, region) in enumerate(TERRITORIES)]
            cur.executemany(
                "INSERT INTO sales.sales_territories VALUES (%s, %s, %s, %s)",
                territories,
            )
            terr_by_name = {name: tid for tid, name, _, _ in territories}

            products = []
            for i, (cat, name, price, cost, weight, color) in enumerate(PRODUCTS, start=1):
                products.append(
                    {
                        "product_id": i,
                        "name": name,
                        "category_id": cat_by_name[cat],
                        "list_price": price,
                        "standard_cost": cost,
                        "weight_kg": weight,
                        "color": color,
                    }
                )
            cur.executemany(
                """INSERT INTO production.products
                   (product_id, name, category_id, list_price, standard_cost, weight_kg, color)
                   VALUES (%(product_id)s, %(name)s, %(category_id)s, %(list_price)s,
                           %(standard_cost)s, %(weight_kg)s, %(color)s)""",
                products,
            )

            customers = generate_customers(rng)
            for i, c in enumerate(customers, start=1):
                c["customer_id"] = i
            cur.executemany(
                """INSERT INTO sales.customers
                   (customer_id, customer_number, first_name, last_name,
                    company_name, customer_type, signup_date, territory_id)
                   VALUES (%(customer_id)s, %(customer_number)s, %(first_name)s,
                           %(last_name)s, %(company_name)s, %(customer_type)s,
                           %(signup_date)s, %(territory_id)s)""",
                [
                    {**c, "territory_id": terr_by_name[c["territory"]]}
                    for c in customers
                ],
            )

            print("Generating and inserting orders...")
            orders, order_items = generate_orders(rng, customers, products)
            cur.executemany(
                """INSERT INTO sales.orders
                   (order_id, order_number, customer_id, order_date, ship_date,
                    online_order, subtotal, discount_amount, tax_amount,
                    freight, total_due)
                   VALUES (%(order_id)s, %(order_number)s, %(customer_id)s,
                           %(order_date)s, %(ship_date)s, %(online_order)s,
                           %(subtotal)s, %(discount_amount)s, %(tax_amount)s,
                           %(freight)s, %(total_due)s)""",
                [{**o, "order_id": i} for i, o in enumerate(orders, start=1)],
            )
            cur.executemany(
                """INSERT INTO sales.order_items
                   (item_id, order_id, product_id, order_qty, unit_price, line_total)
                   VALUES (%(item_id)s, %(order_id)s, %(product_id)s,
                           %(order_qty)s, %(unit_price)s, %(line_total)s)""",
                order_items,
            )

        conn.commit()
        print("\nSeed complete:")
        print(f"  production.product_categories: {len(PRODUCT_CATEGORIES)}")
        print(f"  production.products:           {len(PRODUCTS)}")
        print(f"  sales.sales_territories:       {len(TERRITORIES)}")
        print(f"  sales.customers:               {len(customers)}")
        print(f"  sales.orders:                  {len(orders)}")
        print(f"  sales.order_items:             {len(order_items)}")
        print("\nReady for the recruiter demo — try: 'Which sales territory")
        print("generated the most revenue?' or 'Top 10 products by total sales.'")
        return 0
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"ERROR while seeding (rolled back): {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

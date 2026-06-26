import requests
import streamlit as st
import time

# ── Credenciales desde Streamlit Secrets ──────────────────────────────────────
ACCOUNT = st.secrets["VTEX_ACCOUNT"]
APP_KEY = st.secrets["VTEX_APP_KEY"]
APP_TOKEN = st.secrets["VTEX_APP_TOKEN"]

HEADERS = {
    "X-VTEX-API-AppKey": APP_KEY,
    "X-VTEX-API-AppToken": APP_TOKEN,
    "Content-Type": "application/json",
}

BASE_OMS = f"https://{ACCOUNT}.vtexcommercestable.com.br/api/oms/pvt"
BASE_LOG = f"https://logistics.vtexcommercestable.com.br/api/logistics/pvt"
BASE_CAT = f"https://{ACCOUNT}.vtexcommercestable.com.br/api/catalog_system/pvt"

# ── Clasificación de Marketplace por sufijo de Order ID ──────────────────────
MP_SUFFIX = {
    "DFT": "Dafiti",
    "GVL": "Agaval",
    "VPC": "Puntos Colombia",
    "DDD": "ADDI",
    "FFF": "Fruta Fresca",
    "MLB": "Mercado Libre",
    "MPX": "Éxito",
    "FLB": "Falabella",
    "PLT": "Pilatos",
}

def get_marketplace(order_id: str) -> str:
    parts = order_id.split("-")
    suffix = parts[-1].upper() if parts else ""
    return MP_SUFFIX.get(suffix, "Propio")

# ── Extracción de órdenes con paginación ─────────────────────────────────────
def fetch_orders(days_back: int = 30) -> list:
    from datetime import datetime, timedelta
    date_from = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00.000Z")
    date_to   = datetime.utcnow().strftime("%Y-%m-%dT23:59:59.999Z")

    orders, page = [], 1
    while True:
        try:
            resp = requests.get(
                f"{BASE_OMS}/orders",
                headers=HEADERS,
                params={
                    "f_status": "invoiced,handling,ready-for-handling,waiting-for-fulfillment",
                    "f_creationDate": f"creationDate:[{date_from} TO {date_to}]",
                    "per_page": 100,
                    "page": page,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("list", [])
            if not batch:
                break
            orders.extend(batch)
            total_pages = data.get("paging", {}).get("pages", 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.4)
        except requests.exceptions.RequestException as e:
            st.error(f"Error al obtener órdenes página {page}: {e}")
            break

    return orders

# ── Parsear órdenes a lista de dicts ─────────────────────────────────────────
def parse_orders(raw_orders: list) -> list:
    rows = []
    for o in raw_orders:
        order_id = o.get("orderId", "")
        totals   = {t["id"]: t["value"] for t in o.get("totals", [])}
        items    = o.get("items", [])
        rows.append({
            "order_id":    order_id,
            "marketplace": get_marketplace(order_id),
            "created_at":  o.get("creationDate", ""),
            "status":      o.get("status", ""),
            "gmv":         totals.get("Items", 0) / 100,
            "discount":    abs(totals.get("Discounts", 0)) / 100,
            "shipping":    totals.get("Shipping", 0) / 100,
            "total":       o.get("value", 0) / 100,
            "units": sum(int(i.get("quantity", 0)) for i in items if isinstance(i, dict)),
            "sku_ids": [str(i.get("id","")) for i in items if isinstance(i, dict)],
        })
    return rows

# ── Inventario por SKU ────────────────────────────────────────────────────────
def fetch_inventory(sku_id: str) -> dict:
    try:
        resp = requests.get(
            f"{BASE_LOG}/inventory/skus/{sku_id}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            total = sum(
                b.get("totalQuantity", 0) - b.get("reservedQuantity", 0)
                for b in data.get("balance", [])
            )
            return {"sku_id": sku_id, "available": total}
    except Exception:
        pass
    return {"sku_id": sku_id, "available": -1}

# ── Categorías de productos ───────────────────────────────────────────────────
def fetch_product_info(product_id: str) -> dict:
    try:
        resp = requests.get(
            f"{BASE_CAT}/products/{product_id}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            d = resp.json()
            specs = {}
            for group in d.get("allSpecifications", []):
                specs[group] = d.get("specificationGroups", {})
            return {
                "product_id": product_id,
                "name":       d.get("Name", ""),
                "category":   d.get("CategoryId", ""),
                "brand":      d.get("BrandName", ""),
                "gender":     "Unisex",
            }
    except Exception:
        pass
    return {"product_id": product_id, "name": "", "category": "", "brand": "", "gender": "Unisex"}

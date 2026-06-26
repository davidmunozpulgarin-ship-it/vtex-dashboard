import requests
import streamlit as st
import time
from datetime import datetime, timedelta

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
    try:
        parts = str(order_id).split("-")
        suffix = parts[-1].upper() if parts else ""
        return MP_SUFFIX.get(suffix, "Propio")
    except Exception:
        return "Propio"

def fetch_orders(days_back: int = 30) -> list:
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
            if page >= total_pages or page >= 30:
                break
            page += 1
            time.sleep(0.4)
        except Exception as e:
            st.error(f"Error al obtener órdenes página {page}: {e}")
            break
    return orders

def parse_orders(raw_orders: list) -> list:
    rows = []
    for o in raw_orders:
        try:
            order_id = str(o.get("orderId", ""))
            totals   = {}
            for t in o.get("totals", []):
                if isinstance(t, dict):
                    totals[t.get("id", "")] = t.get("value", 0)
            items = o.get("items", [])
            if not isinstance(items, list):
                items = []
            units = 0
            sku_ids = []
            for i in items:
                if isinstance(i, dict):
                    units += int(i.get("quantity", 0) or 0)
                    sku_ids.append(str(i.get("id", "")))
            rows.append({
                "order_id":    order_id,
                "marketplace": get_marketplace(order_id),
                "created_at":  str(o.get("creationDate", "")),
                "status":      str(o.get("status", "")),
                "gmv":         float(totals.get("Items", 0)) / 100,
                "discount":    abs(float(totals.get("Discounts", 0))) / 100,
                "shipping":    float(totals.get("Shipping", 0)) / 100,
                "total":       float(o.get("value", 0) or 0) / 100,
                "units":       units,
                "sku_ids":     sku_ids,
            })
        except Exception:
            continue
    return rows

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
                int(b.get("totalQuantity", 0) or 0) - int(b.get("reservedQuantity", 0) or 0)
                for b in data.get("balance", [])
                if isinstance(b, dict)
            )
            return {"sku_id": sku_id, "available": total}
    except Exception:
        pass
    return {"sku_id": sku_id, "available": -1}

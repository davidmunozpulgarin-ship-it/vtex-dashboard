import requests
import streamlit as st
import time
from datetime import datetime, timedelta

ACCOUNT   = st.secrets["VTEX_ACCOUNT"]
APP_KEY   = st.secrets["VTEX_APP_KEY"]
APP_TOKEN = st.secrets["VTEX_APP_TOKEN"]

HEADERS = {
    "X-VTEX-API-AppKey":   APP_KEY,
    "X-VTEX-API-AppToken": APP_TOKEN,
    "Content-Type":        "application/json",
}

BASE_OMS = f"https://{ACCOUNT}.vtexcommercestable.com.br/api/oms/pvt"
BASE_LOG = f"https://logistics.vtexcommercestable.com.br/api/logistics/pvt"

# Sufijos válidos de Marketplace
MP_SUFFIX = {
    "DFT": "Dafiti",
    "GVL": "Agaval",
    "VPC": "Puntos Colombia",
    "DDD": "ADDI",
    "FFF": "Fruta Fresca",
    "MLB": "Mercado Libre",
    "MPX": "Exito",
    "FLB": "Falabella",
    "PLT": "Pilatos",
}

VTEX_STATUSES = "invoiced,ready-for-handling,handling,payment-approved"

STATUS_LABEL = {
    "invoiced":            "Facturado",
    "ready-for-handling":  "Listo para preparación",
    "handling":            "Preparando",
    "payment-approved":    "Pago aprobado",
}

def get_marketplace(order_id):
    """
    Busca el código de marketplace en CUALQUIER parte del orderId.
    VTEX puede enviarlo como: DFT-5229258-284912359  o  1234-01-DFT
    """
    try:
        parts = str(order_id).upper().split("-")
        for part in parts:
            if part in MP_SUFFIX:
                return MP_SUFFIX[part]
        return None
    except Exception:
        return None

def is_marketplace_order(order_id):
    """True si alguna parte del orderId es un código de marketplace conocido."""
    return get_marketplace(order_id) is not None

def fetch_orders(date_from_str, date_to_str):
    date_from  = datetime.strptime(date_from_str, "%Y-%m-%d")
    date_to    = datetime.strptime(date_to_str,   "%Y-%m-%d")
    all_orders = []
    current    = date_from

    while current <= date_to:
        chunk_end = min(current + timedelta(days=6), date_to)
        f_from    = current.strftime("%Y-%m-%dT00:00:00.000Z")
        f_to      = chunk_end.strftime("%Y-%m-%dT23:59:59.999Z")
        page      = 1

        while True:
            try:
                resp = requests.get(
                    f"{BASE_OMS}/orders",
                    headers=HEADERS,
                    params={
                        "f_status":       VTEX_STATUSES,
                        "f_creationDate": f"creationDate:[{f_from} TO {f_to}]",
                        "per_page":       100,
                        "page":           page,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data  = resp.json()
                batch = data.get("list", [])
                if not batch:
                    break

                mp_batch = [
                    o for o in batch
                    if is_marketplace_order(o.get("orderId", ""))
                ]
                all_orders.extend(mp_batch)

                total_pages = data.get("paging", {}).get("pages", 1)
                if page >= total_pages or page >= 29:
                    break
                page += 1
                time.sleep(0.35)

            except Exception as e:
                st.warning(f"Bloque {f_from[:10]}: {e}")
                break

        current = chunk_end + timedelta(days=1)

    return all_orders

def fetch_order_detail(order_id):
    try:
        resp = requests.get(
            f"{BASE_OMS}/orders/{order_id}",
            headers=HEADERS,
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def parse_orders(raw_orders, enrich_sample=150):
    rows    = []
    total_n = len(raw_orders)

    if total_n == 0:
        return rows

    bar = st.progress(0, text="Procesando órdenes de marketplace...")

    for idx, o in enumerate(raw_orders):
        try:
            order_id = str(o.get("orderId", ""))
            mp_name  = get_marketplace(order_id)
            if not mp_name:
                continue

            if idx < enrich_sample:
                detail = fetch_order_detail(order_id)
                if detail:
                    o = detail
                time.sleep(0.12)

            totals = {}
            for t in o.get("totals", []):
                if isinstance(t, dict):
                    totals[t.get("id", "")] = t.get("value", 0)

            items = o.get("items", [])
            if not isinstance(items, list):
                items = []

            units     = 0
            sku_ids   = []
            item_rows = []
            for i in items:
                if isinstance(i, dict):
                    qty   = int(i.get("quantity", 0) or 0)
                    price = float(i.get("price", 0) or i.get("sellingPrice", 0) or 0) / 100
                    units += qty
                    sku_ids.append(str(i.get("id", "")))
                    item_rows.append({
                        "order_id":    order_id,
                        "marketplace": mp_name,
                        "sku_id":      str(i.get("id", "")),
                        "nombre":      str(i.get("name", "")),
                        "cantidad":    qty,
                        "precio_unit": price,
                        "valor_total": price * qty,
                    })

            gmv_val      = float(totals.get("Items", 0)) / 100
            discount_val = abs(float(totals.get("Discounts", 0))) / 100
            total_val    = float(o.get("value", 0) or o.get("totalValue", 0) or 0) / 100

            if gmv_val == 0 and total_val > 0:
                gmv_val = total_val + discount_val

            raw_status   = str(o.get("status", ""))
            status_label = STATUS_LABEL.get(raw_status, raw_status)

            rows.append({
                "order_id":    order_id,
                "marketplace": mp_name,
                "created_at":  str(o.get("creationDate", "")),
                "status":      status_label,
                "status_raw":  raw_status,
                "gmv":         gmv_val,
                "discount":    discount_val,
                "shipping":    float(totals.get("Shipping", 0)) / 100,
                "total":       total_val,
                "units":       units,
                "sku_ids":     sku_ids,
                "items":       item_rows,
            })

        except Exception:
            continue

        if idx % 50 == 0 or idx == total_n - 1:
            pct = min(int((idx + 1) / max(total_n, 1) * 100), 100)
            bar.progress(pct, text=f"Procesando {idx+1} de {total_n} órdenes...")

    bar.empty()
    return rows

def fetch_inventory(sku_id):
    try:
        resp = requests.get(
            f"{BASE_LOG}/inventory/skus/{sku_id}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data  = resp.json()
            total = sum(
                int(b.get("totalQuantity", 0) or 0) -
                int(b.get("reservedQuantity", 0) or 0)
                for b in data.get("balance", [])
                if isinstance(b, dict)
            )
            return {"sku_id": sku_id, "available": total}
    except Exception:
        pass
    return {"sku_id": sku_id, "available": -1}

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

def get_marketplace(order_id):
    try:
        parts = str(order_id).split("-")
        suffix = parts[-1].upper() if parts else ""
        return MP_SUFFIX.get(suffix, "Propio")
    except Exception:
        return "Propio"

def fetch_orders(date_from_str, date_to_str):
    """
    Trae lista de ordenes entre dos fechas (strings formato YYYY-MM-DD).
    Usa paginacion con max 30 paginas por llamada de VTEX.
    Para rangos grandes divide en semanas.
    """
    date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
    date_to   = datetime.strptime(date_to_str,   "%Y-%m-%d")

    # Dividir en bloques de 7 dias para no exceder 30 paginas
    all_orders = []
    current = date_from
    while current <= date_to:
        chunk_end = min(current + timedelta(days=6), date_to)
        f_from = current.strftime("%Y-%m-%dT00:00:00.000Z")
        f_to   = chunk_end.strftime("%Y-%m-%dT23:59:59.999Z")
        page   = 1
        while True:
            try:
                resp = requests.get(
                    f"{BASE_OMS}/orders",
                    headers=HEADERS,
                    params={
                        "f_status": "invoiced,handling,ready-for-handling,waiting-for-fulfillment,payment-approved",
                        "f_creationDate": f"creationDate:[{f_from} TO {f_to}]",
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data  = resp.json()
                batch = data.get("list", [])
                if not batch:
                    break
                all_orders.extend(batch)
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
    """Trae el detalle completo de una orden para obtener valores reales."""
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

def parse_orders(raw_orders, fetch_details=False, max_details=500):
    """
    Parsea lista de ordenes.
    Si fetch_details=True consulta cada orden individualmente (mas lento pero datos completos).
    """
    rows = []
    total = len(raw_orders)

    progress = st.progress(0, text="Procesando ordenes...")

    for idx, o in enumerate(raw_orders):
        try:
            order_id = str(o.get("orderId", ""))

            if fetch_details and idx < max_details:
                detail = fetch_order_detail(order_id)
                if detail:
                    o = detail
                time.sleep(0.15)

            totals = {}
            for t in o.get("totals", []):
                if isinstance(t, dict):
                    totals[t.get("id", "")] = t.get("value", 0)

            items = o.get("items", [])
            if not isinstance(items, list):
                items = []

            units   = 0
            sku_ids = []
            item_rows = []
            for i in items:
                if isinstance(i, dict):
                    qty  = int(i.get("quantity", 0) or 0)
                    price = float(i.get("price", 0) or i.get("sellingPrice", 0) or 0) / 100
                    units += qty
                    sku_ids.append(str(i.get("id", "")))
                    item_rows.append({
                        "order_id":    order_id,
                        "marketplace": get_marketplace(order_id),
                        "sku_id":      str(i.get("id", "")),
                        "nombre":      str(i.get("name", "")),
                        "cantidad":    qty,
                        "precio_unit": price,
                        "valor_total": price * qty,
                    })

            gmv_val      = float(totals.get("Items", 0)) / 100
            discount_val = abs(float(totals.get("Discounts", 0))) / 100
            total_val    = float(o.get("value", 0) or 0) / 100

            # Si el listado no trae value, usar totalValue
            if total_val == 0:
                total_val = float(o.get("totalValue", 0) or 0) / 100
            if gmv_val == 0 and total_val > 0:
                gmv_val = total_val + discount_val

            rows.append({
                "order_id":    order_id,
                "marketplace": get_marketplace(order_id),
                "created_at":  str(o.get("creationDate", "")),
                "status":      str(o.get("status", "")),
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

        if idx % 50 == 0:
            progress.progress(
                min(int((idx / max(total, 1)) * 100), 100),
                text=f"Procesando orden {idx+1} de {total}..."
            )

    progress.empty()
    return rows

def fetch_inventory(sku_id):
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

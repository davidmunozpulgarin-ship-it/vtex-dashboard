import requests
import streamlit as st
import time
from datetime import datetime, timedelta, timezone

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

# Zona horaria Colombia = UTC-5
COL_TZ = timezone(timedelta(hours=-5))

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
    try:
        parts = str(order_id).upper().split("-")
        for part in parts:
            if part in MP_SUFFIX:
                return MP_SUFFIX[part]
        return None
    except Exception:
        return None


def is_marketplace_order(order_id):
    return get_marketplace(order_id) is not None


def fecha_a_utc(date_str, hora="00:00:00", fin_dia=False):
    """
    Convierte una fecha (YYYY-MM-DD) en hora Colombia (UTC-5) a UTC.
    Si fin_dia=True usa 23:59:59 Colombia = 04:59:59 UTC día siguiente.
    """
    hora_str = "23:59:59" if fin_dia else "00:00:00"
    dt_col   = datetime.strptime(f"{date_str} {hora_str}", "%Y-%m-%d %H:%M:%S")
    dt_col   = dt_col.replace(tzinfo=COL_TZ)
    dt_utc   = dt_col.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_orders(date_from_str, date_to_str):
    """
    Descarga órdenes usando fechas en hora Colombia convertidas a UTC.
    Divide en bloques de 7 días para no superar el límite de 30 páginas.
    """
    from datetime import date as date_type
    date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
    date_to   = datetime.strptime(date_to_str,   "%Y-%m-%d").date()

    all_orders = []
    current    = date_from

    while current <= date_to:
        chunk_end = min(current + timedelta(days=6), date_to)

        # Convertir a UTC respetando UTC-5
        f_from = fecha_a_utc(current.strftime("%Y-%m-%d"),   fin_dia=False)
        f_to   = fecha_a_utc(chunk_end.strftime("%Y-%m-%d"), fin_dia=True)

        page = 1
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
                st.warning(f"Bloque {current}: {e}")
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
    """
    GMV = value / 100 (valor pagado por el cliente en pesos).
    Filtra además que la fecha de creación esté en hora Colombia
    dentro del rango solicitado (para descartar órdenes UTC que
    se cuelan por el desfase horario).
    """
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

            # Enriquecer con detalle para obtener items completos
            if idx < enrich_sample:
                detail = fetch_order_detail(order_id)
                if detail:
                    o = detail
                time.sleep(0.12)

            # ── GMV = valor pagado por el cliente ─────────────────────────
            gmv_val = float(o.get("value", 0) or o.get("totalValue", 0) or 0) / 100

            # ── Descuentos y envío (informativos) ─────────────────────────
            discount_val = 0.0
            shipping_val = 0.0
            for t in (o.get("totals") or []):
                if isinstance(t, dict):
                    tid = t.get("id", "")
                    val = float(t.get("value", 0) or 0)
                    if tid == "Discounts":
                        discount_val = abs(val) / 100
                    elif tid == "Shipping":
                        shipping_val = val / 100

            # ── Items ─────────────────────────────────────────────────────
            items = o.get("items") or []
            if not isinstance(items, list):
                items = []

            units     = 0
            sku_ids   = []
            item_rows = []
            for i in items:
                if isinstance(i, dict):
                    qty   = int(i.get("quantity", 0) or 0)
                    price = float(i.get("sellingPrice", 0) or i.get("price", 0) or 0) / 100
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

            # ── Fecha en hora Colombia ─────────────────────────────────────
            creation_raw = str(o.get("creationDate", ""))
            try:
                dt_utc    = datetime.strptime(creation_raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                dt_col    = dt_utc.astimezone(COL_TZ)
                fecha_col = dt_col.date()
            except Exception:
                fecha_col = None

            raw_status   = str(o.get("status", ""))
            status_label = STATUS_LABEL.get(raw_status, raw_status)

            rows.append({
                "order_id":    order_id,
                "marketplace": mp_name,
                "created_at":  creation_raw,
                "fecha":       fecha_col,       # fecha en hora Colombia
                "status":      status_label,
                "status_raw":  raw_status,
                "gmv":         gmv_val,
                "discount":    discount_val,
                "shipping":    shipping_val,
                "total":       gmv_val,
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
                for b in (data.get("balance") or [])
                if isinstance(b, dict)
            )
            return {"sku_id": sku_id, "available": max(total, 0)}
    except Exception:
        pass
    return {"sku_id": sku_id, "available": -1}

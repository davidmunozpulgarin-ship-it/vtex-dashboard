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

BASE_OMS     = f"https://{ACCOUNT}.vtexcommercestable.com.br/api/oms/pvt"
BASE_LOG     = f"https://logistics.vtexcommercestable.com.br/api/logistics/pvt"
BASE_CATALOG = f"https://{ACCOUNT}.vtexcommercestable.com.br/api/catalog/pvt"

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
    hora_str = "23:59:59" if fin_dia else "00:00:00"
    dt_col   = datetime.strptime(f"{date_str} {hora_str}", "%Y-%m-%d %H:%M:%S")
    dt_col   = dt_col.replace(tzinfo=COL_TZ)
    dt_utc   = dt_col.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_orders(date_from_str, date_to_str):
    from datetime import date as date_type
    date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
    date_to   = datetime.strptime(date_to_str,   "%Y-%m-%d").date()

    all_orders = []
    current    = date_from

    while current <= date_to:
        chunk_end = min(current + timedelta(days=6), date_to)
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


# ── Extrae ciudad de envío desde el detalle de la orden ──────────────────────
def _extract_city(order_detail: dict) -> str | None:
    """Ciudad tomada de shippingData (dirección de envío del pedido)."""
    if not order_detail:
        return None

    shipping = order_detail.get("shippingData") or {}

    # 1) address directo
    address = shipping.get("address") or {}
    city = str(address.get("city", "") or "").strip()
    if city:
        return city.title()

    # 2) selectedAddresses (lista)
    for addr in (shipping.get("selectedAddresses") or []):
        city = str((addr or {}).get("city", "") or "").strip()
        if city:
            return city.title()

    return None


# ── Consulta el catálogo para obtener género y foto de un SKU ────────────────
_sku_cache: dict = {}   # cache en memoria para no repetir llamadas


def fetch_sku_catalog_info(sku_id: str) -> dict:
    """
    Llama a GET /api/catalog/pvt/stockkeepingunit/{skuId}
    Retorna dict con keys: 'gender' ('Hombre'|'Mujer'|None), 'image_url' (str|None).
    Usa cache en memoria para evitar llamadas repetidas.
    """
    if sku_id in _sku_cache:
        return _sku_cache[sku_id]

    result = {"gender": None, "image_url": None}
    try:
        resp = requests.get(
            f"{BASE_CATALOG}/stockkeepingunit/{sku_id}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()

            # ── Imagen: primer elemento de Images ─────────────────────────
            images = data.get("Images") or []
            if images and isinstance(images, list):
                img = images[0]
                url = img.get("ImageUrl") or img.get("imageUrl") or ""
                result["image_url"] = url if url else None

            # ── Género: buscar en especificaciones del producto padre ──────
            # La especificación "Género" vive en el producto, no en el SKU.
            # Intentamos con ProductId para ir al producto.
            product_id = data.get("ProductId")
            if product_id:
                result["gender"] = _fetch_product_gender(str(product_id))

    except Exception:
        pass

    _sku_cache[sku_id] = result
    return result


_product_cache: dict = {}


def _fetch_product_gender(product_id: str) -> str | None:
    """
    Consulta las especificaciones del producto en el catálogo para
    obtener el género. Busca campos: Género, Genero, Gender, Sexo.
    """
    if product_id in _product_cache:
        return _product_cache[product_id]

    gender = None
    try:
        resp = requests.get(
            f"{BASE_CATALOG}/product/{product_id}/specification",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            specs = resp.json()  # lista de dicts con FieldName / Value
            for spec in (specs or []):
                name = str(spec.get("FieldName", "") or "").strip().lower()
                if name in ("género", "genero", "gender", "sexo"):
                    val = str((spec.get("Value") or [""])[0] if isinstance(spec.get("Value"), list) else spec.get("Value", "")).strip().lower()
                    if val in ("hombre", "masculino", "male", "m", "h"):
                        gender = "Hombre"
                    elif val in ("mujer", "femenino", "female", "f"):
                        gender = "Mujer"
                    elif val in ("unisex", "niño", "niña", "infantil"):
                        gender = val.title()
                    break
    except Exception:
        pass

    _product_cache[product_id] = gender
    return gender


def parse_orders(raw_orders, enrich_sample=150):
    """
    GMV = value / 100.
    Extrae ciudad de envío del pedido.
    Extrae género e imagen del catálogo de producto (por SKU).
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

            # Enriquecer con detalle
            detail = None
            if idx < enrich_sample:
                detail = fetch_order_detail(order_id)
                if detail:
                    o = detail
                time.sleep(0.12)

            # ── GMV ───────────────────────────────────────────────────────
            gmv_val = float(o.get("value", 0) or o.get("totalValue", 0) or 0) / 100

            # ── Descuentos y envío ────────────────────────────────────────
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
                    qty      = int(i.get("quantity", 0) or 0)
                    price    = float(i.get("sellingPrice", 0) or i.get("price", 0) or 0) / 100
                    sku_id_i = str(i.get("id", ""))
                    units   += qty
                    sku_ids.append(sku_id_i)

                    # Imagen desde imageUrl del item (disponible en detalle)
                    img_item = str(i.get("imageUrl", "") or "").strip()

                    item_rows.append({
                        "order_id":    order_id,
                        "marketplace": mp_name,
                        "sku_id":      sku_id_i,
                        "nombre":      str(i.get("name", "")),
                        "cantidad":    qty,
                        "precio_unit": price,
                        "valor_total": price * qty,
                        "image_url":   img_item if img_item else None,
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

            # ── Ciudad: de la dirección de envío del pedido ───────────────
            source = detail if detail else o
            city   = _extract_city(source)

            # ── Género: del catálogo del producto (primer SKU del pedido) ─
            # Se consulta solo para órdenes enriquecidas (tienen SKU ID real)
            gender = None
            if sku_ids:
                cat_info = fetch_sku_catalog_info(sku_ids[0])
                gender   = cat_info.get("gender")

            rows.append({
                "order_id":    order_id,
                "marketplace": mp_name,
                "created_at":  creation_raw,
                "fecha":       fecha_col,
                "status":      status_label,
                "status_raw":  raw_status,
                "gmv":         gmv_val,
                "discount":    discount_val,
                "shipping":    shipping_val,
                "total":       gmv_val,
                "units":       units,
                "sku_ids":     sku_ids,
                "items":       item_rows,
                "gender":      gender,
                "city":        city,
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

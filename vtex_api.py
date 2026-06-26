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
BASE_LOG  = "https://logistics.vtexcommercestable.com.br/api/logistics/pvt"

# ── Sufijos del orderId → nombre de marketplace ───────────────────────────────
# VTEX pone el sufijo DESPUÉS del último guion: 1234567890-01-DFT
# Ajusta estas claves si en tu cuenta usan sufijos distintos.
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
    """
    Extrae el marketplace a partir del sufijo del orderId.
    VTEX usa formatos como:
      - 1234567890-01-DFT   → sufijo = DFT
      - 1234567890-DFT-01   → sufijo = 01  ← INCORRECTO, por eso probamos todas las partes
    Probamos TODAS las partes del orderId y retornamos el primer match.
    """
    try:
        parts = str(order_id).upper().split("-")
        for part in parts:
            if part in MP_SUFFIX:
                return MP_SUFFIX[part]
        return "Propio"
    except Exception:
        return "Propio"


def fetch_orders(days_back: int = 30) -> list:
    """
    Descarga todas las órdenes del período con paginación completa.
    Incluye todos los estados relevantes.
    """
    date_from = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00.000Z")
    date_to   = datetime.utcnow().strftime("%Y-%m-%dT23:59:59.999Z")

    orders, page = [], 1

    while True:
        try:
            resp = requests.get(
                f"{BASE_OMS}/orders",
                headers=HEADERS,
                params={
                    # Sin filtro de status para traer TODAS las órdenes
                    # (si quieres filtrar, descomenta la línea siguiente)
                    # "f_status": "invoiced,handling,ready-for-handling,waiting-for-fulfillment,payment-approved,cancel",
                    "f_creationDate": f"creationDate:[{date_from} TO {date_to}]",
                    "per_page": 100,
                    "page":     page,
                    "orderBy":  "creationDate,desc",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data  = resp.json()
            batch = data.get("list", [])

            if not batch:
                break

            orders.extend(batch)

            paging      = data.get("paging", {})
            total_pages = paging.get("pages", 1)

            if page >= total_pages or page >= 50:   # aumentamos límite a 50 páginas = 5 000 órdenes
                break

            page += 1
            time.sleep(0.3)

        except requests.exceptions.HTTPError as e:
            st.error(f"Error HTTP en página {page}: {e.response.status_code} — {e.response.text[:300]}")
            break
        except Exception as e:
            st.error(f"Error al obtener órdenes página {page}: {e}")
            break

    return orders


def parse_orders(raw_orders: list) -> list:
    """
    Convierte la lista cruda de órdenes en filas limpias para el DataFrame.
    """
    rows = []
    for o in raw_orders:
        try:
            if not isinstance(o, dict):
                continue

            order_id = str(o.get("orderId") or o.get("id") or "")
            if not order_id:
                continue

            # Totales
            totals: dict[str, float] = {}
            for t in (o.get("totals") or []):
                if isinstance(t, dict):
                    totals[t.get("id", "")] = float(t.get("value", 0) or 0)

            # Items
            items   = o.get("items") or []
            units   = 0
            sku_ids = []
            for i in (items if isinstance(items, list) else []):
                if isinstance(i, dict):
                    units += int(i.get("quantity", 0) or 0)
                    raw_id = i.get("id") or i.get("productId") or ""
                    if raw_id:
                        sku_ids.append(str(raw_id))

            gmv      = float(totals.get("Items", 0)) / 100
            discount = abs(float(totals.get("Discounts", 0))) / 100
            shipping = float(totals.get("Shipping", 0)) / 100
            total    = float(o.get("value", 0) or 0) / 100

            rows.append({
                "order_id":    order_id,
                "marketplace": get_marketplace(order_id),
                "created_at":  str(o.get("creationDate", "")),
                "status":      str(o.get("status", "")),
                "gmv":         gmv,
                "discount":    discount,
                "shipping":    shipping,
                "total":       total,
                "units":       units,
                "sku_ids":     sku_ids,
            })
        except Exception:
            continue

    return rows


def fetch_inventory(sku_id: str) -> dict:
    """
    Consulta el stock disponible de un SKU en todos los almacenes.
    Retorna available = -1 si hubo error.
    """
    try:
        resp = requests.get(
            f"{BASE_LOG}/inventory/skus/{sku_id}",
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code == 200:
            data  = resp.json()
            total = sum(
                int(b.get("totalQuantity", 0) or 0) - int(b.get("reservedQuantity", 0) or 0)
                for b in (data.get("balance") or [])
                if isinstance(b, dict)
            )
            return {"sku_id": sku_id, "available": max(total, 0)}
    except Exception:
        pass
    return {"sku_id": sku_id, "available": -1}

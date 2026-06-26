import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from vtex_api import fetch_orders, parse_orders, fetch_inventory, MP_SUFFIX

# ── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Control Comercial VTEX",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilos CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stSidebar"] { background: #171b26; border-right: 1px solid rgba(255,255,255,0.07); }
[data-testid="metric-container"] {
    background: #171b26;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 12px 16px;
}
[data-testid="stMetricValue"] { color: #e8eaf2; font-size: 26px; font-weight: 700; }
[data-testid="stMetricLabel"] { color: #555a72; font-size: 11px; text-transform: uppercase; }
h1, h2, h3 { color: #e8eaf2 !important; }
.stSelectbox label { color: #8b90a7; }
div[data-testid="stPlotlyChart"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

PLOT_LAYOUT = dict(
    paper_bgcolor="#171b26",
    plot_bgcolor="#171b26",
    font_color="#8b90a7",
    title_font_color="#e8eaf2",
    showlegend=False,
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛍️ VTEX Control")
    st.markdown("**Colombia · Producción**")
    st.divider()

    dias = st.selectbox(
        "Período",
        options=[7, 14, 30, 60, 90],
        index=2,
        format_func=lambda x: f"Últimos {x} días",
    )

    mp_opciones = ["Todos"] + sorted(MP_SUFFIX.values())
    mp_sel = st.selectbox("Marketplace", mp_opciones)

    actualizar = st.button("↻ Actualizar datos", use_container_width=True)
    st.divider()
    st.caption(f"Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

# ── Carga de datos ────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Consultando API de VTEX…")
def cargar_datos(dias: int) -> pd.DataFrame:
    raw    = fetch_orders(days_back=dias)
    parsed = parse_orders(raw)
    if not parsed:
        return pd.DataFrame()
    df = pd.DataFrame(parsed)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df["fecha"]      = df["created_at"].dt.date
    return df


@st.cache_data(ttl=3600, show_spinner="Cargando detalle de productos…")
def cargar_items(dias: int) -> pd.DataFrame:
    """Explota los items de cada orden para análisis de producto."""
    from vtex_api import get_marketplace
    raw  = fetch_orders(days_back=dias)   # usa caché de Streamlit → no hace doble llamada
    rows = []
    for o in raw:
        if not isinstance(o, dict):
            continue
        mp    = get_marketplace(str(o.get("orderId") or o.get("id") or ""))
        items = o.get("items") or []
        for item in (items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            add_info  = item.get("additionalInfo") or {}
            categoria = add_info.get("categoriesIds", "") if isinstance(add_info, dict) else ""
            precio    = float(item.get("price",    0) or 0) / 100
            cantidad  = int(item.get("quantity", 0) or 0)
            rows.append({
                "marketplace": mp,
                "sku_id":      str(item.get("id") or ""),
                "nombre":      str(item.get("name") or "Sin nombre"),
                "categoria":   str(categoria),
                "cantidad":    cantidad,
                "precio_unit": precio,
                "valor_total": precio * cantidad,
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


if actualizar:
    st.cache_data.clear()

df_full = cargar_datos(dias)

# ── DEBUG: muestra marketplaces encontrados (descomenta si necesitas depurar) ──
# if not df_full.empty:
#     st.write("Marketplaces encontrados:", df_full["marketplace"].unique().tolist())
#     st.write("Ejemplo de order IDs:", df_full["order_id"].head(5).tolist())

if df_full.empty:
    st.warning(
        "No se encontraron órdenes para el período seleccionado. "
        "Verifica tus credenciales en Streamlit Secrets y que la cuenta VTEX tenga órdenes en este rango."
    )
    st.stop()

# ── Filtro por Marketplace ────────────────────────────────────────────────────
df = df_full.copy() if mp_sel == "Todos" else df_full[df_full["marketplace"] == mp_sel].copy()

if df.empty:
    st.info(f"Sin órdenes para **{mp_sel}** en los últimos {dias} días.")

    # ── DIAGNÓSTICO: muestra qué marketplaces SÍ tienen datos ────────────────
    with st.expander("🔍 Diagnóstico — Marketplaces con datos"):
        conteo = df_full["marketplace"].value_counts().reset_index()
        conteo.columns = ["Marketplace", "Órdenes"]
        st.dataframe(conteo, hide_index=True)
        st.caption("Si no ves el marketplace esperado, el sufijo del orderId puede no coincidir con MP_SUFFIX en vtex_api.py")
        st.code(df_full["order_id"].head(10).to_string(), language="text")

    st.stop()

# ── MÓDULO 1: KPIs ────────────────────────────────────────────────────────────
st.markdown(f"## {'Todos los Marketplaces' if mp_sel == 'Todos' else mp_sel}")
st.caption(f"Últimos {dias} días · {len(df):,} órdenes encontradas")

gmv_total   = df["gmv"].sum()
pedidos     = len(df)
descuentos  = df["discount"].sum()
ticket_prom = df["total"].mean() if pedidos > 0 else 0
unidades    = df["units"].sum()
pct_desc    = (descuentos / gmv_total * 100) if gmv_total > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("GMV Total",       f"${gmv_total:,.0f}")
c2.metric("Pedidos",         f"{pedidos:,}")
c3.metric("Descuentos",      f"${descuentos:,.0f}", f"{pct_desc:.1f}% del GMV")
c4.metric("Ticket Promedio", f"${ticket_prom:,.0f}")
c5.metric("Unidades",        f"{unidades:,}")
c6.metric("Tasa Descuento",  f"{pct_desc:.1f}%")

st.divider()

# ── MÓDULO 2: VENTAS Y DESCUENTOS ─────────────────────────────────────────────
st.markdown("### 📊 Ventas y Descuentos")
col1, col2 = st.columns(2)

with col1:
    gmv_mp = (
        df_full.groupby("marketplace")
        .agg(GMV=("gmv", "sum"), Pedidos=("order_id", "count"))
        .reset_index()
        .sort_values("GMV", ascending=False)
    )
    fig_gmv = px.bar(
        gmv_mp, x="marketplace", y="GMV",
        title="GMV por Marketplace",
        color="marketplace",
        color_discrete_sequence=px.colors.qualitative.Vivid,
        labels={"GMV": "GMV ($)", "marketplace": ""},
        text=gmv_mp["GMV"].apply(lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v:,.0f}"),
    )
    fig_gmv.update_traces(textposition="outside")
    fig_gmv.update_layout(**PLOT_LAYOUT)
    st.plotly_chart(fig_gmv, use_container_width=True)

with col2:
    desc_mp = (
        df_full.groupby("marketplace")
        .agg(Descuento=("discount", "sum"), GMV=("gmv", "sum"))
        .reset_index()
    )
    desc_mp["Pct"] = desc_mp.apply(
        lambda r: r["Descuento"] / r["GMV"] * 100 if r["GMV"] > 0 else 0, axis=1
    )
    desc_mp = desc_mp.sort_values("Pct", ascending=False)

    fig_desc = px.bar(
        desc_mp, x="marketplace", y="Pct",
        title="Descuento como % del GMV por Canal",
        color="Pct",
        color_continuous_scale="RdYlGn_r",
        labels={"Pct": "% Descuento", "marketplace": ""},
        text=desc_mp["Pct"].apply(lambda v: f"{v:.1f}%"),
    )
    fig_desc.update_traces(textposition="outside")
    fig_desc.update_layout(**PLOT_LAYOUT, coloraxis_showscale=False)
    st.plotly_chart(fig_desc, use_container_width=True)

# Tendencia diaria
tend = df.groupby("fecha").agg(
    Pedidos=("order_id", "count"),
    GMV=("gmv", "sum"),
).reset_index()

fig_tend = px.line(
    tend, x="fecha", y="GMV",
    title=f"Tendencia GMV diario — {mp_sel}",
    labels={"fecha": "", "GMV": "GMV ($)"},
    color_discrete_sequence=["#FF3560"],
)
fig_tend.update_traces(fill="tozeroy", fillcolor="rgba(255,53,96,0.08)")
fig_tend.update_layout(**PLOT_LAYOUT)
st.plotly_chart(fig_tend, use_container_width=True)

st.divider()

# ── MÓDULO 3: INVENTARIO ──────────────────────────────────────────────────────
st.markdown("### 📦 Disponibilidad de Inventario")
st.info(
    "Para ver el inventario en tiempo real, el sistema consulta la Logistics API de VTEX "
    "con los SKUs de las órdenes del período. Esto puede tomar unos segundos adicionales según el volumen."
)

if "sku_ids" in df.columns:
    all_skus = []
    for row in df["sku_ids"]:
        if isinstance(row, list):
            all_skus.extend(row)
    skus_unicos = list(set(filter(None, all_skus)))[:50]

    label = f"Consultar inventario de {len(skus_unicos)} SKUs"
    if st.button(label, disabled=len(skus_unicos) == 0):
        with st.spinner("Consultando Logistics API…"):
            inv_data = [fetch_inventory(s) for s in skus_unicos]

        df_inv = pd.DataFrame(inv_data)
        df_inv["estado"] = df_inv["available"].apply(
            lambda x: "🔴 Sin stock" if x == 0 else ("🟡 Crítico (<10)" if x < 10 else "🟢 OK")
        )

        criticos = df_inv[df_inv["available"] <= 0]
        bajos    = df_inv[(df_inv["available"] > 0) & (df_inv["available"] < 10)]

        a1, a2, a3 = st.columns(3)
        a1.metric("SKUs sin stock",    len(criticos), delta_color="inverse")
        a2.metric("SKUs stock bajo",   len(bajos),    delta_color="inverse")
        a3.metric("SKUs con stock OK", len(df_inv) - len(criticos) - len(bajos))

        st.dataframe(
            df_inv.sort_values("available").rename(columns={
                "sku_id":    "SKU",
                "available": "Stock disponible",
                "estado":    "Estado",
            }),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ── MÓDULO 4: RENDIMIENTO DE PRODUCTOS ───────────────────────────────────────
st.markdown("### 🏆 Rendimiento de Productos")

df_items = cargar_items(dias)

if not df_items.empty:
    df_items_f = df_items if mp_sel == "Todos" else df_items[df_items["marketplace"] == mp_sel]

    if df_items_f.empty:
        st.info("No se encontró detalle de productos para el período y filtro seleccionados.")
    else:
        col_a, col_b = st.columns(2)

        with col_a:
            top_u = (
                df_items_f.groupby("nombre")["cantidad"]
                .sum().reset_index()
                .sort_values("cantidad", ascending=False).head(10)
            )
            fig_top_u = px.bar(
                top_u, x="cantidad", y="nombre", orientation="h",
                title="Top 10 productos — Unidades vendidas",
                color_discrete_sequence=["#4f87ff"],
                labels={"cantidad": "Unidades", "nombre": ""},
            )
            fig_top_u.update_layout(**PLOT_LAYOUT, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_top_u, use_container_width=True)

        with col_b:
            top_v = (
                df_items_f.groupby("nombre")["valor_total"]
                .sum().reset_index()
                .sort_values("valor_total", ascending=False).head(10)
            )
            fig_top_v = px.bar(
                top_v, x="valor_total", y="nombre", orientation="h",
                title="Top 10 productos — Valor ($)",
                color_discrete_sequence=["#22c77a"],
                labels={"valor_total": "Valor ($)", "nombre": ""},
            )
            fig_top_v.update_layout(**PLOT_LAYOUT, yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_top_v, use_container_width=True)

        mix = df_items_f.groupby("marketplace")["valor_total"].sum().reset_index()
        fig_mix = px.pie(
            mix, values="valor_total", names="marketplace",
            title="Mix de ventas por Marketplace",
            color_discrete_sequence=px.colors.qualitative.Vivid,
            hole=0.5,
        )
        fig_mix.update_layout(paper_bgcolor="#171b26", font_color="#8b90a7", title_font_color="#e8eaf2")
        st.plotly_chart(fig_mix, use_container_width=True)
else:
    st.info("No se encontró detalle de productos para el período y filtro seleccionados.")

st.divider()
st.caption("VTEX Control Comercial · Colombia · Datos en tiempo real vía Order Management API, Logistics API y Catalog API")

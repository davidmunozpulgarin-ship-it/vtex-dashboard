import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from vtex_api import fetch_orders, parse_orders, MP_SUFFIX

# ── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Control Comercial VTEX",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilos CSS personalizados ────────────────────────────────────────────────
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
[data-testid="stMetricDelta"] { font-size: 11px; }
h1, h2, h3 { color: #e8eaf2 !important; }
.stSelectbox label { color: #8b90a7; }
div[data-testid="stPlotlyChart"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

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

    mp_opciones = ["Todos"] + list(MP_SUFFIX.values())
    mp_sel = st.selectbox("Marketplace", mp_opciones)

    actualizar = st.button("↻ Actualizar datos", use_container_width=True)
    st.divider()
    st.caption(f"Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    st.caption("🟢 API VTEX conectada")

# ── Carga de datos con caché (se refresca cada 1 hora) ───────────────────────
@st.cache_data(ttl=3600, show_spinner="Consultando API de VTEX…")
def cargar_datos(dias: int):
    raw    = fetch_orders(days_back=dias)
    parsed = parse_orders(raw)
    df     = pd.DataFrame(parsed)
    if df.empty:
        return df
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df["fecha"]      = df["created_at"].dt.date
    return df

if actualizar:
    st.cache_data.clear()

df_full = cargar_datos(dias)

if df_full.empty:
    st.warning("No se encontraron órdenes para el período seleccionado. Verifica tus credenciales y el nombre de la cuenta en Streamlit Secrets.")
    st.stop()

# ── Filtro por Marketplace ────────────────────────────────────────────────────
if mp_sel == "Todos":
    df = df_full.copy()
else:
    df = df_full[df_full["marketplace"] == mp_sel].copy()

if df.empty:
    st.info(f"Sin órdenes para **{mp_sel}** en los últimos {dias} días.")
    st.stop()

# ── MÓDULO 1: KPIs ───────────────────────────────────────────────────────────
st.markdown(f"## {'Todos los Marketplaces' if mp_sel == 'Todos' else mp_sel}")
st.caption(f"Últimos {dias} días · {len(df):,} órdenes encontradas")

gmv_total   = df["gmv"].sum()
pedidos     = len(df)
descuentos  = df["discount"].sum()
ticket_prom = df["total"].mean()
unidades    = df["units"].sum()
pct_desc    = (descuentos / gmv_total * 100) if gmv_total > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("GMV Total",      f"${gmv_total:,.0f}")
c2.metric("Pedidos",        f"{pedidos:,}")
c3.metric("Descuentos",     f"${descuentos:,.0f}", f"{pct_desc:.1f}% del GMV")
c4.metric("Ticket Promedio",f"${ticket_prom:,.0f}")
c5.metric("Unidades",       f"{unidades:,}")
c6.metric("Tasa Descuento", f"{pct_desc:.1f}%")

st.divider()

# ── MÓDULO 2: VENTAS Y DESCUENTOS ────────────────────────────────────────────
st.markdown("### 📊 Ventas y Descuentos")
col1, col2 = st.columns(2)

with col1:
    # GMV por Marketplace
    gmv_mp = df_full.groupby("marketplace").agg(
        GMV=("gmv", "sum"),
        Pedidos=("order_id", "count")
    ).reset_index().sort_values("GMV", ascending=False)

    fig_gmv = px.bar(
        gmv_mp, x="marketplace", y="GMV",
        title="GMV por Marketplace",
        color="marketplace",
        color_discrete_sequence=px.colors.qualitative.Vivid,
        labels={"GMV": "GMV ($)", "marketplace": ""},
        text=gmv_mp["GMV"].apply(lambda v: f"${v/1e6:.1f}M"),
    )
    fig_gmv.update_traces(textposition="outside")
    fig_gmv.update_layout(
        paper_bgcolor="#171b26", plot_bgcolor="#171b26",
        font_color="#8b90a7", showlegend=False,
        title_font_color="#e8eaf2",
    )
    st.plotly_chart(fig_gmv, use_container_width=True)

with col2:
    # Descuentos por Marketplace
    desc_mp = df_full.groupby("marketplace").agg(
        Descuento=("discount", "sum"),
        GMV=("gmv", "sum")
    ).reset_index()
    desc_mp["Pct"] = desc_mp["Descuento"] / desc_mp["GMV"] * 100
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
    fig_desc.update_layout(
        paper_bgcolor="#171b26", plot_bgcolor="#171b26",
        font_color="#8b90a7", showlegend=False,
        title_font_color="#e8eaf2", coloraxis_showscale=False,
    )
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
fig_tend.update_layout(
    paper_bgcolor="#171b26", plot_bgcolor="#171b26",
    font_color="#8b90a7", title_font_color="#e8eaf2",
)
st.plotly_chart(fig_tend, use_container_width=True)
st.divider()

# ── MÓDULO 3: INVENTARIO ─────────────────────────────────────────────────────
st.markdown("### 📦 Disponibilidad de Inventario")
st.info("Para ver el inventario en tiempo real, el sistema consulta la Logistics API de VTEX con los SKUs de las órdenes del período. Esto puede tomar unos segundos adicionales según el volumen.")

# Extraer SKUs únicos de las órdenes
if "sku_ids" in df.columns:
    all_skus = []
    for row in df["sku_ids"]:
        if isinstance(row, list):
            all_skus.extend(row)
    skus_unicos = list(set(all_skus))[:50]  # limitamos a 50 para no sobrecargar la API

    if st.button(f"Consultar inventario de {len(skus_unicos)} SKUs"):
        from vtex_api import fetch_inventory
        with st.spinner("Consultando Logistics API…"):
            inv_data = [fetch_inventory(s) for s in skus_unicos]
        df_inv = pd.DataFrame(inv_data)
        df_inv["estado"] = df_inv["available"].apply(
            lambda x: "🔴 Sin stock" if x == 0 else "🟡 Crítico (<10)" if x < 10 else "🟢 OK"
        )
        criticos = df_inv[df_inv["available"] <= 0]
        bajos    = df_inv[(df_inv["available"] > 0) & (df_inv["available"] < 10)]

        a1, a2, a3 = st.columns(3)
        a1.metric("SKUs sin stock",   len(criticos), delta_color="inverse")
        a2.metric("SKUs stock bajo",  len(bajos),    delta_color="inverse")
        a3.metric("SKUs con stock OK",len(df_inv) - len(criticos) - len(bajos))
        st.dataframe(
            df_inv.sort_values("available").rename(columns={"sku_id":"SKU","available":"Stock disponible","estado":"Estado"}),
            use_container_width=True, hide_index=True,
        )

st.divider()

# ── MÓDULO 4: PRODUCTOS Y CATEGORÍAS ─────────────────────────────────────────
st.markdown("### 🏆 Rendimiento de Productos")

# Para productos necesitamos explotar los items de las órdenes
# En la API de órdenes, el campo "items" trae nombre, SKU, cantidad y precio
@st.cache_data(ttl=3600, show_spinner="Cargando detalle de productos…")
def cargar_items(dias: int):
    from vtex_api import fetch_orders
    raw = fetch_orders(days_back=dias)
    rows = []
    for o in raw:
        mp = __import__('vtex_api').get_marketplace(o.get("orderId",""))
        items = o.get("items") or []
for item in items:
            rows.append({
                "marketplace":   mp,
                "sku_id":        item.get("id",""),
                "nombre":        item.get("name",""),
                "categoria":     item.get("additionalInfo",{}).get("categoriesIds",""),
                "cantidad":      item.get("quantity", 0),
                "precio_unit":   item.get("price", 0) / 100,
                "valor_total":   item.get("price", 0) / 100 * item.get("quantity", 0),
            })
    return pd.DataFrame(rows)

df_items = cargar_items(dias)
if not df_items.empty:
    if mp_sel != "Todos":
        df_items = df_items[df_items["marketplace"] == mp_sel]

    col_a, col_b = st.columns(2)

    with col_a:
        top_u = (
            df_items.groupby("nombre")["cantidad"]
            .sum().reset_index()
            .sort_values("cantidad", ascending=False).head(10)
        )
        fig_top_u = px.bar(
            top_u, x="cantidad", y="nombre", orientation="h",
            title="Top 10 productos — Unidades vendidas",
            color_discrete_sequence=["#4f87ff"],
            labels={"cantidad": "Unidades", "nombre": ""},
        )
        fig_top_u.update_layout(
            paper_bgcolor="#171b26", plot_bgcolor="#171b26",
            font_color="#8b90a7", title_font_color="#e8eaf2",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_top_u, use_container_width=True)

    with col_b:
        top_v = (
            df_items.groupby("nombre")["valor_total"]
            .sum().reset_index()
            .sort_values("valor_total", ascending=False).head(10)
        )
        fig_top_v = px.bar(
            top_v, x="valor_total", y="nombre", orientation="h",
            title="Top 10 productos — Valor ($)",
            color_discrete_sequence=["#22c77a"],
            labels={"valor_total": "Valor ($)", "nombre": ""},
        )
        fig_top_v.update_layout(
            paper_bgcolor="#171b26", plot_bgcolor="#171b26",
            font_color="#8b90a7", title_font_color="#e8eaf2",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_top_v, use_container_width=True)

    # Distribución por Marketplace
    mix = df_items.groupby("marketplace")["valor_total"].sum().reset_index()
    fig_mix = px.pie(
        mix, values="valor_total", names="marketplace",
        title="Mix de ventas por Marketplace",
        color_discrete_sequence=px.colors.qualitative.Vivid,
        hole=0.5,
    )
    fig_mix.update_layout(
        paper_bgcolor="#171b26", font_color="#8b90a7",
        title_font_color="#e8eaf2",
    )
    st.plotly_chart(fig_mix, use_container_width=True)
else:
    st.info("No se encontró detalle de productos para el período y filtro seleccionados.")

st.divider()
st.caption("VTEX Control Comercial · Colombia · Datos en tiempo real vía Order Management API, Logistics API y Catalog API")

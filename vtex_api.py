import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from vtex_api import fetch_orders, parse_orders, MP_SUFFIX, fetch_inventory

st.set_page_config(
    page_title="Control Comercial VTEX",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stSidebar"] { background: #171b26; }
section[data-testid="stSidebar"] * { color: #e8eaf2; }
[data-testid="metric-container"] {
    background: #171b26;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 14px 18px;
}
[data-testid="stMetricValue"] { color: #e8eaf2 !important; font-size: 24px !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] { color: #8b90a7 !important; font-size: 11px !important; text-transform: uppercase; }
h1,h2,h3,h4 { color: #e8eaf2 !important; }
p, li { color: #8b90a7; }
.stAlert { border-radius: 10px; }
div[data-testid="stPlotlyChart"] { border-radius: 12px; overflow: hidden; }
.stDataFrame { border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛍️ VTEX Control")
    st.markdown("**Colombia · Producción**")
    st.divider()

    st.markdown("#### 📅 Rango de fechas")
    preset = st.selectbox(
        "Período rápido",
        ["Personalizado", "Hoy", "Últimos 7 días", "Últimos 15 días",
         "Últimos 30 días", "Este mes", "Mes anterior", "Últimos 90 días"],
        index=4,
    )

    hoy = date.today()
    if preset == "Hoy":
        default_from, default_to = hoy, hoy
    elif preset == "Últimos 7 días":
        default_from, default_to = hoy - timedelta(days=6), hoy
    elif preset == "Últimos 15 días":
        default_from, default_to = hoy - timedelta(days=14), hoy
    elif preset == "Últimos 30 días":
        default_from, default_to = hoy - timedelta(days=29), hoy
    elif preset == "Este mes":
        default_from = hoy.replace(day=1)
        default_to   = hoy
    elif preset == "Mes anterior":
        primer_dia_mes = hoy.replace(day=1)
        ultimo_mes     = primer_dia_mes - timedelta(days=1)
        default_from   = ultimo_mes.replace(day=1)
        default_to     = ultimo_mes
    elif preset == "Últimos 90 días":
        default_from, default_to = hoy - timedelta(days=89), hoy
    else:
        default_from, default_to = hoy - timedelta(days=29), hoy

    fecha_desde = st.date_input("Desde", value=default_from, max_value=hoy)
    fecha_hasta = st.date_input("Hasta", value=default_to,   max_value=hoy)

    if fecha_desde > fecha_hasta:
        st.error("La fecha 'Desde' no puede ser mayor que 'Hasta'.")
        st.stop()

    st.divider()
    st.markdown("#### 🏪 Marketplace")
    mp_opciones = ["Todos"] + sorted(MP_SUFFIX.values())
    mp_sel = st.selectbox("Filtrar por canal", mp_opciones)

    st.divider()
    cargar = st.button("🔄 Cargar datos", use_container_width=True, type="primary")
    st.caption(f"Cuenta: **{st.secrets.get('VTEX_ACCOUNT', '—')}**")
    st.caption(f"🟢 API conectada")

# ── CARGA DE DATOS ────────────────────────────────────────────────────────────
fecha_desde_str = fecha_desde.strftime("%Y-%m-%d")
fecha_hasta_str = fecha_hasta.strftime("%Y-%m-%d")
cache_key       = f"{fecha_desde_str}_{fecha_hasta_str}"

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_datos(key, f_desde, f_hasta):
    with st.spinner(f"📡 Consultando VTEX ({f_desde} → {f_hasta})..."):
        raw    = fetch_orders(f_desde, f_hasta)
        parsed = parse_orders(raw, fetch_details=False)
    df = pd.DataFrame(parsed) if parsed else pd.DataFrame()
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df["fecha"]      = df["created_at"].dt.date
    return df

if cargar:
    st.cache_data.clear()

if "df_loaded" not in st.session_state or cargar:
    st.session_state["df_loaded"] = cargar_datos(cache_key, fecha_desde_str, fecha_hasta_str)

df_full = st.session_state.get("df_loaded", pd.DataFrame())

if df_full.empty:
    st.warning("⚠️ No se encontraron órdenes para el rango seleccionado. Ajusta las fechas o verifica las credenciales.")
    st.info("Haz clic en **Cargar datos** para consultar la API de VTEX.")
    st.stop()

# ── FILTRO MARKETPLACE ────────────────────────────────────────────────────────
df = df_full.copy() if mp_sel == "Todos" else df_full[df_full["marketplace"] == mp_sel].copy()

if df.empty:
    st.info(f"Sin órdenes para **{mp_sel}** en el período seleccionado.")
    st.stop()

dias_rango = (fecha_hasta - fecha_desde).days + 1
titulo     = "Todos los Marketplaces" if mp_sel == "Todos" else mp_sel

# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown(f"## {titulo}")
st.caption(f"{fecha_desde.strftime('%d/%m/%Y')} → {fecha_hasta.strftime('%d/%m/%Y')} · **{len(df):,}** órdenes · {dias_rango} días")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
gmv_total   = df["gmv"].sum()
pedidos     = len(df)
descuentos  = df["discount"].sum()
ticket_prom = df["total"].mean() if pedidos > 0 else 0
unidades    = df["units"].sum()
pct_desc    = (descuentos / gmv_total * 100) if gmv_total > 0 else 0
gmv_dia     = gmv_total / dias_rango if dias_rango > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("💰 GMV Total",       f"${gmv_total:,.0f}")
c2.metric("🛒 Pedidos",         f"{pedidos:,}")
c3.metric("🎟️ Descuentos",      f"${descuentos:,.0f}", f"{pct_desc:.1f}% del GMV")
c4.metric("🧾 Ticket Promedio", f"${ticket_prom:,.0f}")
c5.metric("📦 Unidades",        f"{unidades:,}")
c6.metric("📈 GMV / Día",       f"${gmv_dia:,.0f}")

st.divider()

# ── MÓDULO 1: VENTAS Y DESCUENTOS ────────────────────────────────────────────
st.markdown("### 📊 Ventas y Descuentos")

col1, col2 = st.columns(2)
with col1:
    gmv_mp = df_full.groupby("marketplace").agg(
        GMV=("gmv", "sum"),
        Pedidos=("order_id", "count")
    ).reset_index().sort_values("GMV", ascending=False)

    if mp_sel != "Todos":
        gmv_mp["highlight"] = gmv_mp["marketplace"].apply(lambda x: "Seleccionado" if x == mp_sel else "Otros")
        color_map = {"Seleccionado": "#FF3560", "Otros": "#2d3250"}
        fig_gmv = px.bar(
            gmv_mp, x="marketplace", y="GMV",
            color="highlight", color_discrete_map=color_map,
            title="GMV por Marketplace",
            labels={"GMV": "GMV ($)", "marketplace": ""},
            text=gmv_mp["GMV"].apply(lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"),
        )
    else:
        fig_gmv = px.bar(
            gmv_mp, x="marketplace", y="GMV",
            color="marketplace",
            color_discrete_sequence=["#FF3560","#4f87ff","#22c77a","#f5a524","#a78bfa","#34d399","#eab308","#f03e3e","#fb923c","#c084fc"],
            title="GMV por Marketplace",
            labels={"GMV": "GMV ($)", "marketplace": ""},
            text=gmv_mp["GMV"].apply(lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"),
        )
    fig_gmv.update_traces(textposition="outside")
    fig_gmv.update_layout(
        paper_bgcolor="#171b26", plot_bgcolor="#171b26",
        font_color="#8b90a7", showlegend=False,
        title_font_color="#e8eaf2", height=350,
    )
    st.plotly_chart(fig_gmv, use_container_width=True)

with col2:
    desc_mp = df_full.groupby("marketplace").agg(
        Descuento=("discount", "sum"),
        GMV=("gmv", "sum")
    ).reset_index()
    desc_mp["Pct"] = desc_mp.apply(
        lambda r: r["Descuento"] / r["GMV"] * 100 if r["GMV"] > 0 else 0, axis=1
    )
    desc_mp = desc_mp.sort_values("Pct", ascending=True)

    fig_desc = px.bar(
        desc_mp, x="Pct", y="marketplace", orientation="h",
        title="Descuento como % del GMV",
        color="Pct", color_continuous_scale="RdYlGn_r",
        labels={"Pct": "% Descuento", "marketplace": ""},
        text=desc_mp["Pct"].apply(lambda v: f"{v:.1f}%"),
    )
    fig_desc.update_traces(textposition="outside")
    fig_desc.update_layout(
        paper_bgcolor="#171b26", plot_bgcolor="#171b26",
        font_color="#8b90a7", showlegend=False,
        title_font_color="#e8eaf2", height=350,
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig_desc, use_container_width=True)

# Tendencia diaria
tend = df.groupby("fecha").agg(
    Pedidos=("order_id", "count"),
    GMV=("gmv", "sum"),
    Descuentos=("discount", "sum"),
).reset_index()
tend["fecha"] = pd.to_datetime(tend["fecha"])

fig_tend = go.Figure()
fig_tend.add_trace(go.Scatter(
    x=tend["fecha"], y=tend["GMV"],
    mode="lines", name="GMV",
    line=dict(color="#FF3560", width=2),
    fill="tozeroy", fillcolor="rgba(255,53,96,0.08)",
))
fig_tend.add_trace(go.Scatter(
    x=tend["fecha"], y=tend["Descuentos"],
    mode="lines", name="Descuentos",
    line=dict(color="#f5a524", width=2, dash="dot"),
))
fig_tend.update_layout(
    title=f"Tendencia diaria — {titulo}",
    paper_bgcolor="#171b26", plot_bgcolor="#171b26",
    font_color="#8b90a7", title_font_color="#e8eaf2",
    legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    height=300,
)
st.plotly_chart(fig_tend, use_container_width=True)

# Participación GMV (solo si es "Todos")
if mp_sel == "Todos" and len(gmv_mp) > 1:
    col_a, col_b = st.columns([1, 2])
    with col_a:
        fig_pie = px.pie(
            gmv_mp, values="GMV", names="marketplace",
            title="Mix GMV por Canal",
            color_discrete_sequence=["#FF3560","#4f87ff","#22c77a","#f5a524","#a78bfa","#34d399","#eab308","#f03e3e","#fb923c","#c084fc"],
            hole=0.5,
        )
        fig_pie.update_layout(
            paper_bgcolor="#171b26", font_color="#8b90a7",
            title_font_color="#e8eaf2", height=320,
            legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_b:
        st.markdown("##### Resumen por Marketplace")
        resumen = df_full.groupby("marketplace").agg(
            GMV=("gmv", "sum"),
            Pedidos=("order_id", "count"),
            Descuentos=("discount", "sum"),
            Unidades=("units", "sum"),
        ).reset_index().sort_values("GMV", ascending=False)
        resumen["Ticket Prom."] = (resumen["GMV"] / resumen["Pedidos"]).round(0)
        resumen["% Desc."]      = (resumen["Descuentos"] / resumen["GMV"] * 100).round(1)
        resumen["GMV"]          = resumen["GMV"].apply(lambda v: f"${v:,.0f}")
        resumen["Descuentos"]   = resumen["Descuentos"].apply(lambda v: f"${v:,.0f}")
        resumen["Ticket Prom."] = resumen["Ticket Prom."].apply(lambda v: f"${v:,.0f}")
        resumen["% Desc."]      = resumen["% Desc."].apply(lambda v: f"{v}%")
        resumen = resumen.rename(columns={"marketplace": "Marketplace"})
        st.dataframe(resumen, use_container_width=True, hide_index=True)

st.divider()

# ── MÓDULO 2: INVENTARIO ──────────────────────────────────────────────────────
st.markdown("### 📦 Disponibilidad de Inventario")

all_skus = []
for row in df["sku_ids"]:
    if isinstance(row, list):
        all_skus.extend(row)
skus_unicos = [s for s in list(set(all_skus)) if s][:50]

if skus_unicos:
    if st.button(f"🔍 Consultar inventario ({len(skus_unicos)} SKUs únicos)", type="secondary"):
        with st.spinner("Consultando Logistics API de VTEX..."):
            inv_data = [fetch_inventory(s) for s in skus_unicos]
        df_inv = pd.DataFrame(inv_data)
        df_inv["Estado"] = df_inv["available"].apply(
            lambda x: "🔴 Sin stock" if x == 0 else "🟡 Crítico (<10)" if x < 10 else "🟢 OK"
        )
        i1, i2, i3 = st.columns(3)
        criticos = len(df_inv[df_inv["available"] <= 0])
        bajos    = len(df_inv[(df_inv["available"] > 0) & (df_inv["available"] < 10)])
        ok       = len(df_inv) - criticos - bajos
        i1.metric("🔴 Sin stock",  criticos)
        i2.metric("🟡 Stock bajo", bajos)
        i3.metric("🟢 Stock OK",   ok)
        st.dataframe(
            df_inv.rename(columns={"sku_id": "SKU", "available": "Stock disponible"}),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("Carga datos primero para consultar el inventario de los SKUs en las órdenes.")

st.divider()

# ── MÓDULO 3: PRODUCTOS Y CATEGORÍAS ─────────────────────────────────────────
st.markdown("### 🏆 Rendimiento de Productos")

# Explotar items de las ordenes
item_rows = []
for _, row in df.iterrows():
    if isinstance(row.get("items"), list):
        for it in row["items"]:
            if isinstance(it, dict):
                item_rows.append(it)

if item_rows:
    df_items = pd.DataFrame(item_rows)

    col1, col2 = st.columns(2)
    with col1:
        top_u = (
            df_items.groupby("nombre")["cantidad"]
            .sum().reset_index()
            .sort_values("cantidad", ascending=True).tail(10)
        )
        fig_tu = px.bar(
            top_u, x="cantidad", y="nombre", orientation="h",
            title="Top 10 productos — Unidades vendidas",
            color_discrete_sequence=["#4f87ff"],
            labels={"cantidad": "Unidades", "nombre": ""},
            text="cantidad",
        )
        fig_tu.update_layout(
            paper_bgcolor="#171b26", plot_bgcolor="#171b26",
            font_color="#8b90a7", title_font_color="#e8eaf2", height=380,
        )
        st.plotly_chart(fig_tu, use_container_width=True)

    with col2:
        top_v = (
            df_items.groupby("nombre")["valor_total"]
            .sum().reset_index()
            .sort_values("valor_total", ascending=True).tail(10)
        )
        fig_tv = px.bar(
            top_v, x="valor_total", y="nombre", orientation="h",
            title="Top 10 productos — Valor ($)",
            color_discrete_sequence=["#22c77a"],
            labels={"valor_total": "Valor ($)", "nombre": ""},
            text=top_v["valor_total"].apply(lambda v: f"${v:,.0f}"),
        )
        fig_tv.update_layout(
            paper_bgcolor="#171b26", plot_bgcolor="#171b26",
            font_color="#8b90a7", title_font_color="#e8eaf2", height=380,
        )
        st.plotly_chart(fig_tv, use_container_width=True)

    # Tabla resumen de productos
    with st.expander("📋 Ver tabla completa de productos"):
        tabla_prod = (
            df_items.groupby(["sku_id", "nombre"]).agg(
                Unidades=("cantidad", "sum"),
                Valor=("valor_total", "sum"),
                Pedidos=("order_id", "nunique"),
            ).reset_index().sort_values("Valor", ascending=False)
        )
        tabla_prod["Valor"]      = tabla_prod["Valor"].apply(lambda v: f"${v:,.0f}")
        tabla_prod["Precio Unit"] = (
            df_items.groupby("nombre")["precio_unit"].mean()
            .reindex(tabla_prod["nombre"]).values
        )
        tabla_prod["Precio Unit"] = tabla_prod["Precio Unit"].apply(
            lambda v: f"${v:,.0f}" if pd.notna(v) else "—"
        )
        st.dataframe(
            tabla_prod.rename(columns={"sku_id": "SKU", "nombre": "Producto"}),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("El detalle de productos se carga con los ítems de las órdenes. "
            "Activa **fetch_details=True** en vtex_api.py para obtener datos completos por orden.")

st.divider()

# ── MÓDULO 4: DETALLE DE ÓRDENES ─────────────────────────────────────────────
with st.expander("🗂️ Ver tabla de órdenes completa"):
    cols_show = ["order_id", "marketplace", "fecha", "status", "gmv", "discount", "total", "units"]
    df_show   = df[cols_show].copy()
    df_show["gmv"]      = df_show["gmv"].apply(lambda v: f"${v:,.0f}")
    df_show["discount"] = df_show["discount"].apply(lambda v: f"${v:,.0f}")
    df_show["total"]    = df_show["total"].apply(lambda v: f"${v:,.0f}")
    st.dataframe(
        df_show.rename(columns={
            "order_id": "Orden", "marketplace": "Marketplace", "fecha": "Fecha",
            "status": "Estado", "gmv": "GMV", "discount": "Descuento",
            "total": "Total", "units": "Unidades"
        }),
        use_container_width=True, hide_index=True,
    )

st.divider()
st.caption(
    f"VTEX Control Comercial · Cuenta: {st.secrets.get('VTEX_ACCOUNT', '—')} · "
    f"Datos: {fecha_desde.strftime('%d/%m/%Y')} → {fecha_hasta.strftime('%d/%m/%Y')}"
)

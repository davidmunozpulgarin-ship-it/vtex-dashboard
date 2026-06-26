import os
import json
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from vtex_api import fetch_orders, parse_orders, MP_SUFFIX, fetch_inventory, STATUS_LABEL

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
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stMultiSelect label,
section[data-testid="stSidebar"] .stDateInput label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div { color: #e8eaf2 !important; }
section[data-testid="stSidebar"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] [data-baseweb="tag"] {
    color: #e8eaf2 !important;
    background-color: #232738 !important;
}
section[data-testid="stSidebar"] input {
    color: #e8eaf2 !important;
    background-color: #232738 !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 6px !important;
}
[data-baseweb="popover"] { background: #232738 !important; }
[data-baseweb="menu"] li { color: #e8eaf2 !important; }
[data-baseweb="menu"] li:hover { background: #2e3347 !important; }
[data-testid="metric-container"] {
    background: #171b26;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 14px 18px;
}
[data-testid="stMetricValue"] { color: #e8eaf2 !important; font-size: 22px !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] { color: #8b90a7 !important; font-size: 11px !important; text-transform: uppercase; }
h1,h2,h3,h4 { color: #e8eaf2 !important; }
div[data-testid="stPlotlyChart"] { border-radius: 12px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

COLORS = ["#FF3560","#4f87ff","#22c77a","#f5a524","#a78bfa","#34d399","#eab308","#f03e3e","#fb923c","#c084fc"]
PLOT_BASE = dict(paper_bgcolor="#171b26", plot_bgcolor="#171b26", font_color="#8b90a7", title_font_color="#e8eaf2", showlegend=False)

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# ── PRESUPUESTOS: persistencia simple en archivo JSON local ─────────────────
PRESUPUESTOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presupuestos.json")


def cargar_presupuestos() -> dict:
    try:
        with open(PRESUPUESTOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_presupuesto(mes_key: str, valor: float) -> bool:
    data = cargar_presupuestos()
    data[mes_key] = float(valor)
    try:
        with open(PRESUPUESTOS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def obtener_presupuesto_rango(f_desde: date, f_hasta: date, presupuestos: dict) -> float:
    total  = 0.0
    actual = f_desde
    while actual <= f_hasta:
        year, month = actual.year, actual.month
        siguiente_mes = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        fin_mes      = siguiente_mes - timedelta(days=1)
        fin_tramo    = min(fin_mes, f_hasta)
        dias_tramo   = (fin_tramo - actual).days + 1
        dias_mes     = (fin_mes - date(year, month, 1)).days + 1
        mes_key      = f"{year}-{month:02d}"
        presupuesto_mes = presupuestos.get(mes_key, 0.0)
        total += presupuesto_mes * (dias_tramo / dias_mes)
        actual = fin_tramo + timedelta(days=1)
    return total


def shift_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year - 1)


# ── NUEVO: sección de detalle por marketplace ─────────────────────────────────
def render_marketplace_detail(df_mp: pd.DataFrame, mp_name: str):
    """
    Renderiza la sección de detalle exclusivo cuando se selecciona
    un marketplace específico. Muestra ventas por género y ciudades
    de mayor participación.
    No toca ningún código existente; se llama justo antes del header
    cuando mp_sel != 'Todos'.
    """
    st.markdown(f"### 🔍 Detalle Exclusivo — {mp_name}")
    st.caption("Información detallada únicamente de este canal de venta")

    # Agregar columnas si no existen (cache viejo sin estos campos)
    if "gender" not in df_mp.columns:
        df_mp = df_mp.copy()
        df_mp["gender"] = None
    if "city" not in df_mp.columns:
        df_mp = df_mp.copy()
        df_mp["city"] = None

    col_g, col_c = st.columns(2)

    # ── Ventas por Género ─────────────────────────────────────────────────────
    with col_g:
        st.markdown("#### 👤 Ventas por Género")
        df_gender = df_mp[df_mp["gender"].notna()].copy()

        if df_gender.empty:
            st.info(
                "No se encontró información de género en las órdenes enriquecidas del período. "
                "El campo está disponible solo en las primeras 150 órdenes procesadas con detalle completo."
            )
        else:
            gen_agg = (
                df_gender.groupby("gender")
                .agg(Pedidos=("order_id", "count"), GMV=("gmv", "sum"))
                .reset_index()
                .sort_values("GMV", ascending=False)
            )
            gen_agg["% Pedidos"] = (gen_agg["Pedidos"] / gen_agg["Pedidos"].sum() * 100).round(1)
            gen_agg["% GMV"]     = (gen_agg["GMV"]     / gen_agg["GMV"].sum()     * 100).round(1)

            # KPIs rápidos
            for _, r in gen_agg.iterrows():
                emoji = "👨" if r["gender"] == "Hombre" else "👩"
                st.metric(
                    f"{emoji} {r['gender']}",
                    f"${r['GMV']:,.0f}",
                    f"{r['% GMV']:.1f}% del GMV · {r['Pedidos']:,} pedidos ({r['% Pedidos']:.1f}%)",
                )

            # Gráfico donut
            fig_gen = px.pie(
                gen_agg, values="GMV", names="gender",
                hole=0.55,
                color_discrete_sequence=["#4f87ff", "#FF3560"],
                title="GMV por Género",
            )
            fig_gen.update_layout(
                paper_bgcolor="#171b26", font_color="#8b90a7",
                title_font_color="#e8eaf2", height=280,
                legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_gen, use_container_width=True)

            # Tabla
            tabla_gen = gen_agg.copy()
            tabla_gen["GMV"] = tabla_gen["GMV"].apply(lambda v: f"${v:,.0f}")
            st.dataframe(
                tabla_gen.rename(columns={"gender": "Género", "% Pedidos": "% Pedidos", "% GMV": "% GMV"}),
                use_container_width=True, hide_index=True,
            )

    # ── Ciudades de mayor participación ───────────────────────────────────────
    with col_c:
        st.markdown("#### 🏙️ Ciudades de Mayor Participación")
        df_city = df_mp[df_mp["city"].notna() & (df_mp["city"] != "")].copy()

        if df_city.empty:
            st.info(
                "No se encontró información de ciudad en las órdenes del período. "
                "Está disponible en las primeras 150 órdenes procesadas con detalle completo."
            )
        else:
            city_agg = (
                df_city.groupby("city")
                .agg(Pedidos=("order_id", "count"), GMV=("gmv", "sum"))
                .reset_index()
                .sort_values("GMV", ascending=False)
            )
            city_agg["% GMV"] = (city_agg["GMV"] / city_agg["GMV"].sum() * 100).round(1)

            top_cities = city_agg.head(10)

            # Top 3 highlights
            top3 = top_cities.head(3)
            medal = ["🥇", "🥈", "🥉"]
            for i, (_, r) in enumerate(top3.iterrows()):
                st.metric(
                    f"{medal[i]} {r['city']}",
                    f"${r['GMV']:,.0f}",
                    f"{r['% GMV']:.1f}% del GMV · {r['Pedidos']:,} pedidos",
                )

            # Gráfico horizontal
            top_cities_plot = top_cities.sort_values("GMV", ascending=True)
            fig_city = px.bar(
                top_cities_plot,
                x="GMV", y="city", orientation="h",
                color="GMV",
                color_continuous_scale=["#232738", "#4f87ff"],
                title=f"Top {len(top_cities)} Ciudades — GMV",
                labels={"GMV": "GMV ($)", "city": ""},
                text=top_cities_plot["GMV"].apply(
                    lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"
                ),
            )
            fig_city.update_traces(textposition="outside")
            fig_city.update_layout(
                **PLOT_BASE,
                height=340,
                coloraxis_showscale=False,
                margin=dict(t=40, b=10, l=10, r=80),
            )
            st.plotly_chart(fig_city, use_container_width=True)

            # Tabla completa
            with st.expander("📋 Ver todas las ciudades"):
                tabla_city = city_agg.copy()
                tabla_city["GMV"] = tabla_city["GMV"].apply(lambda v: f"${v:,.0f}")
                st.dataframe(
                    tabla_city.rename(columns={"city": "Ciudad", "% GMV": "% GMV"}),
                    use_container_width=True, hide_index=True,
                )

    st.divider()


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛍️ VTEX Control")
    st.markdown("**Colombia · Producción**")
    st.divider()

    hoy = date.today()

    st.markdown("#### 📅 Período")
    preset = st.selectbox(
        "Período rápido",
        ["Hoy", "Últimos 7 días", "Últimos 15 días", "Últimos 30 días",
         "Este mes", "Mes anterior", "Personalizado"],
        index=0,
        label_visibility="collapsed",
    )

    if preset == "Hoy":
        default_from, default_to = hoy, hoy
    elif preset == "Últimos 7 días":
        default_from, default_to = hoy - timedelta(days=6), hoy
    elif preset == "Últimos 15 días":
        default_from, default_to = hoy - timedelta(days=14), hoy
    elif preset == "Últimos 30 días":
        default_from, default_to = hoy - timedelta(days=29), hoy
    elif preset == "Este mes":
        default_from, default_to = hoy.replace(day=1), hoy
    elif preset == "Mes anterior":
        primer = hoy.replace(day=1)
        ultimo = primer - timedelta(days=1)
        default_from, default_to = ultimo.replace(day=1), ultimo
    else:
        default_from, default_to = hoy - timedelta(days=29), hoy

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        fecha_desde = st.date_input("Desde", value=default_from, max_value=hoy)
    with col_d2:
        fecha_hasta = st.date_input("Hasta", value=default_to, max_value=hoy)

    if fecha_desde > fecha_hasta:
        st.error("'Desde' no puede ser mayor que 'Hasta'.")
        st.stop()

    st.divider()
    st.markdown("#### 🏪 Marketplace")
    mp_opciones = ["Todos"] + sorted(MP_SUFFIX.values())
    mp_sel = st.selectbox("Canal", mp_opciones, label_visibility="collapsed")

    st.divider()
    st.markdown("#### 📋 Estado")
    estados_disp = list(STATUS_LABEL.values())
    estados_sel  = st.multiselect(
        "Filtrar estado",
        options=estados_disp,
        default=estados_disp,
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("#### 🎯 Presupuesto Mensual")

    presupuestos_data = cargar_presupuestos()

    with st.expander("📝 Gestionar presupuestos por mes", expanded=False):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            mes_edit = st.selectbox(
                "Mes", list(MESES_ES.values()),
                index=fecha_hasta.month - 1,
                key="mes_edit_sel",
            )
        with col_m2:
            anio_edit = st.number_input(
                "Año", min_value=2020, max_value=2100,
                value=fecha_hasta.year, step=1, key="anio_edit_sel",
            )

        mes_num_edit  = [k for k, v in MESES_ES.items() if v == mes_edit][0]
        mes_key_edit  = f"{int(anio_edit)}-{mes_num_edit:02d}"
        valor_actual  = presupuestos_data.get(mes_key_edit, 0.0)

        nuevo_valor = st.number_input(
            f"Presupuesto {mes_edit} {int(anio_edit)}",
            min_value=0.0, value=float(valor_actual),
            step=1_000_000.0, format="%.0f",
            key=f"presupuesto_input_{mes_key_edit}",
        )

        if st.button("💾 Guardar presupuesto", use_container_width=True):
            if guardar_presupuesto(mes_key_edit, nuevo_valor):
                st.success(f"Presupuesto de {mes_edit} {int(anio_edit)} guardado.")
                st.rerun()
            else:
                st.error("No se pudo guardar el presupuesto.")

        if presupuestos_data:
            st.markdown("**Presupuestos guardados:**")
            for k in sorted(presupuestos_data.keys()):
                anio_k, mes_k = k.split("-")
                st.caption(f"{MESES_ES[int(mes_k)]} {anio_k}: ${presupuestos_data[k]:,.0f}")

    st.divider()
    actualizar = st.button("🔄 Actualizar datos", use_container_width=True, type="primary")
    st.divider()
    st.caption(f"Cuenta: **{st.secrets.get('VTEX_ACCOUNT', '—')}**")
    st.caption("🟢 API conectada · Hora Colombia (UTC-5)")
    st.markdown(
        "<small style='color:#555a72'>✅ Facturado · 📦 Listo · 🔧 Preparando · 💳 Pago aprobado</small>",
        unsafe_allow_html=True,
    )

# ── CARGA ─────────────────────────────────────────────────────────────────────
fecha_desde_str = fecha_desde.strftime("%Y-%m-%d")
fecha_hasta_str = fecha_hasta.strftime("%Y-%m-%d")
cache_key       = f"{fecha_desde_str}_{fecha_hasta_str}"

# Período equivalente del año anterior
fecha_desde_ly     = shift_year(fecha_desde)
fecha_hasta_ly     = shift_year(fecha_hasta)
fecha_desde_ly_str = fecha_desde_ly.strftime("%Y-%m-%d")
fecha_hasta_ly_str = fecha_hasta_ly.strftime("%Y-%m-%d")
cache_key_ly       = f"LY_{fecha_desde_ly_str}_{fecha_hasta_ly_str}"


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_datos(key, f_desde, f_hasta):
    with st.spinner(f"📡 Consultando VTEX: {f_desde} → {f_hasta} (hora Colombia)..."):
        raw    = fetch_orders(f_desde, f_hasta)
        parsed = parse_orders(raw)
    if not parsed:
        return pd.DataFrame()
    df = pd.DataFrame(parsed)

    # "fecha" ya viene en hora Colombia desde vtex_api.py
    if "fecha" not in df.columns or df["fecha"].isna().all():
        from datetime import timezone, timedelta as td
        COL_TZ = timezone(td(hours=-5))
        df["created_at_dt"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df["fecha"] = df["created_at_dt"].dt.tz_convert(COL_TZ).dt.date

    # Filtrar solo órdenes cuya fecha Colombia esté en el rango pedido
    fecha_desde_d = date.fromisoformat(f_desde)
    fecha_hasta_d = date.fromisoformat(f_hasta)
    df = df[df["fecha"].between(fecha_desde_d, fecha_hasta_d)]

    return df

if actualizar:
    st.cache_data.clear()

df_full = cargar_datos(cache_key, fecha_desde_str, fecha_hasta_str)

if df_full.empty:
    st.markdown("## 🛍️ VTEX Control Comercial")
    st.warning(
        f"No se encontraron pedidos de marketplace entre "
        f"**{fecha_desde_str}** y **{fecha_hasta_str}** (hora Colombia).\n\n"
        "Verifica que existan órdenes con los sufijos: "
        "DFT · GVL · VPC · DDD · FFF · MLB · MPX · FLB · PLT"
    )
    st.stop()

# Datos del mismo período, año anterior (para comparativo)
df_full_ly = cargar_datos(cache_key_ly, fecha_desde_ly_str, fecha_hasta_ly_str)

# ── FILTROS ───────────────────────────────────────────────────────────────────
df = df_full.copy()
if mp_sel != "Todos":
    df = df[df["marketplace"] == mp_sel]
if estados_sel:
    df = df[df["status"].isin(estados_sel)]
if df.empty:
    st.info("Sin órdenes para los filtros seleccionados.")
    st.stop()

# Mismo filtro de estado/marketplace aplicado al período del año anterior
if not df_full_ly.empty:
    df_ly = df_full_ly.copy()
    if mp_sel != "Todos":
        df_ly = df_ly[df_ly["marketplace"] == mp_sel]
    if estados_sel:
        df_ly = df_ly[df_ly["status"].isin(estados_sel)]
else:
    df_ly = df_full_ly  # ya está vacío

# Versión del año anterior filtrada solo por estado (para el desglose por
# marketplace, que siempre debe mostrar todos los canales)
df_estado_actual = df_full[df_full["status"].isin(estados_sel)] if estados_sel else df_full
if not df_full_ly.empty:
    df_estado_ly = df_full_ly[df_full_ly["status"].isin(estados_sel)] if estados_sel else df_full_ly
else:
    df_estado_ly = df_full_ly

dias_rango = (fecha_hasta - fecha_desde).days + 1
titulo     = "Todos los Marketplaces" if mp_sel == "Todos" else mp_sel

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown(f"## {titulo}")
st.caption(
    f"{fecha_desde.strftime('%d/%m/%Y')} → {fecha_hasta.strftime('%d/%m/%Y')} · "
    f"**{len(df):,}** pedidos de marketplace · {dias_rango} día(s) · hora Colombia"
)
st.divider()

# ── NUEVO: Detalle exclusivo cuando se selecciona un marketplace específico ───
if mp_sel != "Todos":
    render_marketplace_detail(df, mp_sel)

# ── KPIs ──────────────────────────────────────────────────────────────────────
gmv_total   = df["gmv"].sum()
pedidos     = len(df)
descuentos  = df["discount"].sum()
ticket_prom = df["gmv"].mean() if pedidos > 0 else 0
unidades    = df["units"].sum()
pct_desc    = (descuentos / (gmv_total + descuentos) * 100) if (gmv_total + descuentos) > 0 else 0
gmv_dia     = gmv_total / dias_rango if dias_rango > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("💰 GMV Total",       f"${gmv_total:,.0f}")
c2.metric("🛒 Pedidos",         f"{pedidos:,}")
c3.metric("🎟️ Descuentos",      f"${descuentos:,.0f}", f"{pct_desc:.1f}% sobre precio lista")
c4.metric("🧾 Ticket Promedio", f"${ticket_prom:,.0f}")
c5.metric("📦 Unidades",        f"{unidades:,}")
c6.metric("📈 GMV / Día",       f"${gmv_dia:,.0f}")

st.divider()

# ── COMPARATIVO AÑO ANTERIOR Y PRESUPUESTO ───────────────────────────────────
st.markdown("### 🆚 Comparativo Año Anterior y Presupuesto")
st.caption(
    f"Período actual: {fecha_desde.strftime('%d/%m/%Y')} → {fecha_hasta.strftime('%d/%m/%Y')}  ·  "
    f"Año anterior: {fecha_desde_ly.strftime('%d/%m/%Y')} → {fecha_hasta_ly.strftime('%d/%m/%Y')}"
)

gmv_total_ly      = df_ly["gmv"].sum() if not df_ly.empty else 0.0
crecimiento_pct   = ((gmv_total - gmv_total_ly) / gmv_total_ly * 100) if gmv_total_ly > 0 else None
presupuesto_rango = obtener_presupuesto_rango(fecha_desde, fecha_hasta, presupuestos_data)
cumplimiento_pct  = (gmv_total / presupuesto_rango * 100) if presupuesto_rango > 0 else None

k1, k2, k3, k4 = st.columns(4)
k1.metric(f"💰 GMV {fecha_hasta.year}", f"${gmv_total:,.0f}")
k2.metric(
    f"📅 GMV {fecha_hasta_ly.year} (mismo período)",
    f"${gmv_total_ly:,.0f}" if gmv_total_ly > 0 else "Sin datos",
)
k3.metric(
    "📈 Crecimiento YoY",
    f"{crecimiento_pct:+.1f}%" if crecimiento_pct is not None else "—",
)
k4.metric(
    "🎯 Cumplimiento Presupuesto",
    f"{cumplimiento_pct:.1f}%" if cumplimiento_pct is not None else "Sin presupuesto",
    f"${presupuesto_rango:,.0f} presupuestado" if presupuesto_rango > 0 else None,
)

if presupuesto_rango <= 0:
    st.info(
        "💡 No has ingresado presupuesto para el/los mes(es) del período seleccionado. "
        "Ábrelo en el panel lateral, en **'Gestionar presupuestos por mes'**."
    )

# Desglose por marketplace: año actual vs año anterior (siempre todos los canales)
comp_actual = df_estado_actual.groupby("marketplace")["gmv"].sum().reset_index().rename(columns={"gmv": "GMV_Actual"})
if not df_estado_ly.empty:
    comp_ly = df_estado_ly.groupby("marketplace")["gmv"].sum().reset_index().rename(columns={"gmv": "GMV_LY"})
else:
    comp_ly = pd.DataFrame(columns=["marketplace", "GMV_LY"])

comparativo_mp = comp_actual.merge(comp_ly, on="marketplace", how="outer").fillna(0.0)
comparativo_mp["Crecimiento_%"] = comparativo_mp.apply(
    lambda r: ((r["GMV_Actual"] - r["GMV_LY"]) / r["GMV_LY"] * 100) if r["GMV_LY"] > 0 else None,
    axis=1,
)
comparativo_mp = comparativo_mp.sort_values("GMV_Actual", ascending=False)

chart_data = comparativo_mp.melt(
    id_vars="marketplace", value_vars=["GMV_Actual", "GMV_LY"],
    var_name="Período", value_name="GMV",
)
chart_data["Período"] = chart_data["Período"].map({
    "GMV_Actual": str(fecha_hasta.year),
    "GMV_LY":     str(fecha_hasta_ly.year),
})

fig_comp = px.bar(
    chart_data, x="marketplace", y="GMV", color="Período", barmode="group",
    title="GMV por Marketplace — Año actual vs Año anterior",
    color_discrete_sequence=["#FF3560", "#4f87ff"],
    labels={"GMV": "GMV ($)", "marketplace": ""},
)
fig_comp.update_layout(
    paper_bgcolor="#171b26", plot_bgcolor="#171b26",
    font_color="#8b90a7", title_font_color="#e8eaf2",
    legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
    height=380,
)
st.plotly_chart(fig_comp, use_container_width=True)

tabla_comp = comparativo_mp.copy()
tabla_comp["GMV_Actual"]    = tabla_comp["GMV_Actual"].apply(lambda v: f"${v:,.0f}")
tabla_comp["GMV_LY"]        = tabla_comp["GMV_LY"].apply(lambda v: f"${v:,.0f}")
tabla_comp["Crecimiento_%"] = tabla_comp["Crecimiento_%"].apply(lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
st.dataframe(
    tabla_comp.rename(columns={
        "marketplace":    "Marketplace",
        "GMV_Actual":     f"GMV {fecha_hasta.year}",
        "GMV_LY":         f"GMV {fecha_hasta_ly.year}",
        "Crecimiento_%":  "Crecimiento YoY",
    }),
    use_container_width=True, hide_index=True,
)

st.divider()

# ── PEDIDOS POR ESTADO ────────────────────────────────────────────────────────
st.markdown("### 📋 Pedidos por Estado")
est_counts = df.groupby("status").agg(
    Pedidos=("order_id", "count"),
    GMV=("gmv", "sum"),
).reset_index().sort_values("Pedidos", ascending=False)

col_e1, col_e2 = st.columns(2)
with col_e1:
    fig_est = px.bar(
        est_counts, x="status", y="Pedidos",
        color="status", color_discrete_sequence=COLORS,
        title="Pedidos por estado",
        labels={"status": "", "Pedidos": "Cantidad"},
        text="Pedidos",
    )
    fig_est.update_traces(textposition="outside")
    fig_est.update_layout(**PLOT_BASE, height=320)
    st.plotly_chart(fig_est, use_container_width=True)

with col_e2:
    fig_est_gmv = px.pie(
        est_counts, values="GMV", names="status",
        title="GMV por estado",
        color_discrete_sequence=COLORS,
        hole=0.5,
    )
    fig_est_gmv.update_layout(
        paper_bgcolor="#171b26", font_color="#8b90a7",
        title_font_color="#e8eaf2", height=320,
        legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
    )
    st.plotly_chart(fig_est_gmv, use_container_width=True)

st.divider()

# ── VENTAS Y DESCUENTOS ───────────────────────────────────────────────────────
st.markdown("### 📊 Ventas y Descuentos por Marketplace")

gmv_mp = df.groupby("marketplace").agg(
    GMV=("gmv", "sum"),
    Pedidos=("order_id", "count"),
    Descuentos=("discount", "sum"),
    Unidades=("units", "sum"),
).reset_index().sort_values("GMV", ascending=False)
gmv_mp["Ticket"]  = (gmv_mp["GMV"] / gmv_mp["Pedidos"]).round(0)
gmv_mp["PctDesc"] = (gmv_mp["Descuentos"] / (gmv_mp["GMV"] + gmv_mp["Descuentos"]) * 100).round(1)

col1, col2 = st.columns(2)
with col1:
    fig_gmv = px.bar(
        gmv_mp, x="marketplace", y="GMV",
        color="marketplace", color_discrete_sequence=COLORS,
        title="GMV por Marketplace",
        labels={"GMV": "GMV ($)", "marketplace": ""},
        text=gmv_mp["GMV"].apply(lambda v: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"),
    )
    fig_gmv.update_traces(textposition="outside")
    fig_gmv.update_layout(**PLOT_BASE, height=340)
    st.plotly_chart(fig_gmv, use_container_width=True)

with col2:
    fig_ped = px.bar(
        gmv_mp, x="marketplace", y="Pedidos",
        color="marketplace", color_discrete_sequence=COLORS,
        title="Pedidos por Marketplace",
        labels={"Pedidos": "Cantidad", "marketplace": ""},
        text="Pedidos",
    )
    fig_ped.update_traces(textposition="outside")
    fig_ped.update_layout(**PLOT_BASE, height=340)
    st.plotly_chart(fig_ped, use_container_width=True)

desc_mp = gmv_mp.sort_values("PctDesc", ascending=True)
fig_desc = px.bar(
    desc_mp, x="PctDesc", y="marketplace", orientation="h",
    color="PctDesc", color_continuous_scale="RdYlGn_r",
    title="Descuento como % del precio lista por Canal",
    labels={"PctDesc": "% Descuento", "marketplace": ""},
    text=desc_mp["PctDesc"].apply(lambda v: f"{v:.1f}%"),
)
fig_desc.update_traces(textposition="outside")
fig_desc.update_layout(**PLOT_BASE, height=320, coloraxis_showscale=False)
st.plotly_chart(fig_desc, use_container_width=True)

st.markdown("##### Resumen por Marketplace")
tabla_res = gmv_mp.copy()
tabla_res["GMV"]        = tabla_res["GMV"].apply(lambda v: f"${v:,.0f}")
tabla_res["Descuentos"] = tabla_res["Descuentos"].apply(lambda v: f"${v:,.0f}")
tabla_res["Ticket"]     = tabla_res["Ticket"].apply(lambda v: f"${v:,.0f}")
tabla_res["PctDesc"]    = tabla_res["PctDesc"].apply(lambda v: f"{v}%")
st.dataframe(
    tabla_res.rename(columns={
        "marketplace": "Marketplace", "PctDesc": "% Desc.", "Ticket": "Ticket Prom."
    })[["Marketplace","GMV","Pedidos","Descuentos","Ticket Prom.","Unidades","% Desc."]],
    use_container_width=True, hide_index=True,
)

st.divider()

# ── TENDENCIA DIARIA ──────────────────────────────────────────────────────────
st.markdown("### 📈 Tendencia Diaria")
tend = df.groupby("fecha").agg(
    Pedidos=("order_id", "count"),
    GMV=("gmv", "sum"),
).reset_index()
tend["fecha"] = pd.to_datetime(tend["fecha"])

fig_tend = go.Figure()
fig_tend.add_trace(go.Scatter(
    x=tend["fecha"], y=tend["GMV"], mode="lines", name="GMV",
    line=dict(color="#FF3560", width=2),
    fill="tozeroy", fillcolor="rgba(255,53,96,0.08)",
))
fig_tend.add_trace(go.Scatter(
    x=tend["fecha"], y=tend["Pedidos"], mode="lines", name="Pedidos",
    line=dict(color="#4f87ff", width=2), yaxis="y2",
))
fig_tend.update_layout(
    title=f"GMV y Pedidos diarios — {titulo}",
    paper_bgcolor="#171b26", plot_bgcolor="#171b26",
    font_color="#8b90a7", title_font_color="#e8eaf2",
    legend=dict(bgcolor="#171b26", font=dict(color="#8b90a7")),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="GMV ($)"),
    yaxis2=dict(overlaying="y", side="right", title="Pedidos", showgrid=False),
    height=320,
)
st.plotly_chart(fig_tend, use_container_width=True)

st.divider()

# ── INVENTARIO ────────────────────────────────────────────────────────────────
st.markdown("### 📦 Inventario")
all_skus    = []
for row in df["sku_ids"]:
    if isinstance(row, list):
        all_skus.extend(row)
skus_unicos = [s for s in list(set(all_skus)) if s][:50]

if skus_unicos:
    if st.button(f"🔍 Consultar inventario ({len(skus_unicos)} SKUs)", type="secondary"):
        with st.spinner("Consultando Logistics API..."):
            inv_data = [fetch_inventory(s) for s in skus_unicos]
        df_inv = pd.DataFrame(inv_data)
        df_inv["Estado"] = df_inv["available"].apply(
            lambda x: "🔴 Sin stock" if x == 0 else "🟡 Crítico (<10)" if x < 10 else "🟢 OK"
        )
        i1, i2, i3 = st.columns(3)
        criticos = len(df_inv[df_inv["available"] <= 0])
        bajos    = len(df_inv[(df_inv["available"] > 0) & (df_inv["available"] < 10)])
        i1.metric("🔴 Sin stock",  criticos)
        i2.metric("🟡 Stock bajo", bajos)
        i3.metric("🟢 Stock OK",   len(df_inv) - criticos - bajos)
        st.dataframe(
            df_inv.rename(columns={"sku_id": "SKU", "available": "Stock disponible"}),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("No se encontraron SKUs en las órdenes del período.")

st.divider()

# ── TOP PRODUCTOS ─────────────────────────────────────────────────────────────
st.markdown("### 🏆 Top Productos")
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
            title="Top 10 — Unidades vendidas",
            color_discrete_sequence=["#4f87ff"],
            labels={"cantidad": "Unidades", "nombre": ""},
            text="cantidad",
        )
        fig_tu.update_layout(**PLOT_BASE, height=380)
        st.plotly_chart(fig_tu, use_container_width=True)

    with col2:
        top_v = (
            df_items.groupby("nombre")["valor_total"]
            .sum().reset_index()
            .sort_values("valor_total", ascending=True).tail(10)
        )
        fig_tv = px.bar(
            top_v, x="valor_total", y="nombre", orientation="h",
            title="Top 10 — Valor ($)",
            color_discrete_sequence=["#22c77a"],
            labels={"valor_total": "Valor ($)", "nombre": ""},
            text=top_v["valor_total"].apply(lambda v: f"${v:,.0f}"),
        )
        fig_tv.update_layout(**PLOT_BASE, height=380)
        st.plotly_chart(fig_tv, use_container_width=True)

    with st.expander("📋 Tabla completa de productos"):
        tabla_p = (
            df_items.groupby(["sku_id","nombre"]).agg(
                Unidades=("cantidad", "sum"),
                Valor=("valor_total", "sum"),
            ).reset_index().sort_values("Valor", ascending=False)
        )
        tabla_p["Valor"] = tabla_p["Valor"].apply(lambda v: f"${v:,.0f}")
        st.dataframe(
            tabla_p.rename(columns={"sku_id": "SKU", "nombre": "Producto"}),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("No se encontró detalle de productos para el período seleccionado.")

st.divider()

# ── TABLA DE ÓRDENES ──────────────────────────────────────────────────────────
with st.expander("🗂️ Ver todas las órdenes de marketplace"):
    df_show = df[["order_id","marketplace","fecha","status","gmv","discount","units"]].copy()
    df_show["gmv"]      = df_show["gmv"].apply(lambda v: f"${v:,.0f}")
    df_show["discount"] = df_show["discount"].apply(lambda v: f"${v:,.0f}")
    st.dataframe(
        df_show.rename(columns={
            "order_id": "Orden", "marketplace": "Marketplace", "fecha": "Fecha (Col)",
            "status": "Estado", "gmv": "GMV (pagado)", "discount": "Descuento", "units": "Unidades",
        }),
        use_container_width=True, hide_index=True,
    )

st.divider()
st.caption(
    f"VTEX Control · {st.secrets.get('VTEX_ACCOUNT', '—')} · "
    f"{fecha_desde.strftime('%d/%m/%Y')} → {fecha_hasta.strftime('%d/%m/%Y')} · "
    f"Hora Colombia (UTC-5) · DFT · GVL · VPC · DDD · FFF · MLB · MPX · FLB · PLT"
)

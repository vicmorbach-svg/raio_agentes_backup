import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import requests
import geopandas as gpd
import unicodedata

st.set_page_config(page_title="Realocação de Agentes", layout="wide")
st.title("🔄 Realocação Inteligente de Agentes")
st.markdown("Encontre os agentes disponíveis mais próximos para cobrir a necessidade da sua loja, considerando o tempo real de deslocamento.")

# ==========================================
# 1. CARREGAMENTO E LIMPEZA DOS DADOS
# ==========================================
@st.cache_data
def load_data():
    try:
        df_lojas = pd.read_excel("enderecos_com_coordenadas.xlsx")
        mapa_rs = gpd.read_file("rs_municipios.geojson").to_crs(epsg=4326)
    except FileNotFoundError:
        st.error("⚠️ Arquivos não encontrados na pasta. Verifique o Excel e o GeoJSON.")
        st.stop()

    df_lojas.columns = df_lojas.columns.str.upper().str.strip()

    # Limpeza de Coordenadas
    if 'LATITUDE' in df_lojas.columns and 'LONGITUDE' in df_lojas.columns:
        df_lojas['LATITUDE'] = pd.to_numeric(df_lojas['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        df_lojas['LONGITUDE'] = pd.to_numeric(df_lojas['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        # Trava de segurança para coordenadas inválidas
        df_lojas.loc[(df_lojas['LATITUDE'] < -90) | (df_lojas['LATITUDE'] > 90), 'LATITUDE'] = None
        df_lojas.loc[(df_lojas['LONGITUDE'] < -180) | (df_lojas['LONGITUDE'] > 180), 'LONGITUDE'] = None

    df_lojas = df_lojas.dropna(subset=['LATITUDE', 'LONGITUDE'])
    df_lojas['CIDADE'] = df_lojas['CIDADE'].astype(str).str.upper().str.strip()

    # Garante colunas de agentes
    if 'AGENTE_DISPONIVEL' not in df_lojas.columns:
        df_lojas['AGENTE_DISPONIVEL'] = 'NAO'
    if 'NOME_AGENTE' not in df_lojas.columns:
        df_lojas['NOME_AGENTE'] = 'Não Informado'

    # --- TRATAMENTO DE ACENTOS E PADRONIZAÇÃO PARA O MAPA ---
    def padronizar_nomes(serie):
        return serie.astype(str).str.upper().str.strip().str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')

    df_lojas['CIDADE_TRATADA'] = padronizar_nomes(df_lojas['CIDADE'])
    mapa_rs['name_muni_tratado'] = padronizar_nomes(mapa_rs['name_muni'])

    # Cruzamento do mapa com as diretorias
    if 'DIRETORIA' in df_lojas.columns:
        df_mapa = df_lojas[['CIDADE_TRATADA', 'DIRETORIA']].drop_duplicates(subset=['CIDADE_TRATADA'])
        mapa_diretorias = mapa_rs.merge(df_mapa, how="left", left_on="name_muni_tratado", right_on="CIDADE_TRATADA")
        mapa_diretorias['DIRETORIA'] = mapa_diretorias['DIRETORIA'].fillna('Sem Diretoria')
    else:
        mapa_diretorias = mapa_rs
        mapa_diretorias['DIRETORIA'] = 'Sem Diretoria'

    return df_lojas, mapa_diretorias

df_lojas, mapa_diretorias = load_data()

# Inicializa a memória do aplicativo (Session State)
if 'cidade_selecionada' not in st.session_state:
    st.session_state.cidade_selecionada = "🗺️ VISÃO GERAL (TODAS AS LOJAS)"
if 'loja_selecionada' not in st.session_state:
    st.session_state.loja_selecionada = None

# ==========================================
# 2. INTERFACE DE SELEÇÃO
# ==========================================
col1, col2, col3 = st.columns(3)

with col1:
    cidades_disponiveis = ["🗺️ VISÃO GERAL (TODAS AS LOJAS)"] + sorted(df_lojas['CIDADE'].unique())
    index_cidade = cidades_disponiveis.index(st.session_state.cidade_selecionada) if st.session_state.cidade_selecionada in cidades_disponiveis else 0

    cidade_selecionada = st.selectbox("1️⃣ Escolha a Cidade:", cidades_disponiveis, index=index_cidade)

    if cidade_selecionada != st.session_state.cidade_selecionada:
        st.session_state.cidade_selecionada = cidade_selecionada
        st.session_state.loja_selecionada = None
        st.rerun()

# ==========================================
# LÓGICA 1: VISÃO GERAL DO ESTADO (FOLIUM)
# ==========================================
if st.session_state.cidade_selecionada == "🗺️ VISÃO GERAL (TODAS AS LOJAS)":
    st.info("📍 Clique em qualquer marcador no mapa para ir direto para a análise de raio daquela loja.")

    col_nome_loja = 'ENDERECO' if 'ENDERECO' in df_lojas.columns else df_lojas.columns[0]
    m = folium.Map(location=[-30.0, -53.5], zoom_start=6, tiles="OpenStreetMap")

    # CORES FIXAS DAS REGIONAIS
    dicionario_cores = {
        'CENTRAL': '#F8DC00',
        'LESTE': '#17E3CB',
        'NORTE': '#FE952B',
        'OESTE': '#0027BD',
        'SUL': '#A11FFF',
        'Sem Diretoria': '#cccccc'
    }

    # Adiciona os polígonos coloridos ao mapa
    folium.GeoJson(
        mapa_diretorias,
        style_function=lambda feature: {
            'fillColor': dicionario_cores.get(feature['properties'].get('DIRETORIA', 'Sem Diretoria'), '#cccccc'),
            'color': 'black',
            'weight': 0.5,
            'fillOpacity': 0.5,
        },
        tooltip=folium.GeoJsonTooltip(fields=['name_muni', 'DIRETORIA'], aliases=['Cidade:', 'Diretoria:'])
    ).add_to(m)

    # Adiciona os pins das lojas
    for idx, row in df_lojas.iterrows():
        tem_agente = str(row.get('AGENTE_DISPONIVEL', 'NAO')).strip().upper() == 'SIM'

        if tem_agente:
            cor_pino = "green"
            icone_pino = "user"
            texto_tooltip = f"✅ Agente Disponível | Loja: {row[col_nome_loja]} (Clique para analisar)"
        else:
            cor_pino = "blue"
            icone_pino = "info-sign"
            texto_tooltip = f"Loja: {row[col_nome_loja]} (Clique para analisar)"

        folium.Marker(
            location=[row['LATITUDE'], row['LONGITUDE']],
            tooltip=texto_tooltip,
            icon=folium.Icon(color=cor_pino, icon=icone_pino)
        ).add_to(m)

    # Captura o clique no mapa
    mapa_geral = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])

    if mapa_geral and mapa_geral.get("last_object_clicked"):
        lat_clicada = mapa_geral["last_object_clicked"]["lat"]
        lng_clicada = mapa_geral["last_object_clicked"]["lng"]

        df_lojas['LAT_ROUND'] = df_lojas['LATITUDE'].round(4)
        df_lojas['LNG_ROUND'] = df_lojas['LONGITUDE'].round(4)

        loja_clicada = df_lojas[
            (df_lojas['LAT_ROUND'] == round(lat_clicada, 4)) & 
            (df_lojas['LNG_ROUND'] == round(lng_clicada, 4))
        ]

        if not loja_clicada.empty:
            st.session_state.cidade_selecionada = loja_clicada.iloc[0]['CIDADE']
            st.session_state.loja_selecionada = loja_clicada.iloc[0][col_nome_loja]
            st.rerun()

# ==========================================
# LÓGICA 2: ANÁLISE DE RAIO (FOLIUM + OSRM)
# ==========================================
else:
    with col2:
        lojas_da_cidade = df_lojas[df_lojas['CIDADE'] == st.session_state.cidade_selecionada]
        col_nome_loja = 'ENDERECO' if 'ENDERECO' in lojas_da_cidade.columns else lojas_da_cidade.columns[0]
        lista_lojas = lojas_da_cidade[col_nome_loja].tolist()

        index_loja = 0
        if st.session_state.loja_selecionada in lista_lojas:
            index_loja = lista_lojas.index(st.session_state.loja_selecionada)

        loja_selecionada = st.selectbox("2️⃣ Escolha a sua Loja:", lista_lojas, index=index_loja)
        st.session_state.loja_selecionada = loja_selecionada

    with col3:
        raio_km = st.slider("3️⃣ Defina o Raio de Busca (em KM):", min_value=0.5, max_value=50.0, value=10.0, step=0.5)

    if st.button("⬅️ Voltar para o Mapa Geral"):
        st.session_state.cidade_selecionada = "🗺️ VISÃO GERAL (TODAS AS LOJAS)"
        st.session_state.loja_selecionada = None
        st.rerun()

    dados_loja = lojas_da_cidade[lojas_da_cidade[col_nome_loja] == loja_selecionada].iloc[0]
    coord_loja = (dados_loja['LATITUDE'], dados_loja['LONGITUDE'])

    # Filtra agentes disponíveis
    df_agentes = df_lojas[df_lojas['AGENTE_DISPONIVEL'].astype(str).str.upper().str.strip() == 'SIM'].copy()

    # Função API OSRM
    def calcular_rota_real(coord_origem, coord_destino):
        url = f"http://router.project-osrm.org/route/v1/driving/{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=false"
        try:
            resposta = requests.get(url, timeout=5)
            dados = resposta.json()
            if dados.get('code') == 'Ok':
                distancia_km = dados['routes'][0]['distance'] / 1000
                tempo_minutos = dados['routes'][0]['duration'] / 60
                return distancia_km, tempo_minutos
        except Exception:
            pass
        return None, None

    # 1. Filtro rápido por linha reta
    if not df_agentes.empty:
        df_agentes['DISTANCIA_RETA_KM'] = df_agentes.apply(
            lambda row: geodesic(coord_loja, (row['LATITUDE'], row['LONGITUDE'])).kilometers, axis=1
        )
        df_agentes = df_agentes[df_agentes['DISTANCIA_RETA_KM'] > 0.05] # Remove a própria loja

        # 2. Filtra quem está perto (margem de 50% para curvas da estrada)
        agentes_proximos = df_agentes[df_agentes['DISTANCIA_RETA_KM'] <= (raio_km * 1.5)].copy()

        # 3. Calcula rota real só para os próximos
        if not agentes_proximos.empty:
            with st.spinner("Calculando rotas e tempo de deslocamento real..."):
                rotas = agentes_proximos.apply(
                    lambda row: calcular_rota_real(coord_loja, (row['LATITUDE'], row['LONGITUDE'])), 
                    axis=1
                )
                agentes_proximos['DISTANCIA_REAL_KM'] = [r[0] for r in rotas]
                agentes_proximos['TEMPO_MINUTOS'] = [r[1] for r in rotas]
                agentes_proximos = agentes_proximos.dropna(subset=['DISTANCIA_REAL_KM'])
    else:
        agentes_proximos = pd.DataFrame()
        st.warning("Nenhum agente marcado como 'SIM' foi encontrado na planilha.")

    # Cria o mapa
    m = folium.Map(location=[coord_loja[0], coord_loja[1]], zoom_start=12, tiles="OpenStreetMap")

    folium.Circle(
        location=[coord_loja[0], coord_loja[1]],
        radius=raio_km * 1000,
        color="#0055FF", fill=True, fill_color="#0055FF", fill_opacity=0.15,
        tooltip=f"Raio de {raio_km}km"
    ).add_to(m)

    folium.Marker(
        location=[coord_loja[0], coord_loja[1]],
        tooltip=f"🏢 DESTINO: {dados_loja[col_nome_loja]}",
        icon=folium.Icon(color="blue", icon="star")
    ).add_to(m)

    if not agentes_proximos.empty:
        for idx, row in agentes_proximos.iterrows():
            dist = row['DISTANCIA_REAL_KM']
            tempo = row['TEMPO_MINUTOS']

            if dist <= raio_km:
                cor_pino, icone_pino = "green", "user"
            else:
                cor_pino, icone_pino = "lightgray", "user"

            texto_pin = f"👤 {row['NOME_AGENTE']} | {row['CIDADE']}<br>🚗 {dist:.1f} km | ⏱️ {tempo:.0f} min"

            folium.Marker(
                location=[row['LATITUDE'], row['LONGITUDE']],
                tooltip=texto_pin,
                icon=folium.Icon(color=cor_pino, icon=icone_pino)
            ).add_to(m)

    st_folium(m, use_container_width=True, height=600, returned_objects=[])

    # Tabela de Resultados
    if not agentes_proximos.empty:
        st.subheader(f"📋 Agentes disponíveis num raio de {raio_km}km (Rota Real)")
        agentes_dentro_raio = agentes_proximos[agentes_proximos['DISTANCIA_REAL_KM'] <= raio_km]

        if not agentes_dentro_raio.empty:
            tabela = agentes_dentro_raio[['NOME_AGENTE', 'CIDADE', col_nome_loja, 'DISTANCIA_REAL_KM', 'TEMPO_MINUTOS']].sort_values('DISTANCIA_REAL_KM')
            tabela['DISTANCIA_REAL_KM'] = tabela['DISTANCIA_REAL_KM'].round(1).astype(str) + " km"
            tabela['TEMPO_MINUTOS'] = tabela['TEMPO_MINUTOS'].round(0).astype(int).astype(str) + " min"
            tabela.columns = ['Nome do Agente', 'Cidade Origem', 'Local de Origem', 'Distância (Carro)', 'Tempo Estimado']

            st.dataframe(tabela, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum agente encontrado dentro deste raio considerando as rotas de carro.")

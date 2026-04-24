import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import requests
import json
import unicodedata

st.set_page_config(page_title="Realocação de Agentes", layout="wide")
st.title("🔄 Realocação Inteligente de Agentes")
st.markdown("Encontre os agentes disponíveis mais próximos considerando o tempo real de deslocamento.")

# ==========================================
# 1. CARREGAMENTO E LIMPEZA DOS DADOS
# ==========================================
@st.cache_data
def load_data():
    try:
        # Carrega a planilha única
        df = pd.read_excel("enderecos_com_coordenadas.xlsx")

        # Carrega o GeoJSON nativamente (sem geopandas)
        with open("rs_municipios.geojson", "r", encoding="utf-8") as f:
            geojson_rs = json.load(f)

    except FileNotFoundError:
        st.error("⚠️ Arquivos não encontrados. Verifique se 'enderecos_com_coordenadas.xlsx' e 'rs_municipios.geojson' estão na pasta.")
        st.stop()

    df.columns = df.columns.str.upper().str.strip()

    # Limpeza de Coordenadas
    if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
        df['LATITUDE'] = pd.to_numeric(df['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        df['LONGITUDE'] = pd.to_numeric(df['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        # Trava de segurança para coordenadas inválidas
        df.loc[(df['LATITUDE'] < -90) | (df['LATITUDE'] > 90), 'LATITUDE'] = None
        df.loc[(df['LONGITUDE'] < -180) | (df['LONGITUDE'] > 180), 'LONGITUDE'] = None

    df = df.dropna(subset=['LATITUDE', 'LONGITUDE'])

    # Cria dicionário de diretorias para pintar o mapa
    dict_diretorias = {}
    if 'CIDADE' in df.columns and 'DIRETORIA' in df.columns:
        for _, row in df.iterrows():
            # Limpa acentos para garantir que o nome cruze perfeitamente com o GeoJSON
            cidade_limpa = unicodedata.normalize('NFKD', str(row['CIDADE']).upper().strip()).encode('ascii', 'ignore').decode('utf-8')
            dict_diretorias[cidade_limpa] = row['DIRETORIA']

    return df, geojson_rs, dict_diretorias

# Desempacota corretamente as 3 variáveis
df_lojas, geojson_rs, dict_diretorias = load_data()

# Separa quem é agente disponível
if 'AGENTE_DISPONIVEL' in df_lojas.columns:
    df_agentes = df_lojas[df_lojas['AGENTE_DISPONIVEL'] == 'SIM'].copy()
else:
    df_agentes = pd.DataFrame()

# ==========================================
# 2. FUNÇÃO DE ROTA (OSRM)
# ==========================================
def calcular_rota_real(origem, destino):
    url = f"http://router.project-osrm.org/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}?overview=false"
    try:
        resposta = requests.get(url, timeout=5)
        if resposta.status_code == 200:
            dados = resposta.json()
            if dados['code'] == 'Ok':
                distancia_km = dados['routes'][0]['distance'] / 1000
                tempo_min = dados['routes'][0]['duration'] / 60
                return distancia_km, tempo_min
    except:
        pass
    # Se a API falhar, retorna a distância em linha reta e um tempo estimado (60km/h)
    dist_reta = geodesic(origem, destino).kilometers
    return dist_reta, (dist_reta / 60) * 60

# ==========================================
# 3. INTERFACE E MEMÓRIA (SESSION STATE)
# ==========================================
if 'cidade_selecionada' not in st.session_state:
    st.session_state.cidade_selecionada = "🗺️ VISÃO GERAL (TODAS AS LOJAS)"
if 'loja_selecionada' not in st.session_state:
    st.session_state.loja_selecionada = None

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
# LÓGICA 1: VISÃO GERAL DO ESTADO
# ==========================================
if st.session_state.cidade_selecionada == "🗺️ VISÃO GERAL (TODAS AS LOJAS)":
    st.info("📍 Clique em qualquer marcador no mapa para ir direto para a análise de raio daquela loja.")

    m = folium.Map(location=[-30.0, -53.5], zoom_start=6, tiles="OpenStreetMap")

    # Cores das Diretorias
    cores_dir = {
        'CENTRAL': '#F8DC00', 'LESTE': '#17E3CB', 'NORTE': '#FE952B',
        'OESTE': '#0027BD', 'SUL': '#A11FFF', 'Sem Diretoria': '#cccccc'
    }

    def limpar_nome_geojson(nome):
        if pd.isna(nome) or not nome: return "SEM CIDADE"
        return unicodedata.normalize('NFKD', str(nome).upper().strip()).encode('ascii', 'ignore').decode('utf-8')

    # Adiciona o GeoJSON colorido
    folium.GeoJson(
        geojson_rs,
        style_function=lambda feature: {
            'fillColor': cores_dir.get(dict_diretorias.get(limpar_nome_geojson(feature['properties'].get('name_muni')), 'Sem Diretoria'), '#cccccc'),
            'color': 'black', 'weight': 0.5, 'fillOpacity': 0.5,
        }
    ).add_to(m)

    col_nome_loja = 'ENDERECO' if 'ENDERECO' in df_lojas.columns else df_lojas.columns[0]

    # Adiciona os marcadores
    for idx, row in df_lojas.iterrows():
        tem_agente = row.get('AGENTE_DISPONIVEL', 'NAO') == 'SIM'
        cor_pino = "green" if tem_agente else "blue"
        icone_pino = "user" if tem_agente else "info-sign"
        texto = f"👤 Agente Disponível: {row.get('NOME_AGENTE', '')}" if tem_agente else f"🏢 Loja: {row[col_nome_loja]}"

        folium.Marker(
            location=[row['LATITUDE'], row['LONGITUDE']],
            tooltip=f"{texto} (Clique para analisar)",
            icon=folium.Icon(color=cor_pino, icon=icone_pino)
        ).add_to(m)

    mapa_geral = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])

    # Captura o clique
    if mapa_geral and mapa_geral.get("last_object_clicked"):
        lat_c, lng_c = mapa_geral["last_object_clicked"]["lat"], mapa_geral["last_object_clicked"]["lng"]
        df_lojas['LAT_R'] = df_lojas['LATITUDE'].round(4)
        df_lojas['LNG_R'] = df_lojas['LONGITUDE'].round(4)

        loja_clicada = df_lojas[(df_lojas['LAT_R'] == round(lat_c, 4)) & (df_lojas['LNG_R'] == round(lng_c, 4))]

        if not loja_clicada.empty:
            st.session_state.cidade_selecionada = loja_clicada.iloc[0]['CIDADE']
            st.session_state.loja_selecionada = loja_clicada.iloc[0][col_nome_loja]
            st.rerun()

# ==========================================
# LÓGICA 2: ANÁLISE DE RAIO
# ==========================================
else:
    with col2:
        lojas_da_cidade = df_lojas[df_lojas['CIDADE'] == st.session_state.cidade_selecionada]
        col_nome_loja = 'ENDERECO' if 'ENDERECO' in lojas_da_cidade.columns else lojas_da_cidade.columns[0]
        lista_lojas = lojas_da_cidade[col_nome_loja].tolist()

        index_loja = lista_lojas.index(st.session_state.loja_selecionada) if st.session_state.loja_selecionada in lista_lojas else 0
        loja_selecionada = st.selectbox("2️⃣ Escolha a sua Loja:", lista_lojas, index=index_loja)
        st.session_state.loja_selecionada = loja_selecionada

    with col3:
        raio_km = st.slider("3️⃣ Defina o Raio de Busca (em KM):", min_value=20.0, max_value=150.0, value=50.0, step=5.0)

    if st.button("⬅️ Voltar para Visão Geral"):
        st.session_state.cidade_selecionada = "🗺️ VISÃO GERAL (TODAS AS LOJAS)"
        st.rerun()

    dados_loja = lojas_da_cidade[lojas_da_cidade[col_nome_loja] == loja_selecionada].iloc[0]
    coord_loja = (dados_loja['LATITUDE'], dados_loja['LONGITUDE'])

    # Filtro de Agentes
    if not df_agentes.empty:
        df_agentes['DISTANCIA_RETA_KM'] = df_agentes.apply(lambda row: geodesic(coord_loja, (row['LATITUDE'], row['LONGITUDE'])).kilometers, axis=1)
        df_agentes = df_agentes[df_agentes['DISTANCIA_RETA_KM'] > 0.05] # Remove a própria loja

        agentes_proximos = df_agentes[df_agentes['DISTANCIA_RETA_KM'] <= (raio_km * 1.5)].copy()

        if not agentes_proximos.empty:
            with st.spinner("Calculando rotas reais..."):
                rotas = agentes_proximos.apply(lambda row: calcular_rota_real(coord_loja, (row['LATITUDE'], row['LONGITUDE'])), axis=1)
                agentes_proximos['DISTANCIA_REAL_KM'] = [r[0] for r in rotas]
                agentes_proximos['TEMPO_MINUTOS'] = [r[1] for r in rotas]
    else:
        agentes_proximos = pd.DataFrame()

    # Mapa de Raio
    m = folium.Map(location=[coord_loja[0], coord_loja[1]], zoom_start=12, tiles="OpenStreetMap")

    folium.Circle(
        location=[coord_loja[0], coord_loja[1]], radius=raio_km * 1000,
        color="#0055FF", fill=True, fill_opacity=0.15, tooltip=f"Raio de {raio_km}km"
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
            cor_pino = "green" if dist <= raio_km else "lightgray"

            folium.Marker(
                location=[row['LATITUDE'], row['LONGITUDE']],
                tooltip=f"👤 {row.get('NOME_AGENTE', 'Agente')} | {row['CIDADE']}<br>🚗 {dist:.1f} km | ⏱️ {tempo:.0f} min",
                icon=folium.Icon(color=cor_pino, icon="user")
            ).add_to(m)

    st_folium(m, use_container_width=True, height=600, returned_objects=[])

    # Tabela
    if not agentes_proximos.empty:
        st.subheader(f"📋 Agentes disponíveis num raio de {raio_km}km (Rota Real)")
        agentes_dentro = agentes_proximos[agentes_proximos['DISTANCIA_REAL_KM'] <= raio_km]

        if not agentes_dentro.empty:
            tabela = agentes_dentro[['NOME_AGENTE', 'CIDADE', col_nome_loja, 'DISTANCIA_REAL_KM', 'TEMPO_MINUTOS']].sort_values('DISTANCIA_REAL_KM')
            tabela['DISTANCIA_REAL_KM'] = tabela['DISTANCIA_REAL_KM'].round(1).astype(str) + " km"
            tabela['TEMPO_MINUTOS'] = tabela['TEMPO_MINUTOS'].round(0).astype(int).astype(str) + " min"
            tabela.columns = ['Nome do Agente', 'Cidade Origem', 'Local de Origem', 'Distância (Carro)', 'Tempo Estimado']
            st.dataframe(tabela, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum agente encontrado dentro deste raio considerando as rotas de carro.")

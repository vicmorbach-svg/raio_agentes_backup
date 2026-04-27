import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import requests
import json
import unicodedata

st.set_page_config(page_title="Realocação de Agentes", layout="wide")
st.title("🔄 Realocação de Agentes Backup")
st.markdown("Encontre os agentes disponíveis mais próximos para cobrir a necessidade da sua loja, considerando o tempo real de deslocamento.")

# ==========================================
# 1. FUNÇÕES DE DADOS E ROTAS
# ==========================================
@st.cache_data
def load_data():
    try:
        df_lojas = pd.read_excel("enderecos_com_coordenadas.xlsx")
        with open("rs_municipios.geojson", "r", encoding="utf-8") as f:
            geojson_rs = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ Arquivos não encontrados na pasta. Verifique o Excel e o GeoJSON.")
        st.stop()

    df_lojas.columns = df_lojas.columns.str.upper().str.strip()

    # Limpeza de Coordenadas
    if 'LATITUDE' in df_lojas.columns and 'LONGITUDE' in df_lojas.columns:
        df_lojas['LATITUDE'] = pd.to_numeric(df_lojas['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        df_lojas['LONGITUDE'] = pd.to_numeric(df_lojas['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        df_lojas.loc[(df_lojas['LATITUDE'] < -90) | (df_lojas['LATITUDE'] > 90), 'LATITUDE'] = None
        df_lojas.loc[(df_lojas['LONGITUDE'] < -180) | (df_lojas['LONGITUDE'] > 180), 'LONGITUDE'] = None

    df_lojas['CIDADE'] = df_lojas['CIDADE'].astype(str).str.upper().str.strip()

    # Separa os agentes disponíveis
    if 'AGENTE_DISPONIVEL' in df_lojas.columns:
        df_agentes = df_lojas[df_lojas['AGENTE_DISPONIVEL'].astype(str).str.upper().str.strip() == 'SIM'].copy()
    else:
        df_agentes = pd.DataFrame()

    return df_lojas, df_agentes, geojson_rs

def calcular_rota_real(origem, destino):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{origem[1]},{origem[0]};{destino[1]},{destino[0]}?overview=false"
        resposta = requests.get(url, timeout=5)
        dados = resposta.json()
        if dados.get("code") == "Ok":
            distancia_km = dados["routes"][0]["distance"] / 1000
            tempo_min = dados["routes"][0]["duration"] / 60
            return distancia_km, tempo_min
    except:
        pass
    return geodesic(origem, destino).kilometers, geodesic(origem, destino).kilometers * 1.2

df_lojas, df_agentes, geojson_rs = load_data()
col_nome_loja = 'ENDERECO' if 'ENDERECO' in df_lojas.columns else df_lojas.columns[0]

# ==========================================
# 2. FILTRO DE ENDEREÇOS VÁLIDOS PARA O MENU
# ==========================================
# Remove linhas onde o endereço é vazio, nulo ou "nan"
mascara_endereco_valido = df_lojas[col_nome_loja].notna() & \
                          (df_lojas[col_nome_loja].astype(str).str.strip() != '') & \
                          (df_lojas[col_nome_loja].astype(str).str.lower() != 'nan')

df_lojas_com_endereco = df_lojas[mascara_endereco_valido]

# ==========================================
# 3. CONTROLE DE ESTADO (SESSION STATE)
# ==========================================
if 'cidade_selecionada' not in st.session_state:
    st.session_state.cidade_selecionada = "🗺️ VISÃO GERAL (TODAS AS LOJAS)"
if 'loja_selecionada' not in st.session_state:
    st.session_state.loja_selecionada = None

# ==========================================
# 4. INTERFACE DE SELEÇÃO
# ==========================================
col1, col2, col3 = st.columns(3)

with col1:
    # Usa apenas as cidades que têm pelo menos uma loja com endereço válido
    cidades_disponiveis = ["🗺️ VISÃO GERAL (TODAS AS LOJAS)"] + sorted(df_lojas_com_endereco['CIDADE'].unique())
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
    st.info("📍 Clique em qualquer marcador azul no mapa para ir direto para a análise de raio daquela loja.")

    df_todas_lojas = df_lojas.dropna(subset=['LATITUDE', 'LONGITUDE']).copy()

    m = folium.Map(location=[-30.0, -53.5], zoom_start=7, tiles="OpenStreetMap")

    # Configuração do GeoJSON (Cores por Diretoria)
    dicionario_cores = {
        'CENTRAL': '#F8DC00', 'LESTE': '#17E3CB', 'NORTE': '#FE952B',
        'OESTE': '#0027BD', 'SUL': '#A11FFF', 'Sem Diretoria': '#cccccc'
    }

    dict_diretorias = dict(zip(df_lojas['CIDADE'], df_lojas['DIRETORIA'].fillna('Sem Diretoria')))

    def limpar_nome_geojson(nome):
        if pd.isna(nome) or not nome: return "SEM CIDADE"
        return unicodedata.normalize('NFKD', str(nome).upper().strip()).encode('ascii', 'ignore').decode('utf-8')

    folium.GeoJson(
        geojson_rs,
        style_function=lambda feature: {
            'fillColor': dicionario_cores.get(dict_diretorias.get(limpar_nome_geojson(feature['properties'].get('name_muni')), 'Sem Diretoria'), '#cccccc'),
            'color': 'black', 'weight': 0.5, 'fillOpacity': 0.6,
        }
    ).add_to(m)

        # Adiciona os pins para todas as lojas/agentes
    for idx, row in df_todas_lojas.iterrows():
        endereco_vazio = pd.isna(row[col_nome_loja]) or str(row[col_nome_loja]).strip() == '' or str(row[col_nome_loja]).lower() == 'nan'
        tem_agente = str(row.get('AGENTE_DISPONIVEL', '')).strip().upper() == 'SIM'

        if endereco_vazio:
            cor_pino = "orange"
            icone_pino = "user"
            texto_tooltip = f"📍 Apenas Agente: {row['CIDADE']}"
        elif tem_agente:
            cor_pino = "green"
            icone_pino = "star"
            texto_tooltip = f"✅ Loja com Agente: {row[col_nome_loja]} ({row['CIDADE']})"
        else:
            cor_pino = "blue"
            icone_pino = "info-sign"
            texto_tooltip = f"🏢 Apenas Loja: {row[col_nome_loja]} ({row['CIDADE']})"

        folium.Marker(
            location=[row['LATITUDE'], row['LONGITUDE']],
            tooltip=texto_tooltip,
            icon=folium.Icon(color=cor_pino, icon=icone_pino)
        ).add_to(m)
    # --- LEGENDA DO MAPA ---
    with st.container(border=True):
        st.markdown("""
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
            <div style="display: flex; justify-content: space-around; font-size: 15px;">
                <span><i class="fa-solid fa-circle-info" style="color: #38Aadd; font-size: 18px;"></i> <b>Loja</b></span>
                <span><i class="fa-solid fa-star" style="color: #72b026; font-size: 18px;"></i> <b>Loja + Agente</b></span>
                <span><i class="fa-solid fa-user" style="color: #f69730; font-size: 18px;"></i> <b>Agente Backup</b></span>
            </div>
        """, unsafe_allow_html=True)
    
    mapa_geral = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])

    # Captura clique no mapa
    if mapa_geral and mapa_geral.get("last_object_clicked"):
        lat_clicada = mapa_geral["last_object_clicked"]["lat"]
        lng_clicada = mapa_geral["last_object_clicked"]["lng"]

        df_todas_lojas['LAT_ROUND'] = df_todas_lojas['LATITUDE'].round(4)
        df_todas_lojas['LNG_ROUND'] = df_todas_lojas['LONGITUDE'].round(4)

        loja_clicada = df_todas_lojas[
            (df_todas_lojas['LAT_ROUND'] == round(lat_clicada, 4)) & 
            (df_todas_lojas['LNG_ROUND'] == round(lng_clicada, 4))
        ]

        if not loja_clicada.empty:
            # Só redireciona se a loja clicada tiver endereço válido
            end_clicado = loja_clicada.iloc[0][col_nome_loja]
            if pd.notna(end_clicado) and str(end_clicado).strip() != '' and str(end_clicado).lower() != 'nan':
                st.session_state.cidade_selecionada = loja_clicada.iloc[0]['CIDADE']
                st.session_state.loja_selecionada = end_clicado
                st.rerun()
            else:
                st.warning("⚠️ Este ponto não possui um endereço válido para análise de raio.")

# ==========================================
# LÓGICA 2: ANÁLISE DE RAIO
# ==========================================
else:
    with col2:
        # Filtra as lojas da cidade selecionada APENAS com endereços válidos
        lojas_da_cidade = df_lojas_com_endereco[df_lojas_com_endereco['CIDADE'] == st.session_state.cidade_selecionada]
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

        # Verifica o status da loja de destino
    endereco_vazio = pd.isna(dados_loja[col_nome_loja]) or str(dados_loja[col_nome_loja]).strip() == '' or str(dados_loja[col_nome_loja]).lower() == 'nan'
    tem_agente = str(dados_loja.get('AGENTE_DISPONIVEL', '')).strip().upper() == 'SIM'

    if endereco_vazio:
        cor_pino_destino = "orange"
        texto_destino = f"📍 DESTINO: {dados_loja['CIDADE']} (Apenas Agente)"
    elif tem_agente:
        cor_pino_destino = "green"
        texto_destino = f"✅ DESTINO: {dados_loja[col_nome_loja]} (Loja com Agente)"
    else:
        cor_pino_destino = "blue"
        texto_destino = f"🏢 DESTINO: {dados_loja[col_nome_loja]} (Apenas Loja)"

    # Pin da Loja de Destino
    folium.Marker(
        location=[coord_loja[0], coord_loja[1]],
        tooltip=texto_destino,
        icon=folium.Icon(color=cor_pino_destino, icon="star")
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

    # --- LEGENDA DO MAPA ---
    with st.container(border=True):
        st.markdown("""
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
            <div style="display: flex; justify-content: space-around; font-size: 15px;">
                <span><i class="fa-solid fa-circle-info" style="color: #38Aadd; font-size: 18px;"></i> <b>Loja</b></span>
                <span><i class="fa-solid fa-star" style="color: #72b026; font-size: 18px;"></i> <b>Loja + Agente</b></span>
                <span><i class="fa-solid fa-user" style="color: #f69730; font-size: 18px;"></i> <b>Agente Backup</b></span>
            </div>
        """, unsafe_allow_html=True)
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

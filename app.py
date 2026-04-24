import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import requests
import json
import geopandas as gpd
import unicodedata


st.set_page_config(page_title="Realocação de Agentes", layout="wide")
st.title("🔄 Realocação Inteligente de Agentes")
st.markdown("Encontre os agentes disponíveis mais próximos para cobrir a necessidade da sua loja.")

# ==========================================
# 1. CARREGAMENTO E LIMPEZA DOS DADOS
# ==========================================
@st.cache_data
def load_data():
    try:
        df_lojas = pd.read_excel("enderecos_com_coordenadas.xlsx")
        df_lotericas = pd.read_excel("lotericas_enderecos_com_coordenadas.xlsx")
        mapa_rs = gpd.read_file("rs_municipios.geojson").to_crs(epsg=4326)
    except FileNotFoundError:
        st.error("⚠️ Arquivos não encontrados na pasta.")
        st.stop()

    # ... (Mantenha a sua limpeza de colunas e coordenadas existente aqui) ...
    df_lojas.columns = df_lojas.columns.str.upper().str.strip()
    # ...

    # --- TRATAMENTO DE ACENTOS E PADRONIZAÇÃO ---
    def padronizar_nomes(serie):
        return serie.astype(str).str.upper().str.strip().str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')

    df_lojas['CIDADE_TRATADA'] = padronizar_nomes(df_lojas['CIDADE'])
    mapa_rs['name_muni_tratado'] = padronizar_nomes(mapa_rs['name_muni'])

    # Cruzamento do mapa com as diretorias
    df_mapa = df_lojas[['CIDADE_TRATADA', 'DIRETORIA']].drop_duplicates(subset=['CIDADE_TRATADA'])
    mapa_diretorias = mapa_rs.merge(df_mapa, how="left", left_on="name_muni_tratado", right_on="CIDADE_TRATADA")
    mapa_diretorias['DIRETORIA'] = mapa_diretorias['DIRETORIA'].fillna('Sem Diretoria')

    return df_lojas, df_lotericas, mapa_diretorias

df_lojas, df_lotericas, mapa_diretorias = load_data()

    def limpar_coordenadas(df):
        if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
            # Converte para número
            df['LATITUDE'] = pd.to_numeric(df['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
            df['LONGITUDE'] = pd.to_numeric(df['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')

            # TRAVA DE SEGURANÇA: Transforma em vazio (NaN) qualquer coordenada fora do limite do planeta Terra
            df.loc[(df['LATITUDE'] < -90) | (df['LATITUDE'] > 90), 'LATITUDE'] = None
            df.loc[(df['LONGITUDE'] < -180) | (df['LONGITUDE'] > 180), 'LONGITUDE'] = None

        return df

    # Remove linhas sem coordenadas
    df = df.dropna(subset=['LATITUDE', 'LONGITUDE'])

    if 'CIDADE' in df.columns:
        df['CIDADE'] = df['CIDADE'].astype(str).str.upper().str.strip()
    else:
        st.error("⚠️ A coluna 'CIDADE' não foi encontrada na planilha.")
        st.stop()

    # Garante que as novas colunas existam para evitar erros
    if 'AGENTE_DISPONIVEL' not in df.columns:
        df['AGENTE_DISPONIVEL'] = 'NAO'
    if 'NOME_AGENTE' not in df.columns:
        df['NOME_AGENTE'] = 'Não Informado'

    return df

df_lojas = load_data()

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

    # Descobre a posição da cidade salva na memória
    index_cidade = cidades_disponiveis.index(st.session_state.cidade_selecionada) if st.session_state.cidade_selecionada in cidades_disponiveis else 0

    cidade_selecionada = st.selectbox("1️⃣ Escolha a Cidade:", cidades_disponiveis, index=index_cidade)

    # Se o usuário mudar a cidade manualmente, atualiza a memória e recarrega
    if cidade_selecionada != st.session_state.cidade_selecionada:
        st.session_state.cidade_selecionada = cidade_selecionada
        st.session_state.loja_selecionada = None
        st.rerun()

# ==========================================
# LÓGICA 1: VISÃO GERAL DO ESTADO (FOLIUM)
# ==========================================
if st.session_state.cidade_selecionada == "🗺️ VISÃO GERAL (TODAS AS LOJAS)":
    st.info("📍 Clique em qualquer marcador no mapa para ir direto para a análise de raio daquela loja. Pinos verdes indicam agentes disponíveis.")

    df_todas_lojas = df_lojas.dropna(subset=['LATITUDE', 'LONGITUDE']).copy()
    col_nome_loja = 'ENDERECO' if 'ENDERECO' in df_todas_lojas.columns else df_todas_lojas.columns[0]

        # Adicione este bloco antes de renderizar o mapa da "VISÃO GERAL"
    st.subheader("📊 Resumo de Agentes por Diretoria")
    
    # Filtra apenas quem tem agente e conta por diretoria
    df_agentes_ativos = df_lojas[df_lojas['AGENTE_DISPONIVEL'] == 'SIM']
    contagem_diretoria = df_agentes_ativos.groupby('DIRETORIA').size().reset_index(name='Agentes Disponíveis')
    
    # Exibe os dados em colunas para ficar visualmente agradável
    cols = st.columns(len(contagem_diretoria))
    for i, row in contagem_diretoria.iterrows():
        with cols[i]:
            st.metric(label=row['DIRETORIA'], value=row['Agentes Disponíveis'])
    
    m = folium.Map(location=[-30.0, -53.5], zoom_start=6, tiles="OpenStreetMap")
        # CORES FIXAS DAS REGIONAIS
    dicionario_cores = {
        'CENTRAL': '#F8DC00',
        'LESTE': '#17E3CB',
        'NORTE': '#FE952B',
        'OESTE': '#0027BD',
        'SUL': '#A11FFF',
        'Sem Diretoria': '#cccccc' # Cinza para cidades sem loja
    }

    # Adiciona os polígonos coloridos ao mapa
    folium.GeoJson(
        mapa_diretorias,
        style_function=lambda feature: {
            'fillColor': dicionario_cores.get(feature['properties']['DIRETORIA'], '#cccccc'),
            'color': 'black',
            'weight': 0.5,
            'fillOpacity': 0.6,
        },
        tooltip=folium.GeoJsonTooltip(fields=['name_muni', 'DIRETORIA'], aliases=['Cidade:', 'Diretoria:'])
    ).add_to(m)

    for idx, row in df_todas_lojas.iterrows():
        # Verifica se a coluna AGENTE_DISPONIVEL está marcada como SIM
        tem_agente = str(row.get('AGENTE_DISPONIVEL', '')).strip().upper() == 'SIM'

        # Define a cor, ícone e texto com base na disponibilidade
        if tem_agente:
            cor_pino = "green"
            icone_pino = "user"
            texto_tooltip = f"✅ {row[col_nome_loja]} (COM AGENTE) - Clique para analisar"
        else:
            cor_pino = "blue"
            icone_pino = "info-sign"
            texto_tooltip = f"🏢 {row[col_nome_loja]} - Clique para analisar"

        folium.Marker(
            location=[row['LATITUDE'], row['LONGITUDE']],
            tooltip=texto_tooltip,
            icon=folium.Icon(color=cor_pino, icon=icone_pino)
        ).add_to(m)

    # 🚨 CAPTURA O CLIQUE NO MAPA
    mapa_geral = st_folium(m, use_container_width=True, height=600, returned_objects=["last_object_clicked"])

    # Se houver um clique válido em um marcador
    if mapa_geral and mapa_geral.get("last_object_clicked"):
        lat_clicada = mapa_geral["last_object_clicked"]["lat"]
        lng_clicada = mapa_geral["last_object_clicked"]["lng"]

        # Arredonda as coordenadas para garantir que encontre a loja exata no Excel
        df_todas_lojas['LAT_ROUND'] = df_todas_lojas['LATITUDE'].round(4)
        df_todas_lojas['LNG_ROUND'] = df_todas_lojas['LONGITUDE'].round(4)

        loja_clicada = df_todas_lojas[
            (df_todas_lojas['LAT_ROUND'] == round(lat_clicada, 4)) & 
            (df_todas_lojas['LNG_ROUND'] == round(lng_clicada, 4))
        ]

        if not loja_clicada.empty:
            # Salva a cidade e a loja na memória e recarrega a página automaticamente
            st.session_state.cidade_selecionada = loja_clicada.iloc[0]['CIDADE']
            st.session_state.loja_selecionada = loja_clicada.iloc[0][col_nome_loja]
            st.rerun()

# ==========================================
# LÓGICA 2: ANÁLISE DE RAIO (FOLIUM)
# ==========================================
else:
    with col2:
        lojas_da_cidade = df_lojas[df_lojas['CIDADE'] == st.session_state.cidade_selecionada]
        col_nome_loja = 'ENDERECO' if 'ENDERECO' in lojas_da_cidade.columns else lojas_da_cidade.columns[0]
        lista_lojas = lojas_da_cidade[col_nome_loja].tolist()

        # Verifica se a loja veio da memória (do clique no mapa)
        index_loja = 0
        if st.session_state.loja_selecionada in lista_lojas:
            index_loja = lista_lojas.index(st.session_state.loja_selecionada)

        loja_selecionada = st.selectbox("2️⃣ Escolha a sua Loja:", lista_lojas, index=index_loja)
        st.session_state.loja_selecionada = loja_selecionada

    with col3:
        # Aumentei o limite do raio para 50km caso queira buscar agentes em cidades vizinhas
        raio_km = st.slider("3️⃣ Defina o Raio de Busca (em KM):", min_value=0.5, max_value=50.0, value=10.0, step=0.5)


    # Pega as coordenadas da loja selecionada
    dados_loja = lojas_da_cidade[lojas_da_cidade[col_nome_loja] == loja_selecionada].iloc[0]
    coord_loja = (dados_loja['LATITUDE'], dados_loja['LONGITUDE'])

    # Filtra TODOS os agentes disponíveis no estado (ignorando a cidade selecionada)
    df_agentes = df_lojas[df_lojas['AGENTE_DISPONIVEL'].astype(str).str.upper().str.strip() == 'SIM'].copy()

    # Calcula a distância da loja para todos os agentes
    def calcular_rota_real(coord_origem, coord_destino):
    # A API do OSRM exige o formato: longitude,latitude
    url = f"http://router.project-osrm.org/route/v1/driving/{coord_origem[1]},{coord_origem[0]};{coord_destino[1]},{coord_destino[0]}?overview=false"

    try:
        resposta = requests.get(url)
        dados = resposta.json()

        if dados.get('code') == 'Ok':
            distancia_km = dados['routes'][0]['distance'] / 1000
            tempo_minutos = dados['routes'][0]['duration'] / 60
            return distancia_km, tempo_minutos
    except Exception as e:
        print(f"Erro na API de rotas: {e}")

    # Retorna vazio se a API falhar
    return None, None

    if not df_agentes.empty:
        df_agentes['DISTANCIA_KM'] = df_agentes.apply(calcular_distancia, axis=1)
        # Remove a própria loja da lista de agentes (distância muito próxima a zero)
        df_agentes = df_agentes[df_agentes['DISTANCIA_KM'] > 0.05] 
    else:
        st.warning("Nenhum agente marcado como 'SIM' na coluna AGENTE_DISPONIVEL foi encontrado na planilha.")

    # Cria o mapa base centrado na loja selecionada
    m = folium.Map(location=[coord_loja[0], coord_loja[1]], zoom_start=12, tiles="OpenStreetMap")

    # Desenha o círculo do raio
    folium.Circle(
        location=[coord_loja[0], coord_loja[1]],
        radius=raio_km * 1000,
        color="#0055FF",
        fill=True,
        fill_color="#0055FF",
        fill_opacity=0.15,
        tooltip=f"Raio de {raio_km}km"
    ).add_to(m)

    # Pin da Loja de Destino (Azul com estrela)
    folium.Marker(
        location=[coord_loja[0], coord_loja[1]],
        tooltip=f"🏢 DESTINO: {dados_loja[col_nome_loja]}",
        icon=folium.Icon(color="blue", icon="star")
    ).add_to(m)

    # Adiciona os Pins dos Agentes
    if not df_agentes.empty:
        for idx, row in df_agentes.iterrows():
            dist = row['DISTANCIA_KM']

            if dist <= raio_km:
                cor_pino = "green"
                icone_pino = "user"
            else:
                cor_pino = "lightgray" # Agentes fora do raio ficam cinza para não poluir
                icone_pino = "user"

            folium.Marker(
                location=[row['LATITUDE'], row['LONGITUDE']],
                tooltip=f"👤 Agente: {row['NOME_AGENTE']} | {row['CIDADE']} ({dist:.1f} km)",
                icon=folium.Icon(color=cor_pino, icon=icone_pino)
            ).add_to(m)

    st_folium(m, use_container_width=True, height=600, returned_objects=[])

    # Tabela de Resultados
    if not df_agentes.empty:
        st.subheader(f"📋 Agentes disponíveis num raio de {raio_km}km")
        agentes_dentro_raio = df_agentes[df_agentes['DISTANCIA_KM'] <= raio_km]

        if not agentes_dentro_raio.empty:
            tabela_exibicao = agentes_dentro_raio[['NOME_AGENTE', 'CIDADE', col_nome_loja, 'DISTANCIA_KM']].sort_values('DISTANCIA_KM')
            tabela_exibicao['DISTANCIA_KM'] = tabela_exibicao['DISTANCIA_KM'].round(2).astype(str) + " km"
            tabela_exibicao.columns = ['Nome do Agente', 'Cidade Origem', 'Local/Loja de Origem', 'Distância até o Destino']
            st.dataframe(tabela_exibicao, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum agente disponível encontrado dentro deste raio. Tente aumentar a distância no controle acima.")

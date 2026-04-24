import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic

st.set_page_config(page_title="Realocação de Agentes", layout="wide")
st.title("🔄 Realocação Inteligente de Agentes")
st.markdown("Encontre os agentes disponíveis mais próximos para cobrir a necessidade da sua loja.")

# ==========================================
# 1. CARREGAMENTO E LIMPEZA DOS DADOS
# ==========================================
@st.cache_data
def load_data():
    try:
        # Carrega apenas a base principal agora
        df = pd.read_excel("enderecos_com_coordenadas.xlsx")
    except FileNotFoundError:
        st.error("⚠️ Arquivo 'enderecos_com_coordenadas.xlsx' não encontrado na pasta.")
        st.stop()

    # Padroniza as colunas
    df.columns = df.columns.str.upper().str.strip()

    # Limpeza de coordenadas
    if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
        df['LATITUDE'] = pd.to_numeric(df['LATITUDE'].astype(str).str.replace(',', '.'), errors='coerce')
        df['LONGITUDE'] = pd.to_numeric(df['LONGITUDE'].astype(str).str.replace(',', '.'), errors='coerce')

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

# ==========================================
# 2. INTERFACE DE SELEÇÃO
# ==========================================
col1, col2, col3 = st.columns(3)

with col1:
    cidades_disponiveis = ["🗺️ VISÃO GERAL (TODAS AS LOJAS)"] + sorted(df_lojas['CIDADE'].unique())
    cidade_selecionada = st.selectbox("1️⃣ Cidade da Loja de Destino:", cidades_disponiveis)

# ==========================================
# LÓGICA 1: VISÃO GERAL DO ESTADO
# ==========================================
if cidade_selecionada == "🗺️ VISÃO GERAL (TODAS AS LOJAS)":
    st.info("📍 Mostrando todas as localizações. Lojas em azul, Agentes disponíveis em verde.")

    col_nome_loja = 'ENDERECO' if 'ENDERECO' in df_lojas.columns else df_lojas.columns[0]
    m = folium.Map(location=[-30.0, -53.5], zoom_start=6, tiles="OpenStreetMap")

    for idx, row in df_lojas.iterrows():
        disponivel = str(row['AGENTE_DISPONIVEL']).strip().upper() == 'SIM'

        if disponivel:
            cor = "green"
            icone = "user"
            texto_tooltip = f"Agente Disponível: {row['NOME_AGENTE']} ({row['CIDADE']})"
        else:
            cor = "blue"
            icone = "info-sign"
            texto_tooltip = f"Loja: {row[col_nome_loja]}"

        folium.Marker(
            location=[row['LATITUDE'], row['LONGITUDE']],
            tooltip=texto_tooltip,
            icon=folium.Icon(color=cor, icon=icone)
        ).add_to(m)

    st_folium(m, use_container_width=True, height=600, returned_objects=[])

# ==========================================
# LÓGICA 2: BUSCA DE AGENTES POR RAIO
# ==========================================
else:
    with col2:
        lojas_da_cidade = df_lojas[df_lojas['CIDADE'] == cidade_selecionada]
        col_nome_loja = 'ENDERECO' if 'ENDERECO' in lojas_da_cidade.columns else lojas_da_cidade.columns[0]
        loja_selecionada = st.selectbox("2️⃣ Loja que precisa de ajuda:", lojas_da_cidade[col_nome_loja].tolist())

    with col3:
        # Aumentei o raio máximo para 50km para pegar cidades vizinhas
        raio_km = st.slider("3️⃣ Raio de Busca (em KM):", min_value=1.0, max_value=50.0, value=10.0, step=1.0)

    # Pega as coordenadas da loja selecionada
    dados_loja = lojas_da_cidade[lojas_da_cidade[col_nome_loja] == loja_selecionada].iloc[0]
    coord_loja = (dados_loja['LATITUDE'], dados_loja['LONGITUDE'])

    # Filtra TODOS os agentes disponíveis no estado (ignorando a cidade selecionada)
    df_agentes = df_lojas[df_lojas['AGENTE_DISPONIVEL'].astype(str).str.upper().str.strip() == 'SIM'].copy()

    # Calcula a distância da loja para todos os agentes
    def calcular_distancia(row):
        coord_agente = (row['LATITUDE'], row['LONGITUDE'])
        return geodesic(coord_loja, coord_agente).kilometers

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

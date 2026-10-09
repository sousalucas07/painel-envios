import os
import time
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

# 📌 INJEÇÃO AUTOMÁTICA DE SECRETS NA NUVEM (Para o os.getenv funcionar no Streamlit Cloud)
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, str):
                os.environ[k] = v
except Exception:
    pass

# Importa as funções da planilha, monitoramento e sincronização
try:
    from sheets import (
        deletar_envio_sheets,
        ler_envios_sheets,
        registrar_envio_sheets,
    )
except ImportError:
    ler_envios_sheets = deletar_envio_sheets = registrar_envio_sheets = None

try:
    from tracker import rodar_monitoramento
except ImportError:
    rodar_monitoramento = None

try:
    from atualizar_tarefas import sincronizar_links_tarefas
except ImportError:
    sincronizar_links_tarefas = None

try:
    from leitor_foto import renderizar_aba_foto
except ImportError:
    renderizar_aba_foto = None

# Configuração da Página
st.set_page_config(
    page_title="Analytics Dashboard - USPS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Guarda o horário da última vez que o usuário visualizou/recarregou a tela
if "ultima_visualizacao" not in st.session_state:
    st.session_state["ultima_visualizacao"] = pd.Timestamp.now()

# Cria as Abas do app
tab_dashboard, tab_inserir, tab_foto = st.tabs([
    "📊 Painel de Acompanhamento",
    "📥 Inserir Rastreio Antigo",
    "📸 Adicionar Rastreio Passaporte",
])

# ==========================================
# ABA 1: DASHBOARD DE ACOMPANHAMENTO
# ==========================================
with tab_dashboard:
    col_t1, col_btn = st.columns([5, 1])
    with col_t1:
        st.title("📈 Painel de Análise - USPS")
        st.caption("Acompanhamento de Envios Consulares e Rastreio em Tempo Real")

    with col_btn:
        st.write("")
        if st.button("🔄 Recarregar Tela", use_container_width=True):
            st.session_state["ultima_visualizacao"] = pd.Timestamp.now()
            st.rerun()

    st.markdown("---")

    if ler_envios_sheets:
        df_envios = ler_envios_sheets()

        if not df_envios.empty:
            col_status = next(
                (c for c in df_envios.columns if "status" in c.lower()), None
            )
            col_rastreio = next(
                (
                    c
                    for c in df_envios.columns
                    if "rastreio" in c.lower() or "tracking" in c.lower()
                ),
                None,
            )
            col_nome = next(
                (c for c in df_envios.columns if "nome" in c.lower()), None
            )
            col_id = next(
                (
                    c
                    for c in df_envios.columns
                    if "id" in c.lower()
                    or "pedido" in c.lower()
                    or "bitrix" in c.lower()
                ),
                None,
            )

            col_ult_atualizacao = next(
                (
                    c
                    for c in df_envios.columns
                    if "ult" in c.lower() or "atualiz" in c.lower()
                ),
                None,
            )
            col_data_criacao = next(
                (c for c in df_envios.columns if "data" in c.lower()), None
            )

            df_envios["_is_atualizado"] = False
            if col_ult_atualizacao:
                datas_dt = pd.to_datetime(
                    df_envios[col_ult_atualizacao], errors="coerce"
                )
                df_envios["_is_atualizado"] = (
                    datas_dt > st.session_state["ultima_visualizacao"]
                )

            if col_ult_atualizacao:
                df_envios = df_envios.sort_values(
                    by=col_ult_atualizacao, ascending=False
                )
            elif col_data_criacao:
                df_envios = df_envios.sort_values(
                    by=col_data_criacao, ascending=False
                )
            else:
                df_envios = df_envios.iloc[::-1]

            df_envios = df_envios.reset_index(drop=True)

            df_envios["Categoria Status"] = "Outros"
            if col_status:
                df_envios.loc[
                    df_envios[col_status]
                    .astype(str)
                    .str.contains(
                        "DELIVERED|ENTREGUE|PICKED UP", case=False, na=False
                    ),
                    "Categoria Status",
                ] = "Entregues"
                df_envios.loc[
                    df_envios[col_status]
                    .astype(str)
                    .str.contains(
                        "TRANSIT|WAY|ACCEPT|PROGRESS|GERADA|COLETA|OUT FOR"
                        " DELIVERY",
                        case=False,
                        na=False,
                    ),
                    "Categoria Status",
                ] = "Em Trânsito"
                df_envios.loc[
                    df_envios[col_status]
                    .astype(str)
                    .str.contains(
                        "ERROR|ALERT|DEVOLVIDO|UNAVAILABLE|AGUARDANDO|PRE"
                        " TRANSIT",
                        case=False,
                        na=False,
                    ),
                    "Categoria Status",
                ] = "Pendentes de Envio"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📦 Total Registrados", len(df_envios))
            c2.metric(
                "🚚 Em Trânsito",
                len(df_envios[df_envios["Categoria Status"] == "Em Trânsito"]),
            )
            c3.metric(
                "🟢 Entregues",
                len(df_envios[df_envios["Categoria Status"] == "Entregues"]),
            )
            c4.metric(
                "📨 Pendentes de Envio",
                len(
                    df_envios[
                        df_envios["Categoria Status"] == "Pendentes de Envio"
                    ]
                ),
            )

            st.markdown("<br>", unsafe_allow_html=True)

            col_grafico1, col_grafico2 = st.columns([1, 1])

            cores_status = {
                "Pendentes de Envio": "#f9cdc8",
                "Entregues": "#2ecc71",
                "Em Trânsito": "#3498db",
                "Outros": "#95a5a6",
            }

            with col_grafico1:
                st.markdown("#### Distribuição de Status")
                status_counts = (
                    df_envios["Categoria Status"].value_counts().reset_index()
                )
                status_counts.columns = ["Status", "Quantidade"]
                status_counts["Status"] = status_counts["Status"].astype(str)

                cores_presentes = {
                    k: v
                    for k, v in cores_status.items()
                    if k in status_counts["Status"].values
                }

                fig_donut = px.pie(
                    status_counts,
                    names="Status",
                    values="Quantidade",
                    hole=0.5,
                    color="Status",
                    color_discrete_map=cores_presentes,
                    template="plotly_dark",
                )
                fig_donut.update_layout(
                    height=320,
                    margin=dict(t=20, b=20, l=10, r=10),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.15),
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            with col_grafico2:
                st.markdown("#### Volume por Categoria")
                fig_bars = px.bar(
                    status_counts,
                    x="Status",
                    y="Quantidade",
                    text_auto=True,
                    template="plotly_dark",
                )
                cores_lista = [
                    cores_status.get(val, "#95a5a6")
                    for val in status_counts["Status"]
                ]
                fig_bars.update_traces(marker_color=cores_lista)
                fig_bars.update_layout(
                    height=320,
                    bargap=0.6,
                    margin=dict(t=20, b=20, l=10, r=10),
                    xaxis_title="",
                    yaxis_title="",
                    showlegend=False,
                )
                st.plotly_chart(fig_bars, use_container_width=True)

            st.markdown("---")

            st.markdown("### 📋 Histórico Detalhado")

            col_filtro, col_btn_bitrix, col_btn_usps = st.columns([
                2.2,
                1.3,
                1.3,
            ])

            with col_filtro:
                lista_pedidos = (
                    sorted(df_envios[col_id].astype(str).unique().tolist())
                    if col_id
                    else []
                )
                filtro_selecionado = st.selectbox(
                    "🔍 Filtrar por Número do Pedido / ID:",
                    ["-- Mostrar Todos os Pedidos --"] + lista_pedidos,
                )

            with col_btn_bitrix:
                st.write("")
                st.write("")
                if st.button(
                    "🔗 Sincronizar Links Bitrix", use_container_width=True
                ):
                    if sincronizar_links_tarefas:
                        with st.spinner(
                            "Consultando e atualizando links no Bitrix..."
                        ):
                            sincronizar_links_tarefas()
                        st.success("✅ Links de tarefas atualizados!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(
                            "❌ Módulo 'atualizar_tarefas.py' não encontrado."
                        )

            with col_btn_usps:
                st.write("")
                st.write("")
                if st.button(
                    "⚡ Atualizar Status USPS", use_container_width=True
                ):
                    if rodar_monitoramento:
                        with st.spinner("Consultando USPS..."):
                            rodar_monitoramento()
                        st.success("✅ Rastreios atualizados!")
                        time.sleep(1)
                        st.rerun()

            df_exibir = df_envios.copy()
            if filtro_selecionado != "-- Mostrar Todos os Pedidos --" and col_id:
                df_exibir = df_exibir[
                    df_exibir[col_id].astype(str) == filtro_selecionado
                ]

            df_exibir.insert(0, "Excluir", False)

            config_colunas = {
                "Excluir": st.column_config.CheckboxColumn(
                    "Excluir",
                    help="Marque para apagar este registo da planilha",
                    default=False,
                )
            }

            col_tarefa = next(
                (c for c in df_exibir.columns if "tarefa" in c.lower()), None
            )
            if col_tarefa:
                config_colunas[col_tarefa] = st.column_config.LinkColumn(
                    "TAREFA", display_text="🔗 Abrir Tarefa"
                )

            if col_rastreio:
                config_colunas[col_rastreio] = st.column_config.LinkColumn(
                    "RASTREIO", display_text="📦 Rastrear USPS"
                )

            mask_atualizados = df_exibir.get(
                "_is_atualizado", pd.Series(False, index=df_exibir.index)
            )

            df_final_render = df_exibir.drop(
                columns=["Categoria Status", "_is_atualizado"], errors="ignore"
            )

            def estilo_linhas_atualizadas(df):
                styles = pd.DataFrame("", index=df.index, columns=df.columns)
                hoje_str = datetime.now().strftime("%Y-%m-%d")
                
                col_ult = next((c for c in df.columns if "ult" in c.lower() or "atualiz" in c.lower()), None)
                
                if col_ult:
                    for idx in df.index:
                        val_data = str(df.loc[idx, col_ult])
                        if hoje_str in val_data:
                            # Pinta a linha inteira com um verde sutil de destaque
                            styles.loc[idx, :] = "background-color: #1b4332; color: #ffffff; font-weight: bold;"
                return styles

            df_styled = df_final_render.style.apply(
                estilo_linhas_atualizadas, axis=None
            )

            colunas_bloqueadas = [
                c for c in df_final_render.columns if c != "Excluir"
            ]

            tabela_editada = st.data_editor(
                df_styled,
                use_container_width=True,
                column_config=config_colunas,
                disabled=colunas_bloqueadas,
                hide_index=True,
                key="tabela_historico_editor",
            )

            linhas_marcadas = tabela_editada[tabela_editada["Excluir"] == True]

            if not linhas_marcadas.empty:
                pedidos_para_apagar = (
                    linhas_marcadas[col_id].astype(str).tolist()
                )
                st.warning(
                    "⚠️ Pedidos selecionados para exclusão:"
                    f" **{', '.join(pedidos_para_apagar)}**"
                )

                if st.button(
                    "🗑️ Confirmar Exclusão dos Selecionados", type="primary"
                ):
                    com_sucesso = True
                    for pid in pedidos_para_apagar:
                        if deletar_envio_sheets:
                            if not deletar_envio_sheets(pid):
                                com_sucesso = False

                    if com_sucesso:
                        st.success("✅ Registos excluídos com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(
                            "❌ Ocorreu um erro ao excluir algum dos registos."
                        )

        else:
            st.warning("⚠️ Nenhuma etiqueta cadastrada na planilha ainda.")

# ==========================================
# ABA 2: INSERIR RASTREIO EXISTENTE
# ==========================================
with tab_inserir:
    st.title("📥 Cadastrar Etiqueta Antiga")
    st.markdown("Insira os dados de um envio antigo para ser monitorado.")
    st.markdown("---")

    TIPO_COMBINADO = "Cli - Con / Con - Cli"

    # O tipo fica FORA do form para a tela reagir à escolha (mostrar o campo da volta)
    in_tipo = st.selectbox(
        "Tipo de Envio:",
        ["IDA", "RETORNO", "IDA + RETORNO", TIPO_COMBINADO],
    )
    is_combinado = in_tipo == TIPO_COMBINADO

    if is_combinado:
        st.info(
            "ℹ️ Este tipo gera duas etiquetas. Informe o rastreio da ida e o"
            " da volta: elas serão cadastradas em linhas separadas"
            " (**Cli - Con** e **Con - Cli**)."
        )

    with st.form("form_inserir_rastreio"):
        col1, col2 = st.columns(2)
        with col1:
            in_pedido = st.text_input(
                "Número do Pedido / ID Bitrix *", placeholder="Ex: 262"
            )
            in_nome = st.text_input(
                "Nome do Cliente *", placeholder="Ex: Rodrigo Silva"
            )
        with col2:
            in_rastreio = st.text_input(
                "Código de Rastreio USPS - IDA (Cli → Con) *"
                if is_combinado
                else "Código de Rastreio USPS *",
                placeholder="Ex: 94055502...",
            )
            in_rastreio_volta = ""
            if is_combinado:
                in_rastreio_volta = st.text_input(
                    "Código de Rastreio USPS - VOLTA (Con → Cli) *",
                    placeholder="Ex: 94055502...",
                )
            in_data_criacao = st.date_input("🗓️ Data de Criação da Etiqueta *")

        st.markdown("---")
        btn_salvar = st.form_submit_button(
            "💾 Adicionar ao Monitoramento", use_container_width=True
        )

        if btn_salvar:
            if (
                not in_pedido.strip()
                or not in_nome.strip()
                or not in_rastreio.strip()
                or (is_combinado and not in_rastreio_volta.strip())
            ):
                st.warning("⚠️ Preencha os campos obrigatórios (*).")
            elif is_combinado and in_rastreio.strip() == in_rastreio_volta.strip():
                st.warning(
                    "⚠️ O rastreio da ida e o da volta não podem ser iguais."
                )
            else:
                # Monta a lista de etiquetas a cadastrar (1 linha, ou 2 no tipo combinado)
                if is_combinado:
                    envios = [
                        (in_rastreio.strip(), "Cli - Con"),
                        (in_rastreio_volta.strip(), "Con - Cli"),
                    ]
                else:
                    envios = [(in_rastreio.strip(), in_tipo)]

                with st.spinner("Adicionando à planilha..."):
                    data_formatada = in_data_criacao.strftime("%Y-%m-%d 00:00")
                    resultados = []
                    for codigo, tipo in envios:
                        dados_manuais = {
                            "num_pedido": in_pedido.strip(),
                            "nome": in_nome.strip(),
                            "tracking_code": codigo,
                            "tipo_envio": tipo,
                            "data_criacao": data_formatada,
                        }
                        ok = bool(
                            registrar_envio_sheets
                            and registrar_envio_sheets(dados_manuais)
                        )
                        resultados.append((tipo, ok))

                falhas = [tipo for tipo, ok in resultados if not ok]
                gravados = [tipo for tipo, ok in resultados if ok]

                if not falhas:
                    st.success(
                        f"✅ Etiqueta de **{in_nome}** cadastrada"
                        f" ({' + '.join(gravados)}) com data"
                        f" {in_data_criacao.strftime('%d/%m/%Y')}!"
                    )
                    st.balloons()
                else:
                    msg_erro = f"❌ Falha ao cadastrar: {', '.join(falhas)}."
                    if gravados:
                        msg_erro += (
                            f" Já foi gravado: {', '.join(gravados)}. Confira"
                            " a planilha antes de tentar de novo para não"
                            " duplicar."
                        )
                    st.error(msg_erro)

# ==========================================
# ABA 3: LER RASTREIOS POR FOTO (IA)
# ==========================================
with tab_foto:
    if renderizar_aba_foto:
        renderizar_aba_foto()
    else:
        st.error("❌ Módulo 'leitor_foto.py' não encontrado.")

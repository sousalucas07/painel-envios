import os
import re
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread
import pandas as pd
import requests
import streamlit as st

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ID da Planilha Privada de Auditoria
ID_PLANILHA_AUDITORIA = "1Xi3_aSY9ovKEPT8EcoLa7WNhMlITjU0FL6-csYTdCDM"


def conectar_client():
    # 1. Tenta autenticar via Secrets do Streamlit Cloud (Nuvem)
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
            return gspread.authorize(creds)
    except Exception:
        # Passa silenciosamente caso esteja rodando localmente sem o secrets.toml
        pass

    # 2. Se estiver no computador local, usa o credentials.json
    if os.path.exists("credentials.json"):
        try:
            creds = Credentials.from_service_account_file(
                "credentials.json", scopes=SCOPES
            )
            return gspread.authorize(creds)
        except Exception as e:
            print(f"❌ Erro ao ler credentials.json: {e}")
            return None

    print(
        "❌ Nenhuma credencial encontrada (nem em st.secrets nem em"
        " credentials.json)."
    )
    return None


def conectar_planilha_ativa():
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            credenciais = dict(st.secrets["gcp_service_account"])
            credenciais["private_key"] = credenciais["private_key"].replace('\\n', '\n')
            client = gspread.service_account_from_dict(credenciais)
            planilha = client.open("Rastreio de Etiquetas ShippingEasy")
            return planilha.get_worksheet(0)
    except Exception as e:
        print(f"⚠️ Aviso ao tentar ler st.secrets para Google Sheets: {e}")

    try:
        client = gspread.service_account(filename="credentials.json")
        planilha = client.open("Rastreio de Etiquetas ShippingEasy")
        return planilha.get_worksheet(0)
    except Exception as e:
        print(f"❌ Erro final ao conectar ao Google Sheets: {e}")
        return None


# 📌 ATALHOS DE COMPATIBILIDADE PARA OUTROS SCRIPTS
def conectar_planilha():
    return conectar_planilha_ativa()


def conectar_sheets():
    return conectar_planilha_ativa()


def buscar_link_tarefa(num_pedido):
    """
    Busca no Bitrix a tarefa cujo TÍTULO contenha o ID do pedido
    e retorna a URL com o ID REAL da tarefa interna do Bitrix.
    """
    # Busca a URL tanto do st.secrets quanto do os.getenv
    webhook_url = os.getenv("BITRIX_WEBHOOK_URL")
    try:
        import streamlit as st
        if "BITRIX_WEBHOOK_URL" in st.secrets:
            webhook_url = st.secrets["BITRIX_WEBHOOK_URL"]
    except Exception:
        pass

    if not num_pedido or not webhook_url:
        return ""

    id_str = str(num_pedido).strip()

    try:
        endpoint = webhook_url.rstrip("/") + "/tasks.task.list.json"
        payload = {"filter": {"%TITLE": id_str}, "select": ["ID", "TITLE"]}
        resp = requests.post(endpoint, json=payload, timeout=10)
        if resp.status_code == 200:
            dados = resp.json()
            tarefas = dados.get("result", {}).get("tasks", [])

            for task in tarefas:
                titulo = str(task.get("title", "")).upper()
                task_id_real = task.get("id")

                if id_str in titulo and task_id_real:
                    return f"https://despachante55.bitrix24.com.br/company/personal/user/0/tasks/task/view/{task_id_real}/"
    except Exception as e:
        print(f"⚠️ Erro ao buscar tarefa no Bitrix para o ID {id_str}: {e}")

    return ""


def ler_envios_sheets():
    sheet = conectar_planilha_ativa()
    if not sheet:
        return pd.DataFrame()
    try:
        valores = sheet.get_all_values()
        if not valores or len(valores) <= 1:
            return pd.DataFrame()

        cabecalho = [str(col).strip() for col in valores[0]]
        linhas = valores[1:]
        linhas_validas = [
            l for l in linhas if any(str(field).strip() for field in l)
        ]

        return pd.DataFrame(linhas_validas, columns=cabecalho)
    except Exception as e:
        print(f"❌ Erro ao ler planilha: {e}")
        return pd.DataFrame()


def registrar_envio_sheets(dados):
    client = conectar_client()
    if not client:
        return False

    hoje = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Se uma data de criação específica for informada (ex: etiqueta antiga), usa ela.
    data_criacao_etiqueta = dados.get("data_criacao") or hoje

    num_p = str(dados.get("num_pedido", ""))
    link_tarefa = dados.get("tarefa") or buscar_link_tarefa(num_p)

    try:
        # 1. Registra na Planilha Pública (Dashboard) -> USA A DATA DE CRIAÇÃO DA ETIQUETA
        sheet_ativa = client.open("Rastreio de Etiquetas ShippingEasy").get_worksheet(0)
        linha_publica = [
            data_criacao_etiqueta,
            num_p,
            link_tarefa,
            str(dados.get("nome", "")),
            str(dados.get("tracking_code", "")),
            str(dados.get("tipo_envio", "")),
            "AGUARDANDO ATUALIZAR STATUS",
            hoje,
        ]
        sheet_ativa.append_row(linha_publica)

        # 2. Registra na Planilha Privada (Auditoria + Custos)
        try:
            sheet_privada = client.open_by_key(ID_PLANILHA_AUDITORIA).get_worksheet(0)
            linha_privada = [
                hoje,
                num_p,
                str(dados.get("nome", "")),
                str(dados.get("tracking_code", "")),
                str(dados.get("tipo_envio", "")),
                dados.get("custo", 0.01),
            ]
            sheet_privada.append_row(linha_privada)
        except Exception as err_priv:
            print(f"⚠️ Aviso: Não foi possível gravar na planilha privada: {err_priv}")

        return True
    except Exception as e:
        print(f"❌ Erro ao registrar envio: {e}")
        return False


def registrar_reembolso_sheets(dados):
    """Lança o reembolso só na planilha de auditoria (custo negativo)."""
    client = conectar_client()
    if not client:
        return False
    try:
        client.open_by_key(ID_PLANILHA_AUDITORIA).get_worksheet(0).append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            str(dados.get("num_pedido", "")),
            str(dados.get("nome", "")),
            str(dados.get("tracking_code", "")),
            str(dados.get("tipo_envio", "")),
            dados.get("custo", 0),
        ])
        return True
    except Exception as e:
        print(f"❌ Erro ao registrar reembolso na auditoria: {e}")
        return False


def deletar_envios_sheets(rastreios):
    """Apaga as linhas cujo rastreio (só dígitos, link ou código) está em `rastreios`.

    O rastreio identifica a linha: o nº do pedido se repete (IDA + RETORNO etc.).
    Devolve a lista de rastreios que NÃO foram encontrados (vazia = tudo apagado).
    """
    alvos = {re.sub(r"\D", "", str(r)) for r in rastreios} - {""}
    sheet = conectar_planilha_ativa()
    if not sheet:
        return sorted(alvos)
    try:
        valores = sheet.get_all_values()
        cabecalho = [str(c).upper() for c in valores[0]] if valores else []
        idx = next(
            (i for i, c in enumerate(cabecalho) if "RASTREIO" in c or "TRACKING" in c), None
        )
        if idx is None:
            print("❌ Coluna de rastreio não encontrada na planilha.")
            return sorted(alvos)

        linhas = [
            n
            for n, linha in enumerate(valores[1:], start=2)
            if len(linha) > idx and re.sub(r"\D", "", linha[idx]) in alvos
        ]
        # De baixo para cima: apagar uma linha não muda o número das que estão acima
        for n in sorted(linhas, reverse=True):
            sheet.delete_rows(n)

        achados = {re.sub(r"\D", "", valores[n - 1][idx]) for n in linhas}
        return sorted(alvos - achados)
    except Exception as e:
        print(f"❌ Erro ao deletar registros: {e}")
        return sorted(alvos)

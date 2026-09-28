import os
import re
import time
from datetime import datetime
import requests
from sheets import conectar_planilha_ativa as conectar_planilha

# ==============================================================================
# CONFIGURAÇÕES DE API (Lendo do .env ou Secrets)
# ==============================================================================
def obter_secret(chave):
    try:
        import streamlit as st
        if hasattr(st, "secrets") and chave in st.secrets:
            return st.secrets[chave]
    except Exception:
        pass
    return os.getenv(chave, "")

WEBHOOK_URL = obter_secret("BITRIX_WEBHOOK_URL")

WHATCRM_URL = "https://api.whatcrm.online/v3/instance5e4033fa60963d7ce8e7e7fa4fd4adea/sendMessage"
WHATCRM_HEADERS = {
    "Content-Type": "application/json",
    "X-Whappim-Token": obter_secret("WHATCRM_TOKEN"),
    "Origin": "https://web.whatcrm.online",
    "Referer": "https://web.whatcrm.online/"
}

PALAVRAS_ERRO = [
    "RETURN", "RETURNED", "DEVOLVIDO", "REFUSED", "FAILURE",
    "UNDELIVERED", "UNAVAILABLE", "INCORRECT ADDRESS", "WRONG ADDRESS",
    "NO SUCH NUMBER", "ALERT", "EXCEPTION", "FORWARDED", "HELD",
    "NOTICE LEFT", "ATTEMPTED", "LOST", "MISSING", "DELAYED"
]

def obter_shippo_key():
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "SHIPPO_LIVE_KEY" in st.secrets:
            return st.secrets["SHIPPO_LIVE_KEY"]
    except Exception:
        pass
    return os.getenv("SHIPPO_LIVE_KEY", "")

def limpar_telefone(telefone):
    if not telefone: return ""
    numeros = re.sub(r'\D', '', str(telefone))
    if not numeros: return ""
    
    # Se já é número dos EUA completo (1 + 10 dígitos = 11 dígitos começando com 1)
    if len(numeros) == 11 and numeros.startswith("1"):
        return numeros

    # Se já é número do Brasil com DDI (55 + 10 ou 11 dígitos)
    if len(numeros) in [12, 13] and numeros.startswith("55"):
        return numeros

    # Se for número do Brasil sem DDI (10 ou 11 dígitos sem começar por 1)
    if len(numeros) in [10, 11]:
        return "55" + numeros

    return numeros

# ==============================================================================
# INTEGRACÃO 1: BUSCAR APENAS O TELEFONE NO BITRIX24
# ==============================================================================
def obter_telefone_bitrix(deal_id):
    """Consulta o Bitrix usando o ID do Negócio para retornar o WhatsApp do cliente."""
    if not deal_id:
        return None

    if not WEBHOOK_URL or not str(WEBHOOK_URL).startswith("http"):
        print("   ⚠️ BITRIX_WEBHOOK_URL não configurada ou inválida nas Secrets!", flush=True)
        return None

    try:
        base_url = WEBHOOK_URL.rstrip('/')
        url_deal = f"{base_url}/crm.deal.get.json"
        res_deal = requests.get(url_deal, params={"id": deal_id}, timeout=10)

        if res_deal.status_code != 200:
            print(f"   ⚠️ Bitrix retornou HTTP {res_deal.status_code} ao buscar Negócio #{deal_id}", flush=True)
            return None

        data_deal = res_deal.json()
        contact_id = data_deal.get("result", {}).get("CONTACT_ID")

        if not contact_id:
            print(f"   ⚠️ Negócio #{deal_id} sem Contato vinculado.", flush=True)
            return None

        url_contact = f"{base_url}/crm.contact.get.json"
        res_contact = requests.get(url_contact, params={"id": contact_id}, timeout=10)

        if res_contact.status_code != 200:
            print(f"   ⚠️ Bitrix retornou HTTP {res_contact.status_code} ao buscar Contato #{contact_id}", flush=True)
            return None

        data_contact = res_contact.json()
        phones = data_contact.get("result", {}).get("PHONE", [])

        if phones and len(phones) > 0:
            return limpar_telefone(phones[0].get("VALUE"))

        print(f"   ⚠️ Contato #{contact_id} sem telefone cadastrado.", flush=True)
        return None
    except Exception as e:
        print(f"   ⚠️ Erro ao consultar telefone no Bitrix: {e}", flush=True)
        return None

# ==============================================================================
# INTEGRACÃO 2: CRIAR TAREFA DE ALERTA SE HOUVER ERRO/SLA
# ==============================================================================
def criar_tarefa_bitrix(deal_id, titulo, descricao, responsavel_id=71104):
    """Cria uma tarefa urgente no Bitrix24 apenas quando algo dá errado."""
    if not deal_id or not WEBHOOK_URL or not str(WEBHOOK_URL).startswith("http"):
        return

    base_url = WEBHOOK_URL.rstrip('/')
    url = f"{base_url}/tasks.task.add.json"
    prazo_hoje = datetime.now().strftime("%Y-%m-%d 18:00:00")

    payload = {
        "fields": {
            "TITLE": titulo,
            "DESCRIPTION": descricao,
            "RESPONSIBLE_ID": responsavel_id,
            "PRIORITY": 2,  
            "DEADLINE": prazo_hoje,
            "UF_CRM_TASK": [f"D_{deal_id}"]
        }
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"   🚨 Tarefa de Alerta gerada no Bitrix24: '{titulo}'", flush=True)
        else:
            print(f"   ⚠️ Falha ao criar tarefa no Bitrix (HTTP {res.status_code})", flush=True)
    except Exception as e:
        print(f"   ⚠️ Erro ao gerar tarefa no Bitrix: {e}", flush=True)

# ==============================================================================
# DISPARO DIRETO DO WHATSAPP (WHATCRM)
# ==============================================================================
def enviar_whatsapp_direto(telefone, mensagem):
    """Dispara a mensagem diretamente via WhatCRM."""
    if not telefone: return

    payload = {
        "chatId": f"{telefone}@c.us",
        "body": mensagem
    }

    try:
        res = requests.post(WHATCRM_URL, json=payload, headers=WHATCRM_HEADERS, timeout=10)
        if res.status_code in [200, 201]:
            print(f"   💬 WhatsApp enviado via WhatCRM para {telefone}!", flush=True)
        else:
            print(f"   ⚠️ Falha WhatCRM ({res.status_code}): {res.text}", flush=True)
    except Exception as e:
        print(f"   ⚠️ Erro de conexão com WhatCRM: {e}", flush=True)

# ==============================================================================
# ENGINE DE REGRAS E PREDICADOS
# ==============================================================================
def processar_regras_automacao(deal_id, novo_status, tipo_envio="IDA", data_evento_str=None):
    status_upper = str(novo_status).upper()
    tipo_envio = str(tipo_envio).upper().strip()

    # REGRA 1: EXCEÇÕES E FALHAS USPS -> Criar Tarefa no Bitrix
    if any(palavra in status_upper for palavra in PALAVRAS_ERRO):
        titulo = f"⚠️ EXCEÇÃO USPS: Negócio #{deal_id} ({tipo_envio})"
        descricao = f"O rastreio do Negócio #{deal_id} apresentou uma falha:\nStatus: {novo_status}"
        criar_tarefa_bitrix(deal_id, titulo, descricao)
        return

    # REGRA 2: DISPARO DE WHATSAPP DIRETO
    if "DELIVERED" in status_upper or "ACCEPTED" in status_upper or "PICKED UP" in status_upper:
        telefone_cliente = obter_telefone_bitrix(deal_id)

        if "DELIVERED" in status_upper:
            msg = """Olá xxxx, boa tarde. Tudo bom?

            Verifiquei pelo link da USPS que o envelope chegou dia de hoje. 🎉

            Você confirma esse recebimento?"""
            enviar_whatsapp_direto(telefone_cliente, msg)
            
        elif "ACCEPTED" in status_upper or "PICKED UP" in status_upper:
            msg = "Olá! Passando para avisar que o seu envelope foi coletado pela USPS e já está a caminho! 🚚💨 Qualquer novidade, volto a te avisar."
            enviar_whatsapp_direto(telefone_cliente, msg)

    # REGRA 3: MONITORAMENTO DE SLA DE ENTREGA -> Criar Tarefa se estourar
    if data_evento_str:
        try:
            dt_evento = datetime.strptime(data_evento_str, "%Y-%m-%d %H:%M")
            dias_decorridos = (datetime.now() - dt_evento).days

            if tipo_envio == "IDA" and "DELIVERED" not in status_upper and dias_decorridos > 7:
                criar_tarefa_bitrix(deal_id, f"⚠️ ALERTA SLA (+7 dias): Envio IDA - Negócio #{deal_id}", f"Envio em trânsito há {dias_decorridos} dias.")

            elif tipo_envio in ["RETORNO", "CONSULADO"] and "DELIVERED" not in status_upper and dias_decorridos > 30:
                criar_tarefa_bitrix(deal_id, f"⚠️ ALERTA SLA (+30 dias): Envio {tipo_envio} - Negócio #{deal_id}", f"Envio ultrapassou 30 dias.")

            elif tipo_envio == "PASSAPORTE" and "DELIVERED" not in status_upper and dias_decorridos > 70:
                criar_tarefa_bitrix(deal_id, f"⚠️ ALERTA SLA (+70 dias): Passaporte - Negócio #{deal_id}", f"Prazo de 70 dias expirado.")
        except Exception:
            pass

# ==============================================================================
# CONSULTAS SHIPPO E PLANILHA
# ==============================================================================
def extrair_apenas_numeros_rastreio(texto):
    if not texto: return ""
    numeros = re.findall(r'\d{15,30}', str(texto))
    return numeros[0] if numeros else str(texto).strip()

def consultar_shippo(tracking_code):
    shippo_key = obter_shippo_key()
    if not shippo_key: return None, None

    url = "https://api.goshippo.com/tracks/"
    headers = {"Authorization": f"ShippoToken {shippo_key}", "Content-Type": "application/json"}
    payload = {"carrier": "usps", "tracking_number": tracking_code}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            data = response.json() or {}
            tracking_status = data.get("tracking_status") or {}
            status_macro = str(tracking_status.get("status", "")).replace("_", " ").title()
            detalhe = tracking_status.get("status_details", "")
            data_iso = tracking_status.get("status_date", "")

            if data_iso:
                try:
                    dt_obj = datetime.fromisoformat(str(data_iso).replace("Z", "+00:00"))
                    data_evento = dt_obj.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    data_evento = str(data_iso)
            else:
                data_evento = datetime.now().strftime("%Y-%m-%d %H:%M")

            status_final = f"{status_macro} - {detalhe}" if detalhe else status_macro
            return status_final if status_macro else "Em Trânsito", data_evento
        return None, None
    except Exception:
        return None, None

def rodar_monitoramento():
    print("\n🚀 INICIANDO MONITORAMENTO AUTOMÁTICO (SHIPPO + WHATCRM)...", flush=True)
    sheet = conectar_planilha()
    if not sheet: return

    try:
        valores = sheet.get_all_values()
        if not valores or len(valores) <= 1: return
        cabecalho = [str(c).upper().strip() for c in valores[0]]
    except Exception as e:
        print(f"❌ Erro ao ler planilha: {e}", flush=True)
        return

    idx_status = next((i + 1 for i, c in enumerate(cabecalho) if "STATUS" in c), 7)
    idx_atualizacao = next((i + 1 for i, c in enumerate(cabecalho) if "ATUALIZA" in c), 8)
    idx_rastreio = next((i + 1 for i, c in enumerate(cabecalho) if "RASTREIO" in c), 5)
    idx_nome = next((i + 1 for i, c in enumerate(cabecalho) if "NOME" in c), 4)
    idx_deal = next((i + 1 for i, c in enumerate(cabecalho) if "ID" in c or "DEAL" in c or "NEGOCIO" in c), None)
    idx_tipo = next((i + 1 for i, c in enumerate(cabecalho) if "TIPO" in c or "ENVIO" in c), None)

    linhas = valores[1:]
    mudancas = 0
    for index, row in enumerate(linhas, start=2):
        if len(row) < idx_rastreio: continue
        
        rastreio = str(row[idx_rastreio - 1])
        status_atual = str(row[idx_status - 1]).strip() if len(row) >= idx_status else ""
        nome = str(row[idx_nome - 1]) if len(row) >= idx_nome else "Cliente"
        deal_id = str(row[idx_deal - 1]).strip() if idx_deal and len(row) >= idx_deal else ""
        tipo_envio = str(row[idx_tipo - 1]).strip() if idx_tipo and len(row) >= idx_tipo else "IDA"

        tracking_code = extrair_apenas_numeros_rastreio(rastreio)
        if not tracking_code: continue

        print(f"🔎 Checando linha {index} ({nome})...", flush=True)
        novo_status, data_evento = consultar_shippo(tracking_code)

        if novo_status and novo_status.upper() != status_atual.upper():
            print(f"   ✨ Mudança Detectada: '{status_atual}' ➔ '{novo_status}'", flush=True)
            
            # 1. Atualiza Planilha
            sheet.update_cell(index, idx_status, novo_status)
            sheet.update_cell(index, idx_atualizacao, data_evento)
            mudancas += 1
            
            # 2. Executa Disparo de WhatsApp e/ou Alertas de Erro
            if deal_id:
                processar_regras_automacao(deal_id, novo_status, tipo_envio, data_evento)

        time.sleep(0.2)

    print(f"✅ Monitoramento concluído! {mudancas} etiquetas atualizadas.", flush=True)
   
if __name__ == "__main__":
    # EXECUÇÃO DE PRODUÇÃO
    rodar_monitoramento()

    # DEAL_ID_TESTE = "86994"
    # SEU_TELEFONE = "5583991573227"  # O teu número de teste
    #
    # print(
    #     f"\n🧪 INICIANDO TESTE CONTROLADO DA NOVA VERSÃO (NEGÓCIO"
    #     f" #{DEAL_ID_TESTE})...\n"
    # )
    #
    # # 1. Testar se o Python consegue ir ao Bitrix capturar o telefone
    # print("1️⃣ A buscar o telefone do contacto no Bitrix24...")
    # tel_bitrix = obter_telefone_bitrix(DEAL_ID_TESTE)
    # print(f"   📞 Telefone retornado pela API do Bitrix: {tel_bitrix}")
    #
    # # Se a API não retornar telefone (ou se quiseres garantir), usa o SEU_TELEFONE
    # tel_destino = tel_bitrix if tel_bitrix else SEU_TELEFONE
    # print(f"   🎯 O WhatsApp de teste será enviado para: {tel_destino}\n")
    #
    # # 2. Testar o disparo direto via WhatCRM
    # print("2️⃣ A disparar mensagem de teste de postagem via WhatCRM...")
    # mensagem_teste = (
    #     "🧪 TESTE DA NOVA VERSÃO: O teu envelope foi coletado pela USPS e já"
    #     " está a caminho! 🚚💨 (Disparo 100% Python)"
    # )
    #
    # enviar_whatsapp_direto(tel_destino, mensagem_teste)
    #
    # print(
    #     "\n🏁 Teste concluído! Dá uma olhada no teu WhatsApp para confirmar o"
    #     " recebimento!"
    # )
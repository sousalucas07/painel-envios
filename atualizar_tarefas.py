import os
import time
import requests
from sheets import conectar_planilha_ativa



def obter_bitrix_url():
    url = ""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if "BITRIX_WEBHOOK_URL" in st.secrets:
                url = st.secrets["BITRIX_WEBHOOK_URL"]
            elif "bitrix_webhook_url" in st.secrets:
                url = st.secrets["bitrix_webhook_url"]
    except Exception:
        pass

    if not url:
        url = os.getenv("BITRIX_WEBHOOK_URL", "")

    return str(url).replace("\n", "").replace("\r", "").replace(" ", "").strip('"').strip("'")

def sincronizar_links_tarefas():
    print("\n🔄 Conectando à planilha para sincronizar links de tarefas...", flush=True)
    sheet = conectar_planilha_ativa()
    if not sheet:
        print("❌ Não foi possível conectar à planilha.", flush=True)
        return

    webhook_url = obter_bitrix_url()
    if not webhook_url:
        print("❌ ERRO CRÍTICO: 'BITRIX_WEBHOOK_URL' não foi encontrada nos Secrets da Nuvem nem no .env!", flush=True)
        return
    else:
        # Exibe o tamanho e as pontas da URL para validar o texto exato
        inicio = webhook_url[:35]
        fim = webhook_url[-8:]
        print(f"✅ Webhook do Bitrix localizado! Tamanho: {len(webhook_url)} chars | Formato: '{inicio}...{fim}'", flush=True)

    try:
        valores = sheet.get_all_values()
        if not valores or len(valores) <= 1: return
        cabecalho = [str(c).upper().strip() for c in valores[0]]
    except Exception as e:
        print(f"❌ Erro ao ler planilha: {e}", flush=True)
        return

    idx_pedido = next((i + 1 for i, c in enumerate(cabecalho) if "PEDIDO" in c or "ID" in c or "BITRIX" in c), 2)
    idx_tarefa = next((i + 1 for i, c in enumerate(cabecalho) if "TAREFA" in c), 3)

    linhas = valores[1:]
    mudancas = 0

    for index, row in enumerate(linhas, start=2):
        num_pedido = str(row[idx_pedido - 1]).strip() if len(row) >= idx_pedido else ""
        link_atual = str(row[idx_tarefa - 1]).strip() if len(row) >= idx_tarefa else ""
        
        if not num_pedido or "bitrix24" in link_atual: 
            continue

        try:
            endpoint = webhook_url.rstrip("/") + "/tasks.task.list.json"
            
            # Envia via Query Parameters (formato nativo e mais aceito pela API de Webhook do Bitrix)
            params = {
                "filter[%TITLE%]": num_pedido,
                "select[0]": "ID",
                "select[1]": "TITLE"
            }
            
            resp = requests.get(endpoint, params=params, timeout=10)
            
            if resp.status_code == 200:
                tarefas = resp.json().get("result", {}).get("tasks", [])
                link_encontrado = ""
                
                for task in tarefas:
                    titulo = str(task.get("title", "")).upper()
                    task_id_real = task.get("id")
                    
                    if num_pedido in titulo and task_id_real:
                        link_encontrado = f"https://despachante55.bitrix24.com.br/company/personal/user/0/tasks/task/view/{task_id_real}/"
                        break

                if link_encontrado:
                    sheet.update_cell(index, idx_tarefa, link_encontrado)
                    print(f"✅ Tarefa {num_pedido} sincronizada com ID real {task_id_real}!", flush=True)
                    mudancas += 1
                    time.sleep(0.3)
                else:
                    print(f"⚠️ Nenhuma tarefa encontrada no Bitrix para o ID {num_pedido}", flush=True)
            else:
                # Imprime a resposta detalhada do Bitrix para sabermos exatamente o motivo do 401
                print(f"❌ Erro HTTP {resp.status_code} no Bitrix ao buscar {num_pedido}. Resposta: {resp.text}", flush=True)
        except Exception as e:
            print(f"⚠️ Erro ao consultar Bitrix para {num_pedido}: {e}", flush=True)

    if mudancas == 0:
        print("⚡ Nenhuma tarefa nova precisou ser sincronizada.", flush=True)
    else:
        print(f"✅ Sincronização concluída! {mudancas} links atualizados.", flush=True)

if __name__ == "__main__":
    sincronizar_links_tarefas()
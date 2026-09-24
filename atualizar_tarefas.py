import os
import time
import requests
from sheets import conectar_planilha_ativa

def obter_bitrix_url():
    try:
        import streamlit as st
        if "BITRIX_WEBHOOK_URL" in st.secrets:
            return st.secrets["BITRIX_WEBHOOK_URL"]
    except Exception:
        pass
    return os.getenv("BITRIX_WEBHOOK_URL", "")

def sincronizar_links_tarefas():
    print("\n🔄 Conectando à planilha para sincronizar links de tarefas...", flush=True)
    sheet = conectar_planilha_ativa()
    if not sheet:
        print("❌ Não foi possível conectar à planilha.", flush=True)
        return

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
    webhook_url = obter_bitrix_url()

    headers_browser = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    for index, row in enumerate(linhas, start=2):
        num_pedido = str(row[idx_pedido - 1]).strip() if len(row) >= idx_pedido else ""
        link_atual = str(row[idx_tarefa - 1]).strip() if len(row) >= idx_tarefa else ""
        
        # 📌 LOG DE DIAGNÓSTICO: Mostra no log exatamente o que a Nuvem leu na célula
        print(f"🔍 Linha {index} ({num_pedido}): Link lido = '{link_atual}'", flush=True)

        # Pula se a célula já estiver preenchida com um link do Bitrix
        if not num_pedido or "bitrix24" in link_atual: 
            continue

        if webhook_url:
            try:
                endpoint = webhook_url.rstrip("/") + "/tasks.task.list.json"
                payload = {"filter": {"%TITLE": num_pedido}, "select": ["ID", "TITLE"]}
                resp = requests.post(endpoint, json=payload, headers=headers_browser, timeout=10)
                
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
            except Exception as e:
                print(f"⚠️ Erro ao consultar Bitrix para {num_pedido}: {e}", flush=True)

    if mudancas == 0:
        print("⚡ Nenhuma tarefa nova precisou ser sincronizada.", flush=True)
    else:
        print(f"✅ Sincronização concluída! {mudancas} links atualizados.", flush=True)

if __name__ == "__main__":
    sincronizar_links_tarefas()
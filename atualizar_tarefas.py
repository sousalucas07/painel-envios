import time
from sheets import conectar_sheets, buscar_link_tarefa

def sincronizar_links_tarefas():
    print("\n🔍 Conectando à planilha para sincronizar e validar links de tarefas...", flush=True)
    sheet = conectar_sheets()
    
    if not sheet:
        print("❌ Não foi possível conectar à planilha.")
        return

    # Pega todos os registros e o cabeçalho
    registros = sheet.get_all_records()
    cabecalho = sheet.row_values(1)

    # Identifica dinamicamente o número da coluna 'TAREFA' e 'ID BITRIX'
    col_tarefa_idx = None
    col_id_idx = None

    for idx, col in enumerate(cabecalho, start=1):
        c_lower = col.strip().lower()
        if "tarefa" in c_lower:
            col_tarefa_idx = idx
        elif "id" in c_lower or "pedido" in c_lower:
            col_id_idx = idx

    if not col_tarefa_idx or not col_id_idx:
        print(f"❌ Não encontrei as colunas necessárias no cabeçalho: Tarefa (Col {col_tarefa_idx}), ID (Col {col_id_idx})")
        return

    print(f"📋 Coluna ID: {col_id_idx} | Coluna TAREFA: {col_tarefa_idx}")
    print(f"Total de {len(registros)} linhas encontradas. Iniciando verificação completa com o Bitrix...\n")

    for index, row in enumerate(registros, start=2): # start=2 pois a linha 1 é o cabeçalho
        id_pedido = ""
        link_tarefa_atual = ""

        for k, v in row.items():
            k_lower = str(k).strip().lower()
            if "id" in k_lower or "pedido" in k_lower:
                id_pedido = str(v).strip()
            elif "tarefa" in k_lower:
                link_tarefa_atual = str(v).strip()

        if not id_pedido:
            print(f"⏩ Linha {index}: Sem ID do pedido. Pulando.")
            continue

        print(f"🔎 Linha {index} (ID: {id_pedido}): Verificando link no Bitrix...")
        link_encontrado = buscar_link_tarefa(id_pedido)

        if link_encontrado:
            # COMPARAÇÃO: Atualiza a planilha APENAS se o link mudou ou se estava em branco
            if link_encontrado != link_tarefa_atual:
                sheet.update_cell(index, col_tarefa_idx, link_encontrado)
                print(f"   🔄 Link alterado/atualizado na planilha: {link_encontrado}")
            else:
                print(f"   ✅ Link já está 100% atualizado e correto.")
        else:
            print(f"   ⚠️ Nenhuma tarefa encontrada no Bitrix para o ID {id_pedido}")

        time.sleep(1) # Pausa para respeitar limite de requisições da API

    print("\n🎉 Varredura e sincronização concluídas com sucesso!\n")

if __name__ == "__main__":
    sincronizar_links_tarefas()
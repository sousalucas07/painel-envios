import os
import re
import time
from datetime import datetime
import requests
from sheets import conectar_planilha_ativa as conectar_planilha

SHIPPO_LIVE_KEY = os.getenv("SHIPPO_LIVE_KEY", "")

def extrair_apenas_numeros_rastreio(texto):
    if not texto: return ""
    numeros = re.findall(r'\d{15,30}', str(texto))
    return numeros[0] if numeros else str(texto).strip()

def consultar_shippo(tracking_code):
    url = "https://api.goshippo.com/tracks/"
    headers = {
        "Authorization": f"ShippoToken {SHIPPO_LIVE_KEY}",
        "Content-Type": "application/json"
    }
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
    except Exception as e:
        print(f"⚠️ Exceção na API Shippo: {e}")
        return None, None

def rodar_monitoramento():
    print("\n🚀 INICIANDO MONITORAMENTO VIA SHIPPO API...", flush=True)
    sheet = conectar_planilha()
    if not sheet: return

    try:
        valores = sheet.get_all_values()
        if not valores or len(valores) <= 1: return
        cabecalho = [str(c).upper().strip() for c in valores[0]]
    except Exception as e:
        print(f"❌ Erro ao ler planilha: {e}")
        return

    idx_status = next((i + 1 for i, c in enumerate(cabecalho) if "STATUS" in c), 8)
    idx_atualizacao = next((i + 1 for i, c in enumerate(cabecalho) if "ATUALIZA" in c), 9)
    idx_rastreio = next((i + 1 for i, c in enumerate(cabecalho) if "RASTREIO" in c), 6)
    idx_nome = next((i + 1 for i, c in enumerate(cabecalho) if "NOME" in c), 4)

    linhas = valores[1:]
    for index, row in enumerate(linhas, start=2):
        if len(row) < idx_rastreio: continue
        
        rastreio = str(row[idx_rastreio - 1])
        status_atual = str(row[idx_status - 1]).strip() if len(row) >= idx_status else ""
        nome = str(row[idx_nome - 1]) if len(row) >= idx_nome else "Cliente"

        tracking_code = extrair_apenas_numeros_rastreio(rastreio)
        if not tracking_code: continue

        print(f"🔎 Checando linha {index} ({nome}) | Código: {tracking_code}...", flush=True)
        novo_status, data_evento = consultar_shippo(tracking_code)

        if novo_status and novo_status.upper() != status_atual.upper():
            print(f"   ✨ Mudança Detectada: '{status_atual}' ➔ '{novo_status}'", flush=True)
            sheet.update_cell(index, idx_status, novo_status)
            sheet.update_cell(index, idx_atualizacao, data_evento)
            
        time.sleep(0.2)

    print("✅ Checagem concluída com sucesso!\n", flush=True)

if __name__ == "__main__":
    rodar_monitoramento()
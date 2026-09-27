import requests

URL_EXATA = "https://api.whatcrm.online/v3/instance5e4033fa60963d7ce8e7e7fa4fd4adea/sendMessage"
TELEFONE_TESTE = "5583991573227"  # DDI + DDD + Seu número
MENSAGEM = "🧪 TESTE DA VITÓRIA: Disparo 100% Python via WhatCRM sem Bitrix!"

headers = {
    "Content-Type": "application/json",
    "X-Whappim-Token": "61616049e9939ac708653cd7d55cdba4",
    "Origin": "https://web.whatcrm.online",
    "Referer": "https://web.whatcrm.online/"
}

payloads = [
    {"chatId": f"{TELEFONE_TESTE}@c.us", "message": MENSAGEM},
    {"phone": TELEFONE_TESTE, "message": MENSAGEM},
    {"chatId": f"{TELEFONE_TESTE}@c.us", "body": MENSAGEM},
    {"phone": TELEFONE_TESTE, "text": MENSAGEM}
]

for idx, payload in enumerate(payloads, start=1):
    print(f"\n🚀 Testando Envio #{idx} com o Token de Autenticação...")
    try:
        res = requests.post(URL_EXATA, json=payload, headers=headers, timeout=10)
        print(f"   Status Code: {res.status_code}")
        print(f"   Resposta: {res.text}")
        if res.status_code in [200, 201]:
            print("\n🎉 DÁ-LHE! MENSAGEM ENVIADA COM SUCESSO NO WHATSAPP!")
            print("CRM DESMAMADO COM SUCESSO! 🚀")
            break
    except Exception as e:
        print(f"   ❌ Erro: {e}")
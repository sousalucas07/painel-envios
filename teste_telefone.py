"""Checa a normalização de telefone do WhatsApp (não envia nada). Rode: python teste_telefone.py"""
from tracker import limpar_telefone

CASOS = {
    "(206) 377-9682": "12063779682",          # EUA sem o 1 (era enviado como 55 20...)
    "+1 206 377 9682": "12063779682",         # EUA com DDI
    "12063779682": "12063779682",
    "(212) 555-1234": "12125551234",          # EUA com código de área igual a DDD (21)
    "(11) 98765-4321": "5511987654321",       # SP sem 55 (era enviado como EUA)
    "(19) 99123-4567": "5519991234567",
    "(83) 99157-3227": "5583991573227",       # celular BR sem 55
    "+55 83 99157-3227": "5583991573227",     # BR com DDI
    "558391573227": "558391573227",           # BR com DDI, celular antigo sem o 9
    "": "",
    None: "",
}

for entrada, esperado in CASOS.items():
    obtido = limpar_telefone(entrada)
    assert obtido == esperado, f"{entrada!r}: esperado {esperado}, veio {obtido}"

print(f"OK: {len(CASOS)} casos")

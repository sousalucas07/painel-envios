"""Auto-teste offline da regra de etiqueta parada: python teste_validade.py"""
from datetime import date

import tracker

PRE = "Pre Transit - SHIPPING LABEL CREATED"
f = lambda compra, hoje, status=PRE, tipo="IDA": tracker.fase_validade(status, compra, tipo, date.fromisoformat(hoje))

assert f("2026-11-01 10:00", "2026-11-30") is None          # 29 dias
assert f("2026-11-01 10:00", "2026-12-01") == "aviso"       # dia 30
assert f("2026-11-01 10:00", "2027-01-26") == "aviso"       # dia 86: a tarefa não duplica (checa no Bitrix)
assert f("2026-11-01 10:00", "2027-01-27") == "reembolso"   # dia 87: 3 dias antes do prazo da Shippo
for tipo in ("RETORNO", "Cli - Con", "Cli - Con / Con - Cli", "D55 - DPT", "IDA + RETORNO"):
    assert f("2026-11-01 10:00", "2026-12-01", tipo=tipo) == "aviso", tipo
# Consulado -> Cliente: sem aviso de 30 dias (já tem o alerta de 70), mas reembolsa no dia 87
assert f("2026-11-01 10:00", "2026-12-01", tipo="Con - Cli") is None
assert f("2026-11-01 10:00", "2027-01-29", tipo="Con - Cli") == "reembolso"
for status in ("Transit - ARRIVE USPS FACILITY", "Delivered - DELIVERED", "AGUARDANDO ATUALIZAR STATUS"):
    assert f("2026-11-01 10:00", "2026-12-01", status) is None
    assert f("2026-11-01 10:00", "2027-01-29", status) is None
assert f("", "2027-01-29") is None
# Etiquetas que já tinham 30 dias quando a regra entrou (24/11/2026): sem aviso, só o reembolso
assert f("2026-10-24 10:00", "2026-11-24") is None          # dia 30 caiu em 23/11
assert f("2026-10-25 10:00", "2026-11-24") == "aviso"
assert f("2026-10-19 10:00", "2027-01-16") == "reembolso"
# Aviso de cancelamento ao cliente: só RETORNO e Cli - Con (é o cliente quem posta)
m = tracker.mensagem_cancelamento
assert "Olá, Maria!" in m("RETORNO", "MARIA SILVA", "123", "9400111122223333") and "final 3333" in m("RETORNO", "MARIA SILVA", "123", "9400111122223333")
assert "consulado" in m("Cli - Con", "", "123", "9400111122223333")
assert "consulado" in m("Cli - Con / Con - Cli", "Ana", "123", "9400111122223333")
for tipo in ("IDA", "IDA + RETORNO", "Con - Cli", "D55 - DPT"):
    assert m(tipo, "Ana", "123", "9400111122223333") is None, tipo
# Ida do pedido: só avisa o cliente se a ida saiu (ou se o pedido não tem ida na Shippo)
tx = lambda ref, rastreio, status="SUCCESS": {"metadata": ref, "tracking_status": rastreio, "status": status}
assert tracker.ida_postada("100", [tx("100 IDA", "PRE_TRANSIT"), tx("100 IDA", "DELIVERED"), tx("100 RETORNO", "PRE_TRANSIT")]) is True
assert tracker.ida_postada("100", [tx("100 IDA", "PRE_TRANSIT"), tx("100 IDA", "PRE_TRANSIT", "REFUNDED")]) is False
assert tracker.ida_postada("100", [tx("100 Cli - Con", "TRANSIT"), tx("1000 IDA", "TRANSIT"), tx("100 IDA", "UNKNOWN", "ERROR")]) is None
print("ok")

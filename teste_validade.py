"""Auto-teste offline da regra de etiqueta parada: python teste_validade.py"""
from datetime import date

import tracker

PRE = "Pre Transit - SHIPPING LABEL CREATED"
f = lambda compra, hoje, status=PRE, tipo="IDA": tracker.fase_validade(status, compra, tipo, date.fromisoformat(hoje))

assert f("2026-11-01 10:00", "2026-11-30") is None          # 29 dias
assert f("2026-11-01 10:00", "2026-12-01") == "aviso"       # dia 30
assert f("2026-11-01 10:00", "2027-01-28") == "aviso"       # dia 88: a tarefa não duplica (checa no Bitrix)
assert f("2026-11-01 10:00", "2027-01-29") == "reembolso"   # dia 89: véspera do prazo da Shippo
for tipo in ("RETORNO", "Cli - Con", "Cli - Con / Con - Cli", "D55 - DPT", "IDA + RETORNO"):
    assert f("2026-11-01 10:00", "2026-12-01", tipo=tipo) == "aviso", tipo
# Consulado -> Cliente: sem aviso de 30 dias (já tem o alerta de 70), mas reembolsa no dia 89
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
print("ok")

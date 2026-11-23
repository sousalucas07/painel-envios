"""Auto-teste offline da regra de validade da etiqueta: python teste_validade.py"""
from datetime import date

import tracker

PRE = "Pre Transit - SHIPPING LABEL CREATED"
f = lambda compra, hoje, status=PRE: tracker.fase_validade(status, compra, date.fromisoformat(hoje))

assert f("2026-11-01 10:00", "2026-11-25") is None          # 24 dias
assert f("2026-11-01 10:00", "2026-11-26") == "aviso"       # dia 25
assert f("2026-11-01 10:00", "2026-11-30") == "aviso"       # dia 29
assert f("2026-11-01 10:00", "2026-12-01") is None          # venceu: espera os 5 dias
assert f("2026-11-01 10:00", "2026-12-05") is None          # dia 34
assert f("2026-11-01 10:00", "2026-12-06") == "reembolso"   # dia 35
assert f("2026-11-01 10:00", "2026-12-20") == "reembolso"   # ciclo falhou: tenta de novo depois
assert f("2026-11-01 10:00", "2026-12-06", "Transit - ARRIVE USPS FACILITY") is None
assert f("2026-11-01 10:00", "2026-12-06", "Delivered - DELIVERED") is None
assert f("2026-11-01 10:00", "2026-12-06", "AGUARDANDO ATUALIZAR STATUS") is None
assert f("", "2026-12-06") is None
# Etiquetas que já tinham passado do marco antes de a regra entrar (24/11/2026)
assert f("2026-10-19 10:00", "2026-11-24") is None          # dia 35 caiu em 23/11
assert f("2026-10-20 10:00", "2026-11-24") == "reembolso"   # dia 35 cai em 24/11
assert f("2026-10-29 10:00", "2026-11-24") is None          # dia 25 caiu em 23/11: sem aviso
assert f("2026-10-29 10:00", "2026-12-03") == "reembolso"   # ...mas reembolsa no dia 35
assert f("2026-10-30 10:00", "2026-11-24") == "aviso"
print("ok")

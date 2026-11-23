"""Auto-teste offline da regra de validade da etiqueta: python teste_validade.py"""
from datetime import date

import tracker

PRE = "Pre Transit - SHIPPING LABEL CREATED"
f = lambda compra, hoje, status=PRE: tracker.fase_validade(status, compra, date.fromisoformat(hoje))

assert f("2026-11-01 10:00", "2026-11-25") is None          # 24 dias
assert f("2026-11-01 10:00", "2026-11-26") == "aviso"       # dia 25
assert f("2026-11-01 10:00", "2026-11-30") == "aviso"       # dia 29
assert f("2026-11-01 10:00", "2026-12-01") is None          # venceu: a USPS ainda costuma aceitar
assert f("2026-11-01 10:00", "2027-01-28") is None          # dia 88
assert f("2026-11-01 10:00", "2027-01-29") == "reembolso"   # dia 89: véspera do prazo da Shippo
assert f("2026-11-01 10:00", "2027-01-29", "Transit - ARRIVE USPS FACILITY") is None
assert f("2026-11-01 10:00", "2027-01-29", "Delivered - DELIVERED") is None
assert f("2026-11-01 10:00", "2027-01-29", "AGUARDANDO ATUALIZAR STATUS") is None
assert f("", "2027-01-29") is None
# Etiquetas que já tinham passado do dia 25 antes de a regra entrar (24/11/2026): sem aviso
assert f("2026-10-29 10:00", "2026-11-24") is None          # dia 25 caiu em 23/11
assert f("2026-10-30 10:00", "2026-11-24") == "aviso"
assert f("2026-10-19 10:00", "2027-01-16") == "reembolso"   # ...mas o reembolso do dia 89 vale para todas
print("ok")

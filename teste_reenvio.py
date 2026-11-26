"""Reenvio do WhatsApp que falhou. Rode: python teste_reenvio.py"""
from datetime import date

import tracker

# Qual aviso cada mudança de status pede
assert tracker.evento_whatsapp("Transit - Accepted", "Pre Transit") == "coleta"
assert tracker.evento_whatsapp("Transit - Arrived", "Transit - Accepted") is None
assert tracker.evento_whatsapp("Delivered", "Transit - Arrived") == "entrega"
assert tracker.evento_whatsapp("Delivered - Front door", "Delivered") is None
assert tracker.evento_whatsapp("Pre Transit", "") is None

# Célula da planilha: tenta por DIAS_REENVIO dias, depois desiste
hoje = date(2026, 11, 26)
assert tracker.pendencia("coleta|2026-11-26", hoje) == ("coleta", False)
assert tracker.pendencia("entrega|2026-11-24", hoje) == ("entrega", False)
assert tracker.pendencia("entrega|2026-11-23", hoje) == ("entrega", True)
assert tracker.pendencia("lixo", hoje) == ("lixo", True)

# Envio falhou -> a mudança devolve o evento como não enviado; envio ok -> enviado
tracker.obter_telefone_bitrix = lambda deal_id: "5500000000000"
tracker.enviar_whatsapp_direto = lambda tel, msg: False
assert tracker.processar_regras_automacao("1", "Delivered", "IDA", None, "Transit") == ("entrega", False)
assert tracker.reenviar_pendente("1", "IDA", f"entrega|{tracker.agora_br():%Y-%m-%d}") != ""
tracker.enviar_whatsapp_direto = lambda tel, msg: True
assert tracker.processar_regras_automacao("1", "Delivered", "IDA", None, "Transit") == ("entrega", True)
assert tracker.reenviar_pendente("1", "IDA", f"entrega|{tracker.agora_br():%Y-%m-%d}") == ""
# Trecho sem aviso não fica pendente
assert tracker.processar_regras_automacao("1", "Delivered", "RETORNO", None, "Transit") == ("entrega", True)
# Sem sessão no WhatCRM = não conectado
tracker.requests.get = lambda *a, **k: type("R", (), {"json": lambda self: {"accountStatus": "init"}})()
assert tracker.whatsapp_conectado() is False

print("ok")

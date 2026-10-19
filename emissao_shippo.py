import hmac
import os
import re
import time

import requests

from departamentos import DEPARTAMENTOS_ESTADO
from label_passaporte import ENDERECOS_CONSULADOS

API_SHIPPO = "https://api.goshippo.com"
LINK_USPS = "https://tools.usps.com/go/TrackConfirmAction?tLabels="

# ---------------------------------------------------------------------------
# AJUSTES (confirmar antes de usar a chave live)
# ---------------------------------------------------------------------------
ESCRITORIO = {
    "name": "DESPACHANTE 55",
    "street1": "1941 WANTAGH AVE",
    "street2": "SUITE 204",
    "city": "WANTAGH",
    "state": "NY",
    "zip": "11793",
    "country": "US",
    "phone": "9294188661",
    "email": "isabellemoura@despachante55.com",  # obrigatório na conta USPS da Shippo; vai em todos os endereços
}
# Priority Mail Flat Rate Envelope, igual às etiquetas da ShippingEasy (preço fixo em qualquer zona).
# Outros: USPS_FlatRateLegalEnvelope, USPS_FlatRatePaddedEnvelope
PACOTE = {"template": "USPS_FlatRateEnvelope", "weight": "8", "mass_unit": "oz"}
SERVICO = "usps_priority"  # Priority Mail: o mesmo de todas as etiquetas da ShippingEasy
FORMATO_ETIQUETA = "PNG"   # 4x6, igual à configuração da ShippingEasy

# Tipo de envio da tela -> etiquetas (tipo gravado na planilha, origem, destino)
MODOS = {
    "IDA": [("IDA", "ESC", "CLI")],
    "RETORNO": [("RETORNO", "CLI", "ESC")],
    "IDA + RETORNO": [("IDA", "ESC", "CLI"), ("RETORNO", "CLI", "ESC")],
    "Cli - Con / Con - Cli": [("Cli - Con", "CLI", "CON"), ("Con - Cli", "CON", "CLI")],
    "Cli - Con (Passaporte)": [("Cli - Con", "CLI", "CON")],
    "D55 - DPT / DPT - D55": [("D55 - DPT", "ESC", "DPT"), ("DPT - D55", "DPT", "ESC")],
}


# ==============================================================================
# ENDEREÇOS
# ==============================================================================
def endereco_consulado(nome):
    """Converte o texto de ENDERECOS_CONSULADOS (mesmo usado na Label 228) em endereço Shippo."""
    linhas = ENDERECOS_CONSULADOS[nome].split("\n")
    cidade, resto = linhas[-1].rsplit(",", 1)
    estado, zip_code = resto.split()
    return {
        "name": linhas[0], "street1": linhas[1], "street2": " ".join(linhas[2:-1]),
        "city": cidade.strip(), "state": estado, "zip": zip_code, "country": "US",
        "phone": ESCRITORIO["phone"],
    }


def endereco_departamento(nome):
    d = DEPARTAMENTOS_ESTADO[nome]
    return {
        "name": f"DPT {nome}", "company": d["nome"], "street1": d["endereco"],
        "city": d["cidade"], "state": d["estado"], "zip": d["zip"], "country": "US",
        "phone": d.get("telefone") or ESCRITORIO["phone"],
    }


def endereco_cliente(dados):
    """dados: campos do extrair_endereco (nome, endereco, cidade, estado, zip, telefone)."""
    telefone = re.sub(r"\D", "", dados.get("telefone", ""))
    return {
        "name": dados["nome"].strip().upper(), "street1": dados["endereco"].strip().upper(),
        "city": dados["cidade"].strip().upper(), "state": dados["estado"].strip().upper(),
        "zip": dados["zip"].strip(), "country": "US",
        "phone": telefone if len(telefone) >= 10 else ESCRITORIO["phone"],
    }


# ==============================================================================
# API SHIPPO
# ==============================================================================
def chave_shippo():
    chave = os.getenv("SHIPPO_LIVE_KEY", "")
    if not chave:
        raise RuntimeError("SHIPPO_LIVE_KEY não configurada no .env / Secrets.")
    return chave


def _shippo(caminho, payload):
    resp = requests.post(
        f"{API_SHIPPO}{caminho}", json=payload, timeout=60,
        headers={"Authorization": f"ShippoToken {chave_shippo()}"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Shippo {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _mensagens(obj):
    return "; ".join(m.get("text", "") for m in obj.get("messages") or []) or "sem detalhes"


def cotar(origem, destino, referencia):
    """Cria o shipment e devolve a tarifa do SERVICO (sem cobrar nada)."""
    shp = _shippo("/shipments/", {
        "address_from": {"email": ESCRITORIO["email"], **origem},
        "address_to": {"email": ESCRITORIO["email"], **destino},
        "parcels": [PACOTE],
        "extra": {"reference_1": referencia},  # sai na etiqueta, como o "Order:" da ShippingEasy
        "metadata": referencia, "async": False,
    })
    rates = shp.get("rates") or []
    rate = next((r for r in rates if r["servicelevel"]["token"] == SERVICO), None)
    if not rate:
        disponiveis = ", ".join(sorted({r["servicelevel"]["token"] for r in rates})) or "nenhum"
        raise RuntimeError(f"Serviço {SERVICO} indisponível ({_mensagens(shp)}). Disponíveis: {disponiveis}")
    return rate


def comprar(rate, referencia):
    """Compra a etiqueta (COBRA na chave live). Devolve rastreio, URL da etiqueta e custo."""
    tx = _shippo("/transactions/", {
        "rate": rate["object_id"], "label_file_type": FORMATO_ETIQUETA,
        "metadata": referencia, "async": False,
    })
    if tx.get("status") != "SUCCESS":
        raise RuntimeError(f"Compra recusada: {_mensagens(tx)}")
    return tx["tracking_number"], tx["label_url"], float(rate["amount"])


def emitir(modo, num_pedido, cliente=None, consulado=None, departamento=None, ao_comprar=None):
    """Emite as etiquetas do modo, uma por vez.

    ao_comprar(etiqueta) é chamado logo após cada compra, para registrar na planilha
    antes da próxima: se a segunda falhar, a primeira já está gravada.
    """
    enderecos = {"ESC": ESCRITORIO}
    if cliente:
        enderecos["CLI"] = cliente
    if consulado:
        enderecos["CON"] = endereco_consulado(consulado)
    if departamento:  # nome de DEPARTAMENTOS_ESTADO ou endereço digitado (dict)
        enderecos["DPT"] = departamento if isinstance(departamento, dict) else endereco_departamento(departamento)

    etiquetas = []
    for tipo, de, para in MODOS[modo]:
        referencia = f"{num_pedido} {tipo}"
        rate = cotar(enderecos[de], enderecos[para], referencia)
        rastreio, url, custo = comprar(rate, referencia)
        arquivo = requests.get(url, timeout=60)
        arquivo.raise_for_status()
        etiqueta = {"tipo": tipo, "rastreio": rastreio, "custo": custo, "arquivo": arquivo.content}
        if ao_comprar:
            ao_comprar(etiqueta)
        etiquetas.append(etiqueta)
    return etiquetas


# ==============================================================================
# REEMBOLSO (cancelar etiqueta não usada)
# ==============================================================================
PRAZO_REEMBOLSO_DIAS = 90
STATUS_USADA = ("TRANSIT", "DELIVERED", "RETURNED", "FAILURE")


def _shippo_get(caminho, params=None):
    resp = requests.get(
        f"{API_SHIPPO}{caminho}", params=params, timeout=60,
        headers={"Authorization": f"ShippoToken {chave_shippo()}"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Shippo {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def buscar_compra(rastreio):
    """Acha a transação (compra) do rastreio, da mais nova para a mais antiga.

    A Shippo não filtra transação por rastreio: percorre as páginas até achar
    ou até passar do prazo de reembolso.
    """
    from datetime import datetime, timedelta, timezone

    limite = datetime.now(timezone.utc) - timedelta(days=PRAZO_REEMBOLSO_DIAS)
    params = {"results": 100, "object_status": "SUCCESS", "page": 1}
    while True:
        pagina = _shippo_get("/transactions/", params)
        resultados = pagina.get("results") or []
        for tx in resultados:
            if tx.get("tracking_number") == rastreio:
                return tx
        mais_antiga = min((tx.get("object_created", "") for tx in resultados), default="")
        if (
            not pagina.get("next")
            or not mais_antiga
            or datetime.fromisoformat(mais_antiga.replace("Z", "+00:00")) < limite
        ):
            return None
        params["page"] += 1


def consultar_reembolso(rastreio):
    """Junta o que a tela mostra antes de confirmar. 'bloqueio' preenchido = não reembolsar."""
    from datetime import datetime, timedelta, timezone

    tx = buscar_compra(rastreio)
    if not tx:
        return {"bloqueio": (
            "Compra não encontrada na Shippo (só etiquetas emitidas por este sistema,"
            f" nos últimos {PRAZO_REEMBOLSO_DIAS} dias)."
        )}

    criada = datetime.fromisoformat(tx["object_created"].replace("Z", "+00:00"))
    status_usps = (_shippo_get(f"/tracks/usps/{rastreio}").get("tracking_status") or {}).get("status") or "UNKNOWN"
    rate = tx.get("rate")
    valor = float(_shippo_get(f"/rates/{rate}")["amount"]) if isinstance(rate, str) else float(rate["amount"])

    bloqueio = ""
    if status_usps in STATUS_USADA:
        bloqueio = f"Etiqueta já usada na USPS (status {status_usps}): a Shippo recusa o reembolso."
    elif datetime.now(timezone.utc) - criada > timedelta(days=PRAZO_REEMBOLSO_DIAS):
        bloqueio = f"Compra com mais de {PRAZO_REEMBOLSO_DIAS} dias: fora do prazo de reembolso."

    return {
        "transacao": tx["object_id"], "rastreio": rastreio, "referencia": tx.get("metadata") or "",
        "criada": criada.strftime("%d/%m/%Y"), "status_usps": status_usps, "valor": valor,
        "bloqueio": bloqueio,
    }


def pedir_reembolso(transacao):
    """Pede o reembolso (irreversível). Devolve o status: QUEUED, PENDING, SUCCESS ou ERROR."""
    return _shippo("/refunds/", {"transaction": transacao, "async": False}).get("status", "ERROR")


# ==============================================================================
# TELA (aba "Emitir Etiquetas")
# ==============================================================================
def _ja_emitidas(df, num_pedido, tipos):
    from leitor_foto import _coluna

    col_pedido, col_tipo = _coluna(df, "id", "pedido", "bitrix"), _coluna(df, "tipo")
    if df.empty or not col_pedido or not col_tipo:
        return []
    linhas = df[df[col_pedido].astype(str).str.strip() == num_pedido]
    return sorted(set(linhas[col_tipo].astype(str).str.strip()) & set(tipos))


def renderizar_aba_emissao():
    import streamlit as st

    from label_passaporte import (
        CAMPOS_CLIENTE, CAMPOS_OBRIGATORIOS, extrair_endereco, gerar_label_passaporte_png,
    )
    from leitor_foto import TAMANHO_MAX_FOTO
    from sheets import ler_envios_sheets, registrar_envio_sheets

    st.title("📦 Emitir Etiquetas")

    # Senha extra só desta aba (EMISSAO_SENHA no .env / Secrets): aqui se gasta dinheiro
    if not st.session_state.get("emissao_liberada"):
        senha_correta = os.getenv("EMISSAO_SENHA", "")
        if not senha_correta:
            st.error("❌ EMISSAO_SENHA não configurada no .env / Secrets. Emissão bloqueada.")
            return
        with st.form("form_emissao_senha"):
            senha = st.text_input("Senha da emissão", type="password")
            entrar = st.form_submit_button("Liberar")
        if entrar:
            if hmac.compare_digest(senha.encode(), senha_correta.encode()):
                st.session_state["emissao_liberada"] = True
                st.rerun()
            time.sleep(1)
            st.error("❌ Senha incorreta.")
        return

    col_pedido, col_modo = st.columns([1, 2])
    num_pedido = col_pedido.text_input("Número do Pedido / ID Bitrix *", key="emi_pedido").strip()
    modo = col_modo.radio("Tipo de Envio:", list(MODOS), horizontal=True, key="emi_modo")

    def _bloco_endereco(prefixo, rotulo):
        """Documento ou texto -> IA preenche os campos -> a pessoa confere. Devolve (dados, faltando)."""
        comprovante = st.file_uploader(
            f"Comprovante / documento com o endereço {rotulo}",
            type=["jpg", "jpeg", "png", "webp", "pdf"], key=f"{prefixo}comprovante",
        )
        texto = st.text_area(
            f"...ou cole aqui o nome e o endereço {rotulo}", max_chars=1000, key=f"{prefixo}texto",
        )
        if st.button("🧠 Ler endereço", disabled=not (comprovante or texto.strip()), key=f"{prefixo}ler"):
            if comprovante and comprovante.size > TAMANHO_MAX_FOTO:
                st.error("❌ Arquivo maior que 15 MB.")
            else:
                try:
                    with st.spinner("Lendo o endereço..."):
                        dados = extrair_endereco(
                            texto.strip(),
                            comprovante.getvalue() if comprovante else None,
                            comprovante.type if comprovante else None,
                        )
                    for c in CAMPOS_CLIENTE:
                        st.session_state[f"{prefixo}{c}"] = dados[c]
                except Exception as e:
                    st.error(f"❌ Falha na leitura ({type(e).__name__}: {e})")

        st.caption("Confira e corrija antes de comprar:")
        cols = st.columns(3)
        for i, c in enumerate(CAMPOS_CLIENTE):
            cols[i % 3].text_input(c.capitalize(), key=f"{prefixo}{c}")
        dados = {c: st.session_state.get(f"{prefixo}{c}", "").strip() for c in CAMPOS_CLIENTE}
        return dados, [c for c in CAMPOS_OBRIGATORIOS if not dados[c]]

    OUTRO_DPT = "✏️ Outro endereço (digitar)"
    consulado = departamento = None
    faltando = []
    if "CON" in {e for _, de, para in MODOS[modo] for e in (de, para)}:
        consulado = st.selectbox("🏛️ Consulado:", sorted(ENDERECOS_CONSULADOS), key="emi_consulado")
    if modo.startswith("D55"):
        departamento = st.selectbox(
            "🏛️ Departamento de Estado:", sorted(DEPARTAMENTOS_ESTADO) + [OUTRO_DPT], key="emi_dpt",
        )
        if departamento == OUTRO_DPT:
            dpt_dados, faltando = _bloco_endereco("emi_dpt_", "do departamento")
            departamento = endereco_cliente(dpt_dados)  # emitir() aceita o endereço já montado

    # 1) Endereço do cliente: IA preenche, a pessoa confere antes de comprar
    if not modo.startswith("D55"):
        cliente_dados, faltando = _bloco_endereco("emi_cli_", "do cliente")
    else:
        cliente_dados = None

    # 2) Trava contra etiqueta duplicada (mesmo pedido + tipo já na planilha)
    tipos = [t for t, _, _ in MODOS[modo]]
    repetidas = _ja_emitidas(ler_envios_sheets(), num_pedido, tipos) if num_pedido else []
    forcar = False
    if repetidas:
        st.warning(f"⚠️ O pedido {num_pedido} já tem etiqueta {', '.join(repetidas)} na planilha.")
        forcar = st.checkbox("Emitir mesmo assim (vai cobrar de novo)", key="emi_forcar")

    pronto = num_pedido.isdigit() and not faltando and (not repetidas or forcar)
    if faltando:
        st.caption(f"Faltando: {', '.join(faltando)}")

    if st.button(f"💳 Comprar {len(tipos)} etiqueta(s)", type="primary", disabled=not pronto, use_container_width=True):
        if cliente_dados:
            nome = cliente_dados["nome"].upper()
        elif isinstance(departamento, dict):
            nome = departamento["name"]
        else:
            nome = f"DPT {departamento}"

        etiquetas = []

        def registrar(etiqueta):
            etiquetas.append(etiqueta)  # já comprada: mostra na tela mesmo se a planilha falhar
            ok = registrar_envio_sheets({
                "num_pedido": num_pedido, "nome": nome,
                "tracking_code": LINK_USPS + etiqueta["rastreio"],
                "tipo_envio": etiqueta["tipo"], "custo": etiqueta["custo"],
            })
            if not ok:  # para antes de comprar a próxima
                raise RuntimeError(
                    f"Etiqueta {etiqueta['tipo']} comprada ({etiqueta['rastreio']}) mas NÃO gravada"
                    " na planilha. Cadastre manualmente na aba Inserir Rastreio Antigo."
                )

        try:
            with st.spinner("Comprando etiquetas na Shippo..."):
                emitir(
                    modo, num_pedido,
                    cliente=endereco_cliente(cliente_dados) if cliente_dados else None,
                    consulado=consulado, departamento=departamento, ao_comprar=registrar,
                )
        except Exception as e:
            print(f"❌ Emissão pedido {num_pedido}: {e}", flush=True)
            st.error(f"❌ {e}")
        st.session_state["emi_resultado"] = {"pedido": num_pedido, "etiquetas": etiquetas}
        if modo == "Cli - Con (Passaporte)" and etiquetas:
            st.session_state["emi_resultado"]["label_228"] = gerar_label_passaporte_png(consulado, cliente_dados)

    res = st.session_state.get("emi_resultado")
    if res and res["etiquetas"]:
        ext = "png" if FORMATO_ETIQUETA == "PNG" else "pdf"
        st.success(f"✅ {len(res['etiquetas'])} etiqueta(s) do pedido #{res['pedido']} compradas e registradas.")
        for e in res["etiquetas"]:
            st.markdown(f"**{e['tipo']}**: `{e['rastreio']}` (US$ {e['custo']:.2f})")
            if ext == "png":
                st.image(e["arquivo"], width=420)
            st.download_button(
                f"⬇️ Baixar etiqueta {e['tipo']}", data=e["arquivo"],
                file_name=f"Etiqueta_{res['pedido']}_{e['tipo'].replace(' ', '')}.{ext}",
                mime="image/png" if ext == "png" else "application/pdf",
                use_container_width=True, key=f"emi_dl_{e['rastreio']}",
            )
        if res.get("label_228"):
            st.image(res["label_228"], caption="Label 228 (envelope passaporte)", width=420)
            st.download_button(
                "⬇️ Baixar Label 228", data=res["label_228"],
                file_name=f"Label_Passaporte_{res['pedido']}.png", mime="image/png",
                use_container_width=True, key="emi_dl_228",
            )

    st.markdown("---")
    renderizar_reembolso()


def renderizar_reembolso():
    import streamlit as st

    from sheets import deletar_envios_sheets, ler_envios_sheets, registrar_reembolso_sheets

    st.markdown("### ↩️ Cancelar etiqueta (reembolso)")
    st.caption(
        "Só etiquetas emitidas por esta aba, ainda não escaneadas pela USPS e com até"
        f" {PRAZO_REEMBOLSO_DIAS} dias. O valor volta como crédito na próxima fatura da Shippo."
    )
    col_r, col_b = st.columns([3, 1])
    rastreio = re.sub(r"\D", "", col_r.text_input("Rastreio da etiqueta", key="ree_rastreio"))
    col_b.write("")
    col_b.write("")
    if col_b.button("🔎 Consultar", disabled=not rastreio, use_container_width=True):
        try:
            with st.spinner("Procurando a compra na Shippo..."):
                st.session_state["ree_consulta"] = consultar_reembolso(rastreio)
        except Exception as e:
            st.session_state.pop("ree_consulta", None)
            st.error(f"❌ {e}")

    c = st.session_state.get("ree_consulta")
    if not c or c.get("rastreio", rastreio) != rastreio:
        return
    if c["bloqueio"]:
        st.error(f"❌ {c['bloqueio']}")
        return

    st.info(
        f"**{c['referencia'] or 'sem referência'}** · comprada em {c['criada']}"
        f" · US$ {c['valor']:.2f} · status USPS: {c['status_usps']}"
    )
    if not st.button("↩️ Confirmar reembolso (irreversível)", type="primary", use_container_width=True):
        return

    st.session_state.pop("ree_consulta", None)  # um clique, um pedido de reembolso
    try:
        status = pedir_reembolso(c["transacao"])
    except Exception as e:
        st.error(f"❌ {e}")
        return
    if status == "ERROR":
        st.error("❌ A Shippo recusou o reembolso (etiqueta usada ou já reembolsada).")
        return

    # Pedido aceito: tira do painel (o tracker não monitora mais) e lança o negativo na auditoria
    df = ler_envios_sheets()
    linha = {}
    if not df.empty:
        from leitor_foto import _coluna

        col_r = _coluna(df, "rastreio", "tracking")
        achadas = df[df[col_r].astype(str).str.replace(r"\D", "", regex=True) == c["rastreio"]] if col_r else df.iloc[0:0]
        if not achadas.empty:
            linha = {
                "pedido": achadas.iloc[0][_coluna(df, "id", "pedido", "bitrix")],
                "nome": achadas.iloc[0][_coluna(df, "nome")],
                "tipo": achadas.iloc[0][_coluna(df, "tipo")],
            }
    pedido, _, tipo = c["referencia"].partition(" ")  # referência = "<pedido> <tipo>"
    nao_apagados = deletar_envios_sheets([c["rastreio"]])
    auditoria_ok = registrar_reembolso_sheets({
        "num_pedido": linha.get("pedido") or pedido,
        "nome": linha.get("nome", ""),
        "tracking_code": LINK_USPS + c["rastreio"],
        "tipo_envio": f"REEMBOLSO {linha.get('tipo') or tipo} ({status})",
        "custo": -c["valor"],
    })

    st.success(f"✅ Reembolso solicitado (status {status}). O crédito pode levar até 14 dias.")
    if nao_apagados:
        st.warning("⚠️ Rastreio não encontrado no painel: nada foi apagado lá.")
    if not auditoria_ok:
        st.warning(f"⚠️ Não gravou na auditoria. Lance à mão: -US$ {c['valor']:.2f}, rastreio {c['rastreio']}.")


if __name__ == "__main__":
    # Auto-teste offline: python emissao_shippo.py
    for nome in ENDERECOS_CONSULADOS:
        end = endereco_consulado(nome)
        assert len(end["state"]) == 2 and end["zip"][:5].isdigit(), (nome, end)
    assert endereco_consulado("WASHINGTON")["street2"] == "ATT: SETOR DE PASSAPORTE"
    for nome in DEPARTAMENTOS_ESTADO:
        assert len(endereco_departamento(nome)["state"]) == 2
    cli = endereco_cliente({"nome": "maria", "endereco": "1 Main St", "cidade": "x", "estado": "nj", "zip": "07105", "telefone": "12"})
    assert cli["state"] == "NJ" and cli["phone"] == ESCRITORIO["phone"]
    assert all(de in {"ESC", "CLI", "CON", "DPT"} for m in MODOS.values() for _, de, _ in m)
    print("ok")

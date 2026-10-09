import json
import os
import re
import time

import pandas as pd
import requests
import streamlit as st

from sheets import ler_envios_sheets, registrar_envio_sheets

MODELO_GEMINI = "gemini-flash-latest"
TIPO_ENVIO_FOTO = "Con - Cli"
LINK_USPS = "https://tools.usps.com/go/TrackConfirmAction?tLabels="
TAMANHO_MAX_FOTO = 15 * 1024 * 1024

PROMPT = """A foto mostra um ou mais recibos/etiquetas de envio da USPS.
Para CADA etiqueta visível, extraia:
- "rastreio": o número de rastreio impresso (USPS Tracking #), somente os dígitos, sem espaços.
- "pedido": o número escrito à mão na etiqueta (normalmente ao lado de "Receipt"), somente os dígitos.
Devolva uma linha por etiqueta. Se o número do pedido não estiver legível, devolva "pedido" vazio.
Não invente dígitos."""

SCHEMA_RESPOSTA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "pedido": {"type": "STRING"},
            "rastreio": {"type": "STRING"},
        },
        "required": ["pedido", "rastreio"],
    },
}


# ==============================================================================
# VALIDAÇÃO
# ==============================================================================
def so_digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def digito_verificador_ok(rastreio):
    """MOD 10 da USPS: da direita para a esquerda, pesos 3 e 1 alternados."""
    corpo, dv = rastreio[:-1], int(rastreio[-1])
    soma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(corpo)))
    return (10 - soma % 10) % 10 == dv


def avaliar_linha(pedido, rastreio, nome, ja_cadastrados, repetidos_no_lote):
    """Devolve (nivel, motivo). nivel: 'ok', 'suspeito' (salva só com permissão) ou 'bloqueado'."""
    if not pedido:
        return "bloqueado", "⛔ sem número do pedido"
    if not 20 <= len(rastreio) <= 22:
        return "bloqueado", f"⛔ rastreio com {len(rastreio)} dígitos (esperado 20 a 22)"
    if rastreio in ja_cadastrados:
        return "bloqueado", "⛔ já cadastrado na planilha"
    if rastreio in repetidos_no_lote:
        return "bloqueado", "⛔ repetido nesta lista"
    if not digito_verificador_ok(rastreio):
        return "suspeito", "⚠️ dígito verificador não confere"
    if not nome:
        return "suspeito", "⚠️ cliente não encontrado para este pedido"
    return "ok", "✅ pronto"


# ==============================================================================
# GEMINI
# ==============================================================================
def ler_etiquetas(imagem_bytes, mime_type):
    """Envia a foto ao Gemini e devolve [{'pedido': ..., 'rastreio': ...}] só com dígitos."""
    from google import genai
    from google.genai import types

    chave = os.getenv("GEMINI_API_KEY", "")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não configurada no .env / Secrets.")

    client = genai.Client(api_key=chave)
    resposta = client.models.generate_content(
        model=MODELO_GEMINI,
        contents=[
            types.Part.from_bytes(data=imagem_bytes, mime_type=mime_type),
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA_RESPOSTA,
            temperature=0,
        ),
    )
    itens = json.loads(resposta.text or "[]")
    return [
        {"pedido": so_digitos(i.get("pedido")), "rastreio": so_digitos(i.get("rastreio"))}
        for i in itens
        if so_digitos(i.get("rastreio"))
    ]


# ==============================================================================
# NOME DO CLIENTE (planilha primeiro, depois Bitrix)
# ==============================================================================
def _coluna(df, *trechos):
    return next((c for c in df.columns if any(t in c.lower() for t in trechos)), None)


def rastreios_da_planilha(df):
    col = _coluna(df, "rastreio", "tracking") if not df.empty else None
    if not col:
        return set()
    return {m.group(0) for v in df[col].astype(str) if (m := re.search(r"\d{15,30}", v))}


def nome_na_planilha(pedido, df):
    if df.empty:
        return ""
    col_pedido = _coluna(df, "id", "pedido", "bitrix")
    col_nome = _coluna(df, "nome")
    if not col_pedido or not col_nome:
        return ""
    nomes = df.loc[df[col_pedido].astype(str).str.strip() == pedido, col_nome]
    return next((str(n).strip() for n in nomes if str(n).strip()), "")


@st.cache_data(ttl=600, show_spinner=False)
def nome_no_bitrix(pedido):
    base_url = os.getenv("BITRIX_WEBHOOK_URL", "").strip().strip("\"'").rstrip("/")
    if not base_url.startswith("http"):
        return ""
    try:
        negocio = requests.get(
            f"{base_url}/crm.deal.get.json", params={"id": pedido}, timeout=10
        ).json().get("result") or {}
        contato_id = negocio.get("CONTACT_ID")
        if not contato_id:
            return ""
        contato = requests.get(
            f"{base_url}/crm.contact.get.json", params={"id": contato_id}, timeout=10
        ).json().get("result") or {}
        return f"{contato.get('NAME') or ''} {contato.get('LAST_NAME') or ''}".strip()
    except Exception as e:
        # Só o tipo do erro: a mensagem do requests traz a URL do webhook (segredo)
        print(f"⚠️ Erro ao buscar nome no Bitrix para o pedido {pedido}: {type(e).__name__}")
        return ""


def buscar_nome(pedido, df):
    if not pedido:
        return ""
    return nome_na_planilha(pedido, df) or nome_no_bitrix(pedido)


# ==============================================================================
# ABA DO STREAMLIT
# ==============================================================================
def renderizar_aba_foto():
    st.title("📸 Adicionar foto dos selos")
    st.markdown(
        "Envie a foto dos recibos da USPS com o número do pedido escrito à mão."
        f" Cada etiqueta entra como **{TIPO_ENVIO_FOTO}**."
    )
    st.markdown("---")

    fotos = st.file_uploader(
        "Fotos das etiquetas",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    if st.button("🔍 Ler etiquetas", disabled=not fotos, use_container_width=True):
        lidas = []
        with st.spinner("Lendo as etiquetas com o Gemini..."):
            for foto in fotos:
                dados = foto.getvalue()
                if len(dados) > TAMANHO_MAX_FOTO:
                    st.error(f"❌ {foto.name}: foto maior que 15 MB.")
                    continue
                try:
                    lidas += ler_etiquetas(dados, foto.type or "image/jpeg")
                except Exception as e:
                    st.error(f"❌ {foto.name}: falha na leitura ({type(e).__name__}: {e})")
        st.session_state["foto_lidas"] = lidas
        st.session_state.pop("foto_editor", None)
        if not lidas:
            st.warning("⚠️ Nenhuma etiqueta identificada.")

    lidas = st.session_state.get("foto_lidas")
    if not lidas:
        return

    st.markdown("### ✏️ Corrija o que a IA leu errado")
    editado = st.data_editor(
        pd.DataFrame(lidas, columns=["pedido", "rastreio"]).assign(salvar=True),
        column_config={
            "salvar": st.column_config.CheckboxColumn("Salvar"),
            "pedido": st.column_config.TextColumn("Pedido / ID Bitrix"),
            "rastreio": st.column_config.TextColumn("Rastreio USPS"),
        },
        column_order=["salvar", "pedido", "rastreio"],
        hide_index=True,
        use_container_width=True,
        key="foto_editor",
    )

    def montar_conferencia(df_planilha):
        ja_cadastrados = rastreios_da_planilha(df_planilha)
        linhas = [
            (so_digitos(l.pedido), so_digitos(l.rastreio))
            for l in editado.itertuples()
            if l.salvar
        ]
        todos = [r for _, r in linhas]
        repetidos = {r for r in todos if todos.count(r) > 1}
        conferencia = []
        for pedido, rastreio in linhas:
            nome = buscar_nome(pedido, df_planilha)
            nivel, motivo = avaliar_linha(pedido, rastreio, nome, ja_cadastrados, repetidos)
            conferencia.append(
                {"pedido": pedido, "nome": nome, "rastreio": rastreio, "nivel": nivel, "situacao": motivo}
            )
        return conferencia

    conferencia = montar_conferencia(ler_envios_sheets())
    if not conferencia:
        st.info("Nenhuma linha marcada para salvar.")
        return

    st.markdown("### ✅ Conferência")
    st.caption("Confira se o nome é mesmo do cliente do pedido: é a proteção contra número manuscrito lido errado.")
    st.dataframe(
        pd.DataFrame(conferencia)[["pedido", "nome", "rastreio", "situacao"]],
        hide_index=True,
        use_container_width=True,
    )

    permitir_suspeitos = st.checkbox("Salvar também as linhas com ⚠️")
    niveis_aceitos = {"ok", "suspeito"} if permitir_suspeitos else {"ok"}
    qtd = sum(1 for c in conferencia if c["nivel"] in niveis_aceitos)

    if st.button(
        f"💾 Adicionar {qtd} etiqueta(s) ao monitoramento",
        type="primary",
        disabled=qtd == 0,
        use_container_width=True,
    ):
        gravados, falhas = [], []
        with st.spinner("Gravando na planilha..."):
            # Relê a planilha: um duplo clique ou nova tentativa não duplica linhas
            for c in montar_conferencia(ler_envios_sheets()):
                if c["nivel"] not in niveis_aceitos:
                    continue
                ok = registrar_envio_sheets({
                    "num_pedido": c["pedido"],
                    "nome": c["nome"],
                    "tracking_code": LINK_USPS + c["rastreio"],
                    "tipo_envio": TIPO_ENVIO_FOTO,
                })
                (gravados if ok else falhas).append(c["pedido"])
                time.sleep(1)  # cota de escrita do Google Sheets

        if gravados:
            st.success(f"✅ {len(gravados)} etiqueta(s) cadastrada(s): pedidos {', '.join(gravados)}.")
        if falhas:
            st.error(
                f"❌ Falha ao cadastrar os pedidos {', '.join(falhas)}."
                " Clique de novo: o que já foi gravado não duplica."
            )
        else:
            st.session_state.pop("foto_lidas", None)


if __name__ == "__main__":
    # Auto-teste: python leitor_foto.py
    assert digito_verificador_ok("9400111899223197428497")
    assert not digito_verificador_ok("9400111899223197428498")
    assert so_digitos("9400 1118-9922 ") == "940011189922"
    bom = "9400111899223197428497"
    assert avaliar_linha("262", bom, "Ana", set(), set())[0] == "ok"
    assert avaliar_linha("", bom, "Ana", set(), set())[0] == "bloqueado"
    assert avaliar_linha("262", bom[:15], "Ana", set(), set())[0] == "bloqueado"
    assert avaliar_linha("262", bom, "Ana", {bom}, set())[0] == "bloqueado"
    assert avaliar_linha("262", bom, "Ana", set(), {bom})[0] == "bloqueado"
    assert avaliar_linha("262", bom, "", set(), set())[0] == "suspeito"
    assert avaliar_linha("262", bom[:-1] + "8", "Ana", set(), set())[0] == "suspeito"
    df = pd.DataFrame(
        [["262", "Ana Lima", LINK_USPS + bom]], columns=["PEDIDO", "NOME", "RASTREIO"]
    )
    assert rastreios_da_planilha(df) == {bom}
    assert nome_na_planilha("262", df) == "Ana Lima"
    assert nome_na_planilha("999", df) == ""
    from tracker import classificar_envio, extrair_apenas_numeros_rastreio
    assert extrair_apenas_numeros_rastreio(LINK_USPS + bom) == bom
    assert classificar_envio(TIPO_ENVIO_FOTO) == "CONSULADO_CLIENTE"
    print("ok")

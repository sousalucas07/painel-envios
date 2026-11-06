# Painel de envios (versão nova) na VPS

Roda **ao lado** do painel atual em Streamlit, sem mexer nele: usa a mesma planilha, a mesma
auditoria e as mesmas contas (Shippo, Bitrix, WhatCRM, Gemini). O rastreio automático continua
no GitHub Actions. Endereço: **https://envios.despa.digital**.

> Compras, exclusões e reembolsos feitos aqui são **reais** (mesma planilha e mesma Shippo do painel atual).

## 0. Antes de tudo
- DNS: `envios` → CNAME `srv1980091.hstgr.cloud.` (já criado; é a mesma VPS do cadastro, IP 2.25.75.249).
- Código no GitHub num branch separado (`portal-envios`), para o `main` e o Streamlit Cloud não mudarem.

## 1. Baixar o código (na VPS, como deploy)

    ssh deploy@srv1980091.hstgr.cloud
    git clone --branch portal-envios https://github.com/sousalucas07/painel-envios.git /opt/envios

(Se o repositório virar privado: use uma deploy key só de leitura, como no cadastro.)

## 2. Chaves (secrets.toml)

    cd /opt/envios/portal_envios
    cp secrets.exemplo.toml secrets.toml
    nano secrets.toml

Cole o conteúdo de **Settings → Secrets** do app no Streamlit Cloud e acrescente, no topo:

    PORTAL_ENVIOS_SEGREDO = "<saída de: openssl rand -hex 32>"
    PORTAL_ENVIOS_SENHA = ""   # vazio = usa a mesma senha do painel atual (DASHBOARD_SENHA)

Depois:

    chmod 600 secrets.toml
    sudo chown 1000 secrets.toml   # o container roda como usuário 1000

O `secrets.toml` nunca vai para o git (está no `.gitignore` desta pasta) nem para a imagem.

## 3. Subir

    docker network ls | grep econsular     # confira o nome da rede do cadastro (padrão: econsular_default)
    docker compose up -d --build
    docker compose logs -f envios          # deve aparecer "Uvicorn running on http://0.0.0.0:8080"

Se a rede tiver outro nome: `REDE_CADASTRO=<nome> docker compose up -d --build`.

## 4. HTTPS (Caddy do cadastro)
Cole o conteúdo de `Caddyfile.envios` no fim de `/opt/econsular/Caddyfile` e recarregue:

    docker exec econsular-caddy-1 caddy reload --config /etc/caddy/Caddyfile

## 5. Atualizar depois

    cd /opt/envios && git pull && cd portal_envios && docker compose up -d --build

## 6. Testes antes de liberar para a equipe
1. Login: senha certa, senha errada, bloqueio depois de 5 erradas (15 min), Sair.
2. Acompanhamento: totais iguais aos do painel atual; busca por pedido e por nome; links de tarefa e USPS.
3. Excluir: cadastre uma linha falsa num pedido com 2 linhas e confira que sai a certa.
4. Imprimir: reimprima uma etiqueta recente e imprima em 100%.
5. Emitir: compre **1** etiqueta, confira painel + auditoria + PDF e **reembolse** essa mesma etiqueta.
6. Rastreio antigo: IDA + RETORNO e Cli - Con / Con - Cli falsos (2 linhas cada); depois exclua.
7. Foto dos selos: a mesma foto nos dois painéis deve dar a mesma conferência.
8. Celular e duas pessoas usando ao mesmo tempo.

## Rodar no computador (teste local)

    cd painel-envios        # raiz do repositório, com .env e credentials.json
    COOKIE_SEGURO=0 PORT=8090 python3 portal_envios/app.py

Abra http://127.0.0.1:8090 (usa as mesmas chaves do `.env`; compras e exclusões também são reais).

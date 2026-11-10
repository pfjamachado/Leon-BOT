# Leon BOT — versão 5.2

Bot de RPG para Discord, em Python. Contém módulos de personagens, economia e C.U., loja, catálogo de itens, painel administrativo e moderação.

## Requisitos

- Python 3.11 ou superior (arquivos originais gerados em Python 3.13)
- Biblioteca `discord.py` (veja `requirements.txt`)
- Bot do Discord com os intents necessários habilitados (Message Content e Server Members)

## Instalação

1. Instale dependências: `python -m pip install -r requirements.txt`.
2. **Revogue/regere o token que estava no ZIP original** no Discord Developer Portal. Não reutilize esse token.
3. Configure a variável de ambiente `DISCORD_TOKEN` com o novo token (pode usar as variáveis da sua hospedagem ou um arquivo `.env` carregado pelo ambiente de execução). O programa **não carrega `.env` automaticamente**.
4. Ajuste as constantes `ID_CANAL_LOJA`, `ID_MENSAGEM_LOJA` e `ID_CANAL_CU` em `bot_leon.py` se o bot for usado em outro servidor.
5. Inicie com `python bot_leon.py`.

Exemplo Linux/macOS (shell):

```bash
export DISCORD_TOKEN='SEU_NOVO_TOKEN'
python bot_leon.py
```

Exemplo PowerShell:

```powershell
$env:DISCORD_TOKEN = 'SEU_NOVO_TOKEN'
python bot_leon.py
```

## Dados de jogadores e persistência

Os arquivos `banco_de_dados.json` e `personagens.json` possuem registros de jogadores (saldos, fichas etc.) e **não foram incluídos no pacote preparado para GitHub**. Eles existem no ZIP original enviado e devem ser copiados de volta ao diretório do bot na hospedagem, se você deseja preservar a campanha. Faça backup antes de qualquer substituição.

Os módulos carregam dicionários vazios quando os arquivos não existem e podem criá-los quando salvam os dados. **Iniciar sem os arquivos originais não restaura os jogadores existentes**.

Os arquivos `loja.json` e `catalogo_itens.json` foram mantidos como conteúdo de configuração do jogo.

## Atenção

- Não comite tokens e senhas; o código lê `DISCORD_TOKEN` do ambiente.
- Não comite bancos de dados dos jogadores. Use backup privado separado do histórico do código.
- O projeto foi validado por compilação estática; o funcionamento no Discord não foi testado com credenciais.

## Hospedagem 24h no Railway

1. Conecte o repositório GitHub ao Railway e crie um serviço a partir dele.
2. No serviço, em **Variables**, defina `DISCORD_TOKEN` com um **novo** token do bot. Nunca o comite.
3. Crie um **Volume** ligado ao serviço e monte em `/app/data`. O Leon detecta `RAILWAY_VOLUME_MOUNT_PATH` automaticamente e salva nele `banco_de_dados.json` e `personagens.json`.
4. Antes da primeira execução, envie os dois JSONs originais do ZIP para `/app/data` para manter fichas, saldos e históricos. Na ausência desses arquivos, o Leon começa um banco vazio.
5. Execute somente **uma réplica** do serviço e não mantenha outra instância do Leon ativa com o mesmo token.
6. O `Dockerfile` e `railway.json` estão prontos para construir e iniciar o bot continuamente. Sem volume, dados escritos no container são temporários.

O Leon **não expõe servidor HTTP** e deve ser tratado como processo/worker de longa duração.
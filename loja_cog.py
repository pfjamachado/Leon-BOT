# -*- coding: utf-8 -*-
import asyncio
import datetime
import json
import os
import math
import re
from collections import Counter
from typing import Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands, tasks


DIRETORIO_DADOS = os.environ.get("LEON_DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "."
ARQUIVO_BANCO = os.path.join(DIRETORIO_DADOS, "banco_de_dados.json")
ARQUIVO_LOJA = "loja.json"
ARQUIVO_CATALOGO = "catalogo_itens.json"
try:
    FUSO_LOJA = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    # Windows pode não ter a base IANA instalada. UTC-3 mantém as regras
    # de data da loja funcionando sem impedir o carregamento do cog.
    FUSO_LOJA = datetime.timezone(datetime.timedelta(hours=-3))


def carregar_dados(arquivo):
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"ERRO AO CARREGAR O FICHEIRO '{arquivo}': {e}")
        return {}


def salvar_json(arquivo, dados):
    os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)


def salvar_dados_jogadores():
    salvar_json(ARQUIVO_BANCO, dados_jogadores)


def salvar_loja():
    salvar_json(ARQUIVO_LOJA, loja_data)


def salvar_catalogo():
    salvar_json(ARQUIVO_CATALOGO, catalogo_itens_completo)


def recarregar_loja_e_catalogo():
    global loja_data, catalogo_itens_completo
    loja_data = carregar_dados(ARQUIVO_LOJA)
    catalogo_itens_completo = carregar_dados(ARQUIVO_CATALOGO)


dados_jogadores = carregar_dados(ARQUIVO_BANCO)
loja_data = carregar_dados(ARQUIVO_LOJA)
catalogo_itens_completo = carregar_dados(ARQUIVO_CATALOGO)


def get_dados_jogador(user_id):
    """Migração compatível: nunca apaga saldo, itens ou tópico existentes."""
    user_id_str = str(user_id)
    if user_id_str not in dados_jogadores:
        dados_jogadores[user_id_str] = {
            "saldo": 0,
            "cu": [],
            "id_topico_cu": None,
            "id_mensagem_cu": None,
            "compras_loja": {},
            "historico": [],
        }
    else:
        dados = dados_jogadores[user_id_str]
        dados.setdefault("saldo", 0)
        dados.setdefault("cu", [])
        dados.setdefault("id_topico_cu", None)
        dados.setdefault("id_mensagem_cu", None)
        dados.setdefault("compras_loja", {})
        dados.setdefault("historico", [])
    return dados_jogadores[user_id_str]


def hoje_loja():
    return datetime.datetime.now(FUSO_LOJA).date()


def agora_loja():
    return datetime.datetime.now(FUSO_LOJA)


def registrar_historico(dados_jogador, tipo, **campos):
    """Registra movimentações sem poluir os tópicos do C.U."""
    historico = dados_jogador.setdefault("historico", [])
    registro = {
        "tipo": tipo,
        "data": agora_loja().isoformat(timespec="seconds"),
        **campos,
    }
    historico.append(registro)
    # Evita crescimento ilimitado do JSON, preservando as 500 movimentações mais recentes.
    if len(historico) > 500:
        del historico[:-500]
    return registro


def formatar_data_historico(valor):
    try:
        dt = datetime.datetime.fromisoformat(valor)
        return dt.strftime("%d/%m/%Y • %H:%M")
    except (TypeError, ValueError):
        return str(valor or "Data desconhecida")


def descricao_registro_historico(registro):
    tipo = registro.get("tipo", "desconhecido")
    qtd = int(registro.get("quantidade", 0) or 0)
    item_id = registro.get("item_id")
    item = find_item_by_id(item_id) if item_id else None
    nome_item = item.get("nome", item_id) if item else item_id
    motivo = (registro.get("motivo") or "").strip()
    valor_lc = int(registro.get("valor_lc", 0) or 0)

    if tipo == "compra":
        texto = f"🛒 **{valor_lc} LC** • Comprou **{qtd}x {nome_item}**"
    elif tipo == "uso_item":
        texto = f"🎒 Usou **{qtd}x {nome_item}**"
    elif tipo == "lc_admin_add":
        texto = f"💰 **+{qtd} LC**"
    elif tipo == "lc_admin_remove":
        texto = f"💸 **-{qtd} LC**"
    elif tipo == "item_admin_add":
        texto = f"🎁 Recebeu **{qtd}x {nome_item}**"
    elif tipo == "item_admin_remove":
        texto = f"🗑️ Foram removidos **{qtd}x {nome_item}**"
    else:
        texto = f"• {tipo}"

    if motivo:
        texto += f"\nMotivo: {motivo}"
    return texto


def criar_embed_extrato(bot, usuario, pagina=0, por_pagina=8, admin=False):
    dados = get_dados_jogador(usuario.id)
    registros = list(reversed(dados.get("historico", [])))
    total_paginas = max(1, math.ceil(len(registros) / por_pagina))
    pagina = min(max(0, pagina), total_paginas - 1)
    inicio = pagina * por_pagina
    fatia = registros[inicio:inicio + por_pagina]

    embed = discord.Embed(
        title=f"📜 Extrato de {usuario.display_name}",
        description=f"Saldo atual: **{dados.get('saldo', 0)} {bot.config['nome_moeda_plural']}**",
        color=discord.Color.gold(),
    )
    if not fatia:
        embed.add_field(name="Histórico", value="Ainda não há movimentações registradas na versão 3.2.", inline=False)
    else:
        for registro in fatia:
            titulo = formatar_data_historico(registro.get("data"))
            texto = descricao_registro_historico(registro)
            if admin and registro.get("admin_id"):
                texto += f"\nAdministrador: <@{registro['admin_id']}>"
            embed.add_field(name=titulo, value=texto[:1024], inline=False)
    embed.set_footer(text=f"Página {pagina + 1}/{total_paginas} • Histórico começa a ser registrado na v3.2")
    return embed, total_paginas


def parse_data(texto):
    texto = (texto or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise ValueError("Use DD/MM/AAAA ou AAAA-MM-DD.")


def data_iso(texto):
    data = parse_data(texto)
    return data.isoformat() if data else None


def formatar_data(valor):
    if not valor:
        return None
    try:
        return datetime.date.fromisoformat(valor).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(valor)


def normalizar_categoria(nome):
    nome = (nome or "").strip().lower()
    nome = re.sub(r"\s+", "_", nome)
    return nome


def normalizar_item_id(item_id):
    item_id = (item_id or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]+", item_id):
        raise ValueError("O ID só pode ter letras sem acento, números e _. Ex.: bencaodezico")
    return item_id


def parse_inteiro_opcional(texto, nome_campo, permitir_zero=False):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        valor = int(texto)
    except ValueError:
        raise ValueError(f"{nome_campo} precisa ser um número inteiro.")
    minimo = 0 if permitir_zero else 1
    if valor < minimo:
        raise ValueError(f"{nome_campo} precisa ser pelo menos {minimo}.")
    return valor


def localizar_venda(item_id):
    for categoria, itens in loja_data.items():
        if isinstance(itens, dict) and item_id in itens:
            return categoria, itens[item_id]
    return None, None


def definir_venda(item_id, categoria, venda):
    categoria = normalizar_categoria(categoria)
    if not categoria:
        raise ValueError("A categoria não pode ficar vazia.")

    for cat in list(loja_data.keys()):
        itens = loja_data.get(cat)
        if isinstance(itens, dict):
            itens.pop(item_id, None)
            if not itens:
                # Mantemos categorias antigas vazias; isso evita reorganizações inesperadas.
                pass

    loja_data.setdefault(categoria, {})[item_id] = venda


def retirar_da_loja(item_id):
    removido = False
    for itens in loja_data.values():
        if isinstance(itens, dict) and item_id in itens:
            del itens[item_id]
            removido = True
    return removido


def get_item_catalogo(item_id):
    return catalogo_itens_completo.get(item_id)


def find_item_by_id(item_id):
    """Catálogo é a fonte oficial; dados comerciais da loja são apenas complementares."""
    catalogo = get_item_catalogo(item_id) or {}
    _, venda = localizar_venda(item_id)
    venda = venda or {}

    if not catalogo and not venda:
        return None

    # Catálogo vence em nome/descrição/emoji caso um loja.json legado repita esses campos.
    return {**venda, **catalogo}


def venda_ativa_por_data(venda, data=None):
    data = data or hoje_loja()
    inicio = parse_data(venda.get("data_inicio")) if venda.get("data_inicio") else None
    fim = parse_data(venda.get("data_fim")) if venda.get("data_fim") else None
    if inicio and data < inicio:
        return False
    if fim and data > fim:
        return False
    return True


def chave_oferta(item_id, venda):
    """O limite individual reinicia automaticamente quando as datas da oferta mudam."""
    inicio = venda.get("data_inicio") or "sem_inicio"
    fim = venda.get("data_fim") or "sem_fim"
    return f"{item_id}|{inicio}|{fim}"


def compras_na_oferta(dados_jogador, item_id, venda):
    return int(dados_jogador.get("compras_loja", {}).get(chave_oferta(item_id, venda), 0))


def registrar_compra_na_oferta(dados_jogador, item_id, venda, quantidade=1):
    compras = dados_jogador.setdefault("compras_loja", {})
    chave = chave_oferta(item_id, venda)
    compras[chave] = int(compras.get(chave, 0)) + quantidade


def limite_restante_jogador(dados_jogador, item_id, venda):
    limite = venda.get("limite_por_jogador")
    if limite is None:
        return None
    return max(0, int(limite) - compras_na_oferta(dados_jogador, item_id, venda))


def estoque_restante(venda):
    valor = venda.get("estoque_restante")
    return None if valor is None else int(valor)


def itens_da_categoria_visiveis(categoria):
    itens = loja_data.get(categoria, {})
    if not isinstance(itens, dict):
        return []
    return [
        (item_id, venda)
        for item_id, venda in itens.items()
        if isinstance(venda, dict) and venda_ativa_por_data(venda)
    ]


def nome_categoria(categoria):
    return (categoria or "").replace("_", " ").title()


def usuario_tem_cargo_admin(bot, usuario, guild):
    if not guild:
        return False
    if usuario.id == guild.owner_id:
        return True
    admin_roles = bot.config.get("cargos_admin", [])
    nomes = [role.name for role in getattr(usuario, "roles", [])]
    return any(nome in nomes for nome in admin_roles)


def is_admin():
    async def predicate(ctx):
        return usuario_tem_cargo_admin(ctx.bot, ctx.author, ctx.guild)
    return commands.check(predicate)


def extrair_user_id(texto):
    numeros = re.sub(r"\D", "", texto or "")
    if not numeros:
        raise ValueError("Informe um ID ou uma @menção válida.")
    return int(numeros)


async def resolver_membro(interaction, texto):
    user_id = extrair_user_id(texto)
    membro = interaction.guild.get_member(user_id) if interaction.guild else None
    if membro is None and interaction.guild:
        try:
            membro = await interaction.guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            membro = None
    if membro is None:
        raise ValueError("Não encontrei esse membro neste servidor.")
    return membro


async def atualizar_mensagem_loja(bot):
    config = bot.config
    canal_id = config.get("id_canal_loja")
    mensagem_id = config.get("id_mensagem_loja")
    if not canal_id or not mensagem_id:
        return False

    try:
        canal = bot.get_channel(canal_id) or await bot.fetch_channel(canal_id)
        mensagem = await canal.fetch_message(mensagem_id)
        view = ShopView(bot)
        await mensagem.edit(embed=view.criar_embed_pagina_atual(), view=view)
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        print(f"Não foi possível atualizar a mensagem da loja: {e}")
        return False


# -----------------------------------------------------------------------------
# C.U. INTERATIVO
# -----------------------------------------------------------------------------

def criar_embed_cu(bot: commands.Bot, usuario, dados=None):
    dados = dados or get_dados_jogador(usuario.id)
    lista_cu = dados.get("cu", [])
    moeda = bot.config["nome_moeda_plural"]

    embed = discord.Embed(
        title=f"🎒 C.U. de {usuario.display_name}",
        color=discord.Color.dark_green(),
    )
    embed.description = f"**Saldo:** {dados.get('saldo', 0)} {moeda}"

    if not lista_cu:
        embed.add_field(name="Inventário", value="Vazio.", inline=False)
    else:
        contagem = Counter(lista_cu)
        itens_ordenados = []
        for item_id, qtd in contagem.items():
            item = find_item_by_id(item_id)
            nome = item.get("nome", item_id) if item else item_id
            itens_ordenados.append((nome.lower(), item_id, qtd, item))

        for _, item_id, qtd, item in sorted(itens_ordenados):
            if item:
                emoji = item.get("emoji", "")
                nome = item.get("nome", item_id)
                descricao = item.get("descricao", "-")
                titulo = f"{emoji} {nome} — x{qtd}".strip()
            else:
                titulo = f"{item_id} — x{qtd}"
                descricao = "Item não encontrado no catálogo."
            embed.add_field(name=titulo, value=descricao, inline=False)

    embed.set_footer(text="Use o botão abaixo para gastar itens sem precisar digitar IDs.")
    return embed


def buscar_dono_por_topico(thread_id):
    for user_id, dados in dados_jogadores.items():
        if dados.get("id_topico_cu") == thread_id:
            return int(user_id), dados
    return None, None


async def criar_ou_obter_topico_cu(bot: commands.Bot, usuario):
    dados = get_dados_jogador(usuario.id)
    thread_cu = None

    if dados.get("id_topico_cu"):
        try:
            thread_cu = await bot.fetch_channel(dados["id_topico_cu"])
        except (discord.NotFound, discord.Forbidden):
            dados["id_topico_cu"] = None
            dados["id_mensagem_cu"] = None
            salvar_dados_jogadores()

    if not thread_cu:
        canal_id = bot.config.get("id_canal_cu", 0)
        canal_cu_principal = bot.get_channel(canal_id) or await bot.fetch_channel(canal_id)
        thread_cu = await canal_cu_principal.create_thread(
            name=f"C.U de {usuario.display_name}",
            type=discord.ChannelType.private_thread,
        )
        dados["id_topico_cu"] = thread_cu.id
        dados["id_mensagem_cu"] = None
        salvar_dados_jogadores()

    try:
        await thread_cu.add_user(usuario)
    except discord.HTTPException:
        pass

    return thread_cu, dados


async def garantir_painel_cu(bot: commands.Bot, usuario, thread_cu=None):
    if thread_cu is None:
        thread_cu, dados = await criar_ou_obter_topico_cu(bot, usuario)
    else:
        dados = get_dados_jogador(usuario.id)

    mensagem_painel = None
    mensagem_id = dados.get("id_mensagem_cu")
    if mensagem_id:
        try:
            mensagem_painel = await thread_cu.fetch_message(mensagem_id)
        except (discord.NotFound, discord.Forbidden):
            dados["id_mensagem_cu"] = None

    view = CUThreadView(bot)
    embed = criar_embed_cu(bot, usuario, dados)

    if mensagem_painel:
        await mensagem_painel.edit(embed=embed, view=view)
    else:
        mensagem_painel = await thread_cu.send(embed=embed, view=view)
        dados["id_mensagem_cu"] = mensagem_painel.id

    salvar_dados_jogadores()
    return mensagem_painel


async def atualizar_painel_existente(bot: commands.Bot, usuario):
    dados = get_dados_jogador(usuario.id)
    if not dados.get("id_topico_cu") or not dados.get("id_mensagem_cu"):
        return
    try:
        thread_cu = await bot.fetch_channel(dados["id_topico_cu"])
        mensagem = await thread_cu.fetch_message(dados["id_mensagem_cu"])
        await mensagem.edit(embed=criar_embed_cu(bot, usuario, dados), view=CUThreadView(bot))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        dados["id_mensagem_cu"] = None
        salvar_dados_jogadores()


class ConfirmarUsoView(discord.ui.View):
    def __init__(self, bot, usuario, item_id, quantidade, mensagem_painel):
        super().__init__(timeout=120)
        self.bot = bot
        self.usuario = usuario
        self.item_id = item_id
        self.quantidade = quantidade
        self.mensagem_painel = mensagem_painel

    async def interaction_check(self, interaction):
        if interaction.user.id != self.usuario.id:
            await interaction.response.send_message("Este menu pertence a outro jogador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar uso", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirmar(self, interaction, button):
        dados = get_dados_jogador(self.usuario.id)
        disponivel = dados["cu"].count(self.item_id)
        if disponivel < self.quantidade:
            return await interaction.response.edit_message(
                content="Seu inventário mudou e você não possui mais essa quantidade.", embed=None, view=None
            )

        for _ in range(self.quantidade):
            dados["cu"].remove(self.item_id)
        registrar_historico(
            dados,
            "uso_item",
            item_id=self.item_id,
            quantidade=self.quantidade,
        )
        salvar_dados_jogadores()

        item_info = find_item_by_id(self.item_id)
        nome_item = item_info.get("nome", self.item_id) if item_info else self.item_id
        restante = dados["cu"].count(self.item_id)

        try:
            await self.mensagem_painel.edit(
                embed=criar_embed_cu(self.bot, self.usuario, dados), view=CUThreadView(self.bot)
            )
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title="✅ Item utilizado",
            description=f"Você usou **{self.quantidade}x {nome_item}**.",
            color=discord.Color.green(),
        )
        if item_info and item_info.get("descricao"):
            embed.add_field(name="Efeito", value=item_info["descricao"], inline=False)
        embed.add_field(name="Restantes", value=str(restante))
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancelar(self, interaction, button):
        await interaction.response.edit_message(content="Uso cancelado.", embed=None, view=None)


class QuantidadeUsoView(discord.ui.View):
    def __init__(self, bot, usuario, item_id, mensagem_painel):
        super().__init__(timeout=120)
        self.bot = bot
        self.usuario = usuario
        self.item_id = item_id
        self.mensagem_painel = mensagem_painel
        quantidade_disponivel = get_dados_jogador(usuario.id)["cu"].count(item_id)

        for quantidade in (1, 2, 3, 5):
            botao = discord.ui.Button(
                label=str(quantidade),
                style=discord.ButtonStyle.primary,
                disabled=quantidade > quantidade_disponivel,
                row=0,
            )

            async def quantidade_callback(interaction, q=quantidade):
                await self.escolher_quantidade(interaction, q)

            botao.callback = quantidade_callback
            self.add_item(botao)

        botao_todos = discord.ui.Button(
            label="Todos",
            style=discord.ButtonStyle.primary,
            disabled=quantidade_disponivel <= 0,
            row=0,
        )

        async def todos_callback(interaction):
            atual = get_dados_jogador(self.usuario.id)["cu"].count(self.item_id)
            await self.escolher_quantidade(interaction, atual)

        botao_todos.callback = todos_callback
        self.add_item(botao_todos)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.usuario.id:
            await interaction.response.send_message("Este menu pertence a outro jogador.", ephemeral=True)
            return False
        return True

    async def escolher_quantidade(self, interaction, quantidade):
        if quantidade <= 0:
            return await interaction.response.edit_message(content="Você não possui mais esse item.", embed=None, view=None)

        dados = get_dados_jogador(self.usuario.id)
        disponivel = dados["cu"].count(self.item_id)
        if disponivel < quantidade:
            return await interaction.response.edit_message(content="Você não possui mais essa quantidade.", embed=None, view=None)

        item = find_item_by_id(self.item_id)
        nome = item.get("nome", self.item_id) if item else self.item_id
        emoji = item.get("emoji", "") if item else ""
        embed = discord.Embed(
            title=f"Confirmar uso — {emoji} {nome}".strip(),
            description=f"Usar **{quantidade}x {nome}**?",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Você possui", value=str(disponivel), inline=True)
        embed.add_field(name="Restará", value=str(disponivel - quantidade), inline=True)
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=ConfirmarUsoView(self.bot, self.usuario, self.item_id, quantidade, self.mensagem_painel),
        )


class ItemSelect(discord.ui.Select):
    def __init__(self, bot, usuario, mensagem_painel):
        self.bot = bot
        self.usuario = usuario
        self.mensagem_painel = mensagem_painel
        contagem = Counter(get_dados_jogador(usuario.id).get("cu", []))
        options = []

        ordenados = []
        for item_id, qtd in contagem.items():
            item = find_item_by_id(item_id)
            nome = item.get("nome", item_id) if item else item_id
            ordenados.append((nome.lower(), item_id, qtd, item))

        for _, item_id, qtd, item in sorted(ordenados)[:25]:
            nome = item.get("nome", item_id) if item else item_id
            descricao = item.get("descricao", "") if item else ""
            emoji = item.get("emoji") if item else None
            options.append(
                discord.SelectOption(
                    label=f"{nome} (x{qtd})"[:100],
                    value=item_id,
                    description=descricao[:100] if descricao else None,
                    emoji=emoji or None,
                )
            )

        super().__init__(placeholder="Escolha o item que deseja usar...", options=options)

    async def callback(self, interaction):
        item_id = self.values[0]
        dados = get_dados_jogador(self.usuario.id)
        quantidade = dados["cu"].count(item_id)
        if quantidade <= 0:
            return await interaction.response.edit_message(content="Esse item não está mais no seu C.U.", embed=None, view=None)

        item = find_item_by_id(item_id)
        nome = item.get("nome", item_id) if item else item_id
        descricao = item.get("descricao", "-") if item else "-"
        emoji = item.get("emoji", "") if item else ""
        embed = discord.Embed(title=f"{emoji} {nome}".strip(), description=descricao, color=discord.Color.blurple())
        embed.add_field(name="Você possui", value=str(quantidade), inline=False)
        embed.set_footer(text="Quantos você deseja usar?")
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=QuantidadeUsoView(self.bot, self.usuario, item_id, self.mensagem_painel),
        )


class ItemSelectView(discord.ui.View):
    def __init__(self, bot, usuario, mensagem_painel):
        super().__init__(timeout=120)
        self.usuario = usuario
        self.add_item(ItemSelect(bot, usuario, mensagem_painel))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.usuario.id:
            await interaction.response.send_message("Este menu pertence a outro jogador.", ephemeral=True)
            return False
        return True


class CUThreadView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def resolver_usuario(self, interaction):
        user_id, dados = buscar_dono_por_topico(interaction.channel_id)
        if not user_id or interaction.user.id != user_id:
            return None, dados
        return interaction.user, dados

    @discord.ui.button(label="Usar item", style=discord.ButtonStyle.success, emoji="🎒", custom_id="leon_cu_usar_item")
    async def usar_item(self, interaction, button):
        usuario, dados = await self.resolver_usuario(interaction)
        if not usuario:
            return await interaction.response.send_message("Somente o dono deste C.U. pode gastar os itens daqui.", ephemeral=True)
        if not dados.get("cu"):
            return await interaction.response.send_message("Seu C.U. está vazio.", ephemeral=True)
        await interaction.response.send_message(
            embed=discord.Embed(title="Usar item", description="Escolha abaixo qual item você quer gastar.", color=discord.Color.blurple()),
            view=ItemSelectView(self.bot, usuario, interaction.message),
            ephemeral=True,
        )

    @discord.ui.button(label="Extrato", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="leon_cu_extrato")
    async def extrato(self, interaction, button):
        usuario, dados = await self.resolver_usuario(interaction)
        if not usuario:
            return await interaction.response.send_message("Somente o dono deste C.U. pode abrir este extrato.", ephemeral=True)
        embed, _ = criar_embed_extrato(self.bot, usuario, 0, admin=False)
        await interaction.response.send_message(
            embed=embed,
            view=ExtratoView(self.bot, usuario, pagina=0, admin=False),
            ephemeral=True,
        )

    @discord.ui.button(label="Atualizar", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="leon_cu_atualizar")
    async def atualizar(self, interaction, button):
        usuario, dados = await self.resolver_usuario(interaction)
        if not usuario:
            return await interaction.response.send_message("Somente o dono deste C.U. pode atualizar este painel.", ephemeral=True)
        await interaction.response.edit_message(embed=criar_embed_cu(self.bot, usuario, dados), view=self)


# -----------------------------------------------------------------------------
# LOJA
# -----------------------------------------------------------------------------

class ShopView(discord.ui.View):
    def __init__(self, bot, categoria_atual=None, pagina_atual=0):
        super().__init__(timeout=None)
        self.bot = bot
        self.items_por_pagina = 4
        self.categorias = [k for k, v in loja_data.items() if isinstance(v, dict)]
        self.categoria_atual = categoria_atual if categoria_atual in self.categorias else (self.categorias[0] if self.categorias else None)
        self.pagina_atual = pagina_atual
        self.atualizar_view()

    def itens_atuais(self):
        return itens_da_categoria_visiveis(self.categoria_atual)

    def criar_embed_pagina_atual(self):
        moeda = self.bot.config["nome_moeda_plural"]
        embed = discord.Embed(title=f"Loja - {nome_categoria(self.categoria_atual) or 'Vazia'}", color=discord.Color.teal())
        itens = self.itens_atuais()
        self.total_paginas = max(1, math.ceil(len(itens) / self.items_por_pagina))
        self.pagina_atual = min(max(0, self.pagina_atual), self.total_paginas - 1)
        inicio = self.pagina_atual * self.items_por_pagina
        pagina = itens[inicio:inicio + self.items_por_pagina]

        if not pagina:
            embed.description = "Nenhum item disponível nesta categoria agora."
        else:
            for item_id, venda in pagina:
                item = find_item_by_id(item_id) or {}
                nome = item.get("nome", item_id)
                descricao = item.get("descricao", "Sem descrição.")
                emoji = item.get("emoji", "")
                preco = venda.get("preco", "??")
                extras = []
                if venda.get("limite_por_jogador") is not None:
                    extras.append(f"Limite: {venda['limite_por_jogador']} por jogador")
                if venda.get("estoque_restante") is not None:
                    extras.append(f"Estoque: {venda['estoque_restante']}")
                if venda.get("data_fim"):
                    extras.append(f"Até {formatar_data(venda['data_fim'])}")
                texto = descricao
                if extras:
                    texto += "\n**" + " • ".join(extras) + "**"
                embed.add_field(name=f"{emoji} {nome} — {preco} {moeda}".strip(), value=texto, inline=False)

        embed.set_footer(text=f"Página {self.pagina_atual + 1} de {self.total_paginas}")
        return embed

    def atualizar_view(self):
        self.clear_items()
        for categoria in self.categorias:
            botao = discord.ui.Button(
                label=nome_categoria(categoria)[:80],
                style=discord.ButtonStyle.primary if categoria == self.categoria_atual else discord.ButtonStyle.secondary,
                custom_id=f"cat_{categoria}"[:100],
            )
            botao.callback = self.categoria_callback
            self.add_item(botao)

        itens = self.itens_atuais()
        self.total_paginas = max(1, math.ceil(len(itens) / self.items_por_pagina))
        self.pagina_atual = min(max(0, self.pagina_atual), self.total_paginas - 1)
        inicio = self.pagina_atual * self.items_por_pagina
        pagina = itens[inicio:inicio + self.items_por_pagina]

        for item_id, venda in pagina:
            item = find_item_by_id(item_id) or {}
            nome = item.get("nome", item_id)
            esgotado = venda.get("estoque_restante") is not None and int(venda.get("estoque_restante", 0)) <= 0
            botao = discord.ui.Button(
                label=(f"Esgotado — {nome}" if esgotado else f"Comprar {nome}")[:80],
                style=discord.ButtonStyle.secondary if esgotado else discord.ButtonStyle.success,
                custom_id=f"buy_{item_id}"[:100],
                disabled=esgotado,
                row=1,
            )
            botao.callback = self.compra_callback
            self.add_item(botao)

        if self.total_paginas > 1:
            anterior = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, custom_id="pagina_anterior", disabled=self.pagina_atual == 0, row=2)
            pagina_label = discord.ui.Button(label=f"{self.pagina_atual + 1}/{self.total_paginas}", style=discord.ButtonStyle.secondary, disabled=True, custom_id="label_pagina", row=2)
            proxima = discord.ui.Button(label="Próxima", style=discord.ButtonStyle.secondary, custom_id="pagina_proxima", disabled=self.pagina_atual >= self.total_paginas - 1, row=2)
            anterior.callback = self.navegacao_callback
            proxima.callback = self.navegacao_callback
            self.add_item(anterior)
            self.add_item(pagina_label)
            self.add_item(proxima)

    async def categoria_callback(self, interaction):
        # Não remova componentes de uma View já registrada no discord.py.
        # Isso deixa botões antigos no ViewStore apontando para view=None,
        # provocando "View interaction referencing unknown view".
        categoria = interaction.data["custom_id"][4:]
        if categoria not in self.categorias:
            return await interaction.response.send_message(
                "Esta categoria não está mais disponível. Atualize a loja.", ephemeral=True
            )
        nova_view = ShopView(self.bot, categoria_atual=categoria, pagina_atual=0)
        await interaction.response.edit_message(
            embed=nova_view.criar_embed_pagina_atual(), view=nova_view
        )

    async def navegacao_callback(self, interaction):
        deslocamento = 1 if interaction.data["custom_id"] == "pagina_proxima" else -1
        nova_view = ShopView(
            self.bot,
            categoria_atual=self.categoria_atual,
            pagina_atual=self.pagina_atual + deslocamento,
        )
        await interaction.response.edit_message(
            embed=nova_view.criar_embed_pagina_atual(), view=nova_view
        )

    async def compra_callback(self, interaction):
        item_id = interaction.data["custom_id"][4:]
        cog = self.bot.get_cog("Loja e Economia")
        lock = cog.compra_lock if cog else asyncio.Lock()

        async with lock:
            categoria, venda = localizar_venda(item_id)
            item = find_item_by_id(item_id)
            if not venda or not item:
                return await interaction.response.send_message("Esse item não está mais à venda.", ephemeral=True)
            if not venda_ativa_por_data(venda):
                return await interaction.response.send_message("A oferta deste item não está ativa no momento.", ephemeral=True)

            dados = get_dados_jogador(interaction.user.id)
            preco = int(venda.get("preco", 0))
            nome = item.get("nome", item_id)

            restante_limite = limite_restante_jogador(dados, item_id, venda)
            if restante_limite is not None and restante_limite <= 0:
                return await interaction.response.send_message(
                    f"Você já atingiu o limite de compras de **{nome}** nesta oferta.", ephemeral=True
                )

            estoque = estoque_restante(venda)
            if estoque is not None and estoque <= 0:
                return await interaction.response.send_message(f"**{nome}** está esgotado.", ephemeral=True)

            if dados["saldo"] < preco:
                return await interaction.response.send_message(
                    f"Saldo insuficiente. **{nome}** custa {preco} {self.bot.config['nome_moeda_plural']} e você possui {dados['saldo']}.",
                    ephemeral=True,
                )

            dados["saldo"] -= preco
            dados["cu"].append(item_id)
            registrar_compra_na_oferta(dados, item_id, venda)
            registrar_historico(
                dados,
                "compra",
                item_id=item_id,
                quantidade=1,
                valor_lc=-preco,
            )
            if estoque is not None:
                venda["estoque_restante"] = estoque - 1

            salvar_dados_jogadores()
            salvar_loja()

        restante_limite = limite_restante_jogador(dados, item_id, venda)
        linhas = [f"Compra realizada: **{nome}**.", f"Saldo restante: **{dados['saldo']} {self.bot.config['nome_moeda_plural']}**."]
        if restante_limite is not None:
            linhas.append(f"Você ainda pode comprar **{restante_limite}** nesta oferta.")
        if venda.get("estoque_restante") is not None:
            linhas.append(f"Estoque global restante: **{venda['estoque_restante']}**.")
        await interaction.response.send_message("\n".join(linhas), ephemeral=True)

        # Substitui a View por uma nova instância: não invalida os botões
        # registrados para esta mensagem ao atualizar o estoque.
        try:
            nova_view = ShopView(
                self.bot, categoria_atual=self.categoria_atual, pagina_atual=self.pagina_atual
            )
            await interaction.message.edit(
                embed=nova_view.criar_embed_pagina_atual(), view=nova_view
            )
        except discord.HTTPException:
            pass

        try:
            thread_cu, _ = await criar_ou_obter_topico_cu(self.bot, interaction.user)
            await garantir_painel_cu(self.bot, interaction.user, thread_cu)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"Erro ao atualizar C.U. de {interaction.user.id}: {e}")


# -----------------------------------------------------------------------------
# ADMINISTRAÇÃO POR INTERFACE
# -----------------------------------------------------------------------------

class AdminView(discord.ui.View):
    async def interaction_check(self, interaction):
        bot = getattr(self, "bot", None)
        if not bot or not usuario_tem_cargo_admin(bot, interaction.user, interaction.guild):
            await interaction.response.send_message("Você não tem permissão para usar este painel.", ephemeral=True)
            return False
        return True


class CriarItemBasicoModal(discord.ui.Modal, title="Criar item — 1/2"):
    item_id = discord.ui.TextInput(label="ID interno", placeholder="ex.: bencaodepele", max_length=60)
    nome = discord.ui.TextInput(label="Nome", max_length=100)
    descricao = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, max_length=1000)
    emoji = discord.ui.TextInput(label="Emoji", required=False, max_length=50)
    categoria = discord.ui.TextInput(label="Categoria da loja", placeholder="permanentes, mensais, bonus...", max_length=50)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction):
        try:
            item_id = normalizar_item_id(self.item_id.value)
            categoria = normalizar_categoria(self.categoria.value)
            if item_id in catalogo_itens_completo:
                raise ValueError("Já existe um item com esse ID.")
            if not categoria:
                raise ValueError("Informe uma categoria.")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        dados = {
            "item_id": item_id,
            "nome": self.nome.value.strip(),
            "descricao": self.descricao.value.strip(),
            "emoji": self.emoji.value.strip(),
            "categoria": categoria,
        }
        embed = discord.Embed(title="Novo item", description="Agora configure como ele será vendido.", color=discord.Color.blurple())
        embed.add_field(name="Item", value=f"{dados['emoji']} {dados['nome']} (`{item_id}`)".strip(), inline=False)
        embed.add_field(name="Categoria", value=nome_categoria(categoria), inline=False)
        await interaction.response.send_message(embed=embed, view=FinalizarNovoItemView(self.bot, dados), ephemeral=True)


class CriarVendaModal(discord.ui.Modal, title="Criar item — 2/2"):
    def __init__(self, bot, dados_basicos):
        super().__init__()
        self.bot = bot
        self.dados_basicos = dados_basicos
        self.preco = discord.ui.TextInput(label="Preço em LC", placeholder="2", max_length=10)
        self.limite = discord.ui.TextInput(label="Limite por jogador", placeholder="vazio = sem limite", required=False, max_length=10)
        self.estoque = discord.ui.TextInput(label="Estoque global", placeholder="vazio = infinito", required=False, max_length=10)
        self.inicio = discord.ui.TextInput(label="Data de início", placeholder="DD/MM/AAAA ou vazio = agora", required=False, max_length=10)
        self.fim = discord.ui.TextInput(label="Data final", placeholder="DD/MM/AAAA ou vazio = sem expiração", required=False, max_length=10)
        for campo in (self.preco, self.limite, self.estoque, self.inicio, self.fim):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            preco = parse_inteiro_opcional(self.preco.value, "Preço", permitir_zero=True)
            if preco is None:
                raise ValueError("Informe o preço.")
            limite = parse_inteiro_opcional(self.limite.value, "Limite por jogador")
            estoque = parse_inteiro_opcional(self.estoque.value, "Estoque global")
            inicio = data_iso(self.inicio.value)
            fim = data_iso(self.fim.value)
            if inicio and fim and datetime.date.fromisoformat(inicio) > datetime.date.fromisoformat(fim):
                raise ValueError("A data inicial não pode ser depois da data final.")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        d = self.dados_basicos
        catalogo_itens_completo[d["item_id"]] = {
            "nome": d["nome"],
            "descricao": d["descricao"],
            "emoji": d["emoji"],
        }
        venda = {
            "preco": preco,
            "limite_por_jogador": limite,
            "estoque_global": estoque,
            "estoque_restante": estoque,
            "data_inicio": inicio,
            "data_fim": fim,
        }
        definir_venda(d["item_id"], d["categoria"], venda)
        salvar_catalogo()
        salvar_loja()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message(f"✅ **{d['nome']}** criado e colocado na loja.", ephemeral=True)


class FinalizarNovoItemView(AdminView):
    def __init__(self, bot, dados_basicos):
        super().__init__(timeout=300)
        self.bot = bot
        self.dados_basicos = dados_basicos

    @discord.ui.button(label="Configurar venda", style=discord.ButtonStyle.success, emoji="🛒")
    async def configurar(self, interaction, button):
        await interaction.response.send_modal(CriarVendaModal(self.bot, self.dados_basicos))

    @discord.ui.button(label="Só adicionar ao catálogo", style=discord.ButtonStyle.secondary, emoji="📚")
    async def so_catalogo(self, interaction, button):
        d = self.dados_basicos
        catalogo_itens_completo[d["item_id"]] = {
            "nome": d["nome"],
            "descricao": d["descricao"],
            "emoji": d["emoji"],
        }
        salvar_catalogo()
        await interaction.response.edit_message(content=f"✅ **{d['nome']}** adicionado somente ao catálogo.", embed=None, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancelar(self, interaction, button):
        await interaction.response.edit_message(content="Criação cancelada.", embed=None, view=None)


def embed_admin_item(item_id):
    item = get_item_catalogo(item_id) or {}
    categoria, venda = localizar_venda(item_id)
    embed = discord.Embed(title=f"Gerenciar — {item.get('emoji', '')} {item.get('nome', item_id)}".strip(), color=discord.Color.dark_teal())
    embed.description = item.get("descricao", "Sem descrição.")
    embed.add_field(name="ID", value=f"`{item_id}`", inline=False)
    if venda:
        embed.add_field(name="Categoria", value=nome_categoria(categoria), inline=True)
        embed.add_field(name="Preço", value=f"{venda.get('preco', 0)} LC", inline=True)
        embed.add_field(name="Limite/jogador", value=str(venda.get("limite_por_jogador") or "Sem limite"), inline=True)
        estoque = venda.get("estoque_restante")
        total = venda.get("estoque_global")
        embed.add_field(name="Estoque", value="Infinito" if estoque is None else f"{estoque} / {total if total is not None else '?'}", inline=True)
        embed.add_field(name="Início", value=formatar_data(venda.get("data_inicio")) or "Agora", inline=True)
        embed.add_field(name="Fim", value=formatar_data(venda.get("data_fim")) or "Sem expiração", inline=True)
        embed.add_field(name="Status", value="Ativo" if venda_ativa_por_data(venda) else "Fora da janela de venda", inline=False)
    else:
        embed.add_field(name="Loja", value="Este item está somente no catálogo.", inline=False)
    return embed


class EditarCatalogoModal(discord.ui.Modal, title="Editar item"):
    def __init__(self, bot, item_id):
        super().__init__()
        self.bot = bot
        self.item_id = item_id
        item = get_item_catalogo(item_id) or {}
        self.nome = discord.ui.TextInput(label="Nome", default=item.get("nome", item_id), max_length=100)
        self.descricao = discord.ui.TextInput(label="Descrição", default=item.get("descricao", ""), style=discord.TextStyle.paragraph, max_length=1000)
        self.emoji = discord.ui.TextInput(label="Emoji", default=item.get("emoji", ""), required=False, max_length=50)
        for campo in (self.nome, self.descricao, self.emoji):
            self.add_item(campo)

    async def on_submit(self, interaction):
        catalogo_itens_completo[self.item_id] = {
            "nome": self.nome.value.strip(),
            "descricao": self.descricao.value.strip(),
            "emoji": self.emoji.value.strip(),
        }
        salvar_catalogo()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message("✅ Dados do item atualizados.", ephemeral=True)


class EditarVendaModal(discord.ui.Modal, title="Configurar venda"):
    def __init__(self, bot, item_id):
        super().__init__()
        self.bot = bot
        self.item_id = item_id
        categoria, venda = localizar_venda(item_id)
        venda = venda or {}
        self.categoria = discord.ui.TextInput(label="Categoria", default=categoria or "permanentes", max_length=50)
        self.preco = discord.ui.TextInput(label="Preço em LC", default=str(venda.get("preco", 0)), max_length=10)
        limite_atual = venda.get("limite_por_jogador")
        self.limite = discord.ui.TextInput(label="Limite por jogador", default="" if limite_atual is None else str(limite_atual), placeholder="vazio = sem limite", required=False, max_length=10)
        for campo in (self.categoria, self.preco, self.limite):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            categoria = normalizar_categoria(self.categoria.value)
            preco = parse_inteiro_opcional(self.preco.value, "Preço", permitir_zero=True)
            if preco is None:
                raise ValueError("Informe o preço.")
            limite = parse_inteiro_opcional(self.limite.value, "Limite por jogador")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        _, antiga = localizar_venda(self.item_id)
        antiga = antiga or {}
        venda = {
            "preco": preco,
            "limite_por_jogador": limite,
            "estoque_global": antiga.get("estoque_global"),
            "estoque_restante": antiga.get("estoque_restante"),
            "data_inicio": antiga.get("data_inicio"),
            "data_fim": antiga.get("data_fim"),
        }
        definir_venda(self.item_id, categoria, venda)
        salvar_loja()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message("✅ Configuração de venda atualizada.", ephemeral=True)


class EditarEstoqueModal(discord.ui.Modal, title="Editar estoque"):
    def __init__(self, bot, item_id):
        super().__init__()
        self.bot = bot
        self.item_id = item_id
        _, venda = localizar_venda(item_id)
        venda = venda or {}
        total = venda.get("estoque_global")
        restante = venda.get("estoque_restante")
        self.total = discord.ui.TextInput(label="Estoque global/máximo", default="" if total is None else str(total), placeholder="vazio = infinito", required=False, max_length=10)
        self.restante = discord.ui.TextInput(label="Estoque restante agora", default="" if restante is None else str(restante), placeholder="vazio = igual ao máximo", required=False, max_length=10)
        self.add_item(self.total)
        self.add_item(self.restante)

    async def on_submit(self, interaction):
        _, venda = localizar_venda(self.item_id)
        if not venda:
            return await interaction.response.send_message("Coloque o item na loja antes de configurar estoque.", ephemeral=True)
        try:
            total = parse_inteiro_opcional(self.total.value, "Estoque global")
            if total is None:
                restante = None
            else:
                restante = parse_inteiro_opcional(self.restante.value, "Estoque restante")
                if restante is None:
                    restante = total
                if restante > total:
                    raise ValueError("O estoque restante não pode ser maior que o estoque global.")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        venda["estoque_global"] = total
        venda["estoque_restante"] = restante
        salvar_loja()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message("✅ Estoque atualizado.", ephemeral=True)


class EditarDatasModal(discord.ui.Modal, title="Editar datas da oferta"):
    def __init__(self, bot, item_id):
        super().__init__()
        self.bot = bot
        self.item_id = item_id
        _, venda = localizar_venda(item_id)
        venda = venda or {}
        self.inicio = discord.ui.TextInput(label="Data de início", default=formatar_data(venda.get("data_inicio")) or "", placeholder="vazio = agora", required=False, max_length=10)
        self.fim = discord.ui.TextInput(label="Data final", default=formatar_data(venda.get("data_fim")) or "", placeholder="vazio = sem expiração", required=False, max_length=10)
        self.add_item(self.inicio)
        self.add_item(self.fim)

    async def on_submit(self, interaction):
        _, venda = localizar_venda(self.item_id)
        if not venda:
            return await interaction.response.send_message("Coloque o item na loja antes de configurar datas.", ephemeral=True)
        try:
            inicio = data_iso(self.inicio.value)
            fim = data_iso(self.fim.value)
            if inicio and fim and datetime.date.fromisoformat(inicio) > datetime.date.fromisoformat(fim):
                raise ValueError("A data inicial não pode ser depois da data final.")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        venda["data_inicio"] = inicio
        venda["data_fim"] = fim
        salvar_loja()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message("✅ Datas atualizadas. Alterar as datas também inicia um novo ciclo de limite individual.", ephemeral=True)


class ConfirmarRetiradaView(AdminView):
    def __init__(self, bot, item_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.item_id = item_id

    @discord.ui.button(label="Retirar da loja", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirmar(self, interaction, button):
        retirar_da_loja(self.item_id)
        salvar_loja()
        await atualizar_mensagem_loja(self.bot)
        await interaction.response.edit_message(content="✅ Item retirado da loja. Ele continua existindo no catálogo e nos C.U.s.", embed=None, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction, button):
        await interaction.response.edit_message(content="Cancelado.", embed=None, view=None)


class ItemAdminView(AdminView):
    def __init__(self, bot, item_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.item_id = item_id

    @discord.ui.button(label="Editar item", style=discord.ButtonStyle.primary, emoji="✏️")
    async def editar_item(self, interaction, button):
        await interaction.response.send_modal(EditarCatalogoModal(self.bot, self.item_id))

    @discord.ui.button(label="Venda", style=discord.ButtonStyle.success, emoji="🛒")
    async def venda(self, interaction, button):
        await interaction.response.send_modal(EditarVendaModal(self.bot, self.item_id))

    @discord.ui.button(label="Estoque", style=discord.ButtonStyle.secondary, emoji="📦")
    async def estoque(self, interaction, button):
        await interaction.response.send_modal(EditarEstoqueModal(self.bot, self.item_id))

    @discord.ui.button(label="Datas", style=discord.ButtonStyle.secondary, emoji="📅")
    async def datas(self, interaction, button):
        await interaction.response.send_modal(EditarDatasModal(self.bot, self.item_id))

    @discord.ui.button(label="Retirar da loja", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def retirar(self, interaction, button):
        if not localizar_venda(self.item_id)[1]:
            return await interaction.response.send_message("Esse item já está apenas no catálogo.", ephemeral=True)
        item = get_item_catalogo(self.item_id) or {}
        await interaction.response.send_message(
            f"Retirar **{item.get('nome', self.item_id)}** da loja? Isso não remove o item dos jogadores.",
            view=ConfirmarRetiradaView(self.bot, self.item_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Atualizar painel", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def atualizar(self, interaction, button):
        await interaction.response.edit_message(embed=embed_admin_item(self.item_id), view=self)


class CatalogoSelect(discord.ui.Select):
    def __init__(self, bot, pagina=0):
        self.bot = bot
        ids = sorted(catalogo_itens_completo.keys(), key=lambda i: catalogo_itens_completo[i].get("nome", i).lower())
        inicio = pagina * 25
        fatia = ids[inicio:inicio + 25]
        options = []
        for item_id in fatia:
            item = catalogo_itens_completo[item_id]
            options.append(discord.SelectOption(label=item.get("nome", item_id)[:100], value=item_id, description=item_id[:100], emoji=item.get("emoji") or None))
        super().__init__(placeholder="Escolha um item...", options=options or [discord.SelectOption(label="Catálogo vazio", value="__vazio__")])

    async def callback(self, interaction):
        item_id = self.values[0]
        if item_id == "__vazio__":
            return await interaction.response.send_message("O catálogo está vazio.", ephemeral=True)
        await interaction.response.edit_message(embed=embed_admin_item(item_id), view=ItemAdminView(self.bot, item_id))


class CatalogoSelectView(AdminView):
    def __init__(self, bot, pagina=0):
        super().__init__(timeout=300)
        self.bot = bot
        self.pagina = pagina
        total = len(catalogo_itens_completo)
        self.total_paginas = max(1, math.ceil(total / 25))
        self.add_item(CatalogoSelect(bot, pagina))

        anterior = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, disabled=pagina <= 0, row=1)
        proxima = discord.ui.Button(label="Próxima", style=discord.ButtonStyle.secondary, disabled=pagina >= self.total_paginas - 1, row=1)

        async def anterior_cb(interaction):
            await interaction.response.edit_message(content=f"Catálogo — página {self.pagina}/{self.total_paginas}", view=CatalogoSelectView(self.bot, self.pagina - 1))

        async def proxima_cb(interaction):
            await interaction.response.edit_message(content=f"Catálogo — página {self.pagina + 2}/{self.total_paginas}", view=CatalogoSelectView(self.bot, self.pagina + 1))

        anterior.callback = anterior_cb
        proxima.callback = proxima_cb
        self.add_item(anterior)
        self.add_item(proxima)


class ExtratoView(discord.ui.View):
    def __init__(self, bot, usuario, pagina=0, admin=False):
        super().__init__(timeout=300)
        self.bot = bot
        self.usuario = usuario
        self.pagina = pagina
        self.admin = admin
        _, total_paginas = criar_embed_extrato(bot, usuario, pagina, admin=admin)
        self.total_paginas = total_paginas

        anterior = discord.ui.Button(
            label="Anterior",
            style=discord.ButtonStyle.secondary,
            disabled=pagina <= 0,
        )
        proxima = discord.ui.Button(
            label="Próxima",
            style=discord.ButtonStyle.secondary,
            disabled=pagina >= total_paginas - 1,
        )

        async def anterior_cb(interaction):
            nova = max(0, self.pagina - 1)
            embed, _ = criar_embed_extrato(self.bot, self.usuario, nova, admin=self.admin)
            await interaction.response.edit_message(
                embed=embed,
                view=ExtratoView(self.bot, self.usuario, nova, self.admin),
            )

        async def proxima_cb(interaction):
            nova = min(self.total_paginas - 1, self.pagina + 1)
            embed, _ = criar_embed_extrato(self.bot, self.usuario, nova, admin=self.admin)
            await interaction.response.edit_message(
                embed=embed,
                view=ExtratoView(self.bot, self.usuario, nova, self.admin),
            )

        anterior.callback = anterior_cb
        proxima.callback = proxima_cb
        self.add_item(anterior)
        self.add_item(proxima)

    async def interaction_check(self, interaction):
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = interaction.user.id == self.usuario.id
        if not permitido:
            await interaction.response.send_message("Esse extrato não pertence a você.", ephemeral=True)
            return False
        return True


class AjustarSaldoSelecionadoModal(discord.ui.Modal):
    def __init__(self, bot, membro, adicionar=True):
        super().__init__(title=("Dar LC" if adicionar else "Remover LC") + f" — {membro.display_name}"[:20])
        self.bot = bot
        self.membro = membro
        self.adicionar = adicionar
        self.quantidade = discord.ui.TextInput(label="Quantidade", placeholder="5", max_length=10)
        self.motivo = discord.ui.TextInput(
            label="Motivo",
            placeholder="Ex.: Recompensa da sessão 12",
            style=discord.TextStyle.paragraph,
            max_length=300,
            required=True,
        )
        self.add_item(self.quantidade)
        self.add_item(self.motivo)

    async def on_submit(self, interaction):
        try:
            qtd = parse_inteiro_opcional(self.quantidade.value, "Quantidade")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        dados = get_dados_jogador(self.membro.id)
        motivo = self.motivo.value.strip()
        if self.adicionar:
            dados["saldo"] += qtd
            aplicado = qtd
            tipo = "lc_admin_add"
        else:
            aplicado = min(qtd, dados["saldo"])
            if aplicado <= 0:
                return await interaction.response.send_message(f"{self.membro.display_name} já está com 0 LC.", ephemeral=True)
            dados["saldo"] -= aplicado
            tipo = "lc_admin_remove"

        registrar_historico(
            dados,
            tipo,
            quantidade=aplicado,
            motivo=motivo,
            admin_id=interaction.user.id,
        )
        salvar_dados_jogadores()
        await atualizar_painel_existente(self.bot, self.membro)

        sinal = "+" if self.adicionar else "-"
        aviso = ""
        if not self.adicionar and aplicado < qtd:
            aviso = f"\n(O pedido era remover {qtd}, mas havia apenas {aplicado} LC disponíveis.)"
        await interaction.response.send_message(
            f"✅ **{sinal}{aplicado} LC** para {self.membro.mention}.\n"
            f"Motivo: **{motivo}**\nSaldo atual: **{dados['saldo']} LC**.{aviso}",
            ephemeral=True,
        )


class AjustarItemSelecionadoModal(discord.ui.Modal):
    def __init__(self, bot, membro, adicionar=True):
        super().__init__(title=("Dar item" if adicionar else "Remover item") + f" — {membro.display_name}"[:20])
        self.bot = bot
        self.membro = membro
        self.adicionar = adicionar
        self.item_id = discord.ui.TextInput(label="ID do item", placeholder="obonus", max_length=60)
        self.quantidade = discord.ui.TextInput(label="Quantidade", placeholder="1", max_length=10)
        self.motivo = discord.ui.TextInput(
            label="Motivo (opcional)",
            placeholder="Ex.: prêmio de evento",
            style=discord.TextStyle.short,
            max_length=200,
            required=False,
        )
        for campo in (self.item_id, self.quantidade, self.motivo):
            self.add_item(campo)

    async def on_submit(self, interaction):
        try:
            item_id = normalizar_item_id(self.item_id.value)
            qtd = parse_inteiro_opcional(self.quantidade.value, "Quantidade")
            item = find_item_by_id(item_id)
            if not item:
                raise ValueError("Esse item não existe no catálogo.")
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)

        dados = get_dados_jogador(self.membro.id)
        if self.adicionar:
            dados["cu"].extend([item_id] * qtd)
            aplicado = qtd
            tipo = "item_admin_add"
        else:
            aplicado = min(qtd, dados["cu"].count(item_id))
            if aplicado <= 0:
                return await interaction.response.send_message(
                    f"{self.membro.display_name} não possui esse item.", ephemeral=True
                )
            for _ in range(aplicado):
                dados["cu"].remove(item_id)
            tipo = "item_admin_remove"

        registrar_historico(
            dados,
            tipo,
            item_id=item_id,
            quantidade=aplicado,
            motivo=self.motivo.value.strip(),
            admin_id=interaction.user.id,
        )
        salvar_dados_jogadores()
        await atualizar_painel_existente(self.bot, self.membro)
        verbo = "adicionado ao" if self.adicionar else "removido do"
        await interaction.response.send_message(
            f"✅ {aplicado}x **{item.get('nome', item_id)}** {verbo} C.U. de {self.membro.mention}.",
            ephemeral=True,
        )


class UsuarioAcaoSelect(discord.ui.UserSelect):
    def __init__(self, bot, acao):
        self.bot = bot
        self.acao = acao
        textos = {
            "dar_lc": "Escolha quem vai receber LC...",
            "remover_lc": "Escolha de quem remover LC...",
            "dar_item": "Escolha quem vai receber o item...",
            "remover_item": "Escolha de quem remover o item...",
            "historico": "Escolha o jogador para ver o histórico...",
        }
        super().__init__(placeholder=textos.get(acao, "Escolha um jogador..."), min_values=1, max_values=1)

    async def callback(self, interaction):
        membro = self.values[0]
        if self.acao == "dar_lc":
            return await interaction.response.send_modal(AjustarSaldoSelecionadoModal(self.bot, membro, True))
        if self.acao == "remover_lc":
            return await interaction.response.send_modal(AjustarSaldoSelecionadoModal(self.bot, membro, False))
        if self.acao == "dar_item":
            return await interaction.response.send_modal(AjustarItemSelecionadoModal(self.bot, membro, True))
        if self.acao == "remover_item":
            return await interaction.response.send_modal(AjustarItemSelecionadoModal(self.bot, membro, False))
        if self.acao == "historico":
            embed, _ = criar_embed_extrato(self.bot, membro, 0, admin=True)
            return await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=ExtratoView(self.bot, membro, pagina=0, admin=True),
            )


class UsuarioAcaoView(AdminView):
    def __init__(self, bot, acao):
        super().__init__(timeout=300)
        self.bot = bot
        self.add_item(UsuarioAcaoSelect(bot, acao))


class AdminEconomiaView(AdminView):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(label="Dar LC", style=discord.ButtonStyle.success, emoji="➕")
    async def dar_lc(self, interaction, button):
        await interaction.response.send_message(
            "Escolha o jogador que vai receber LC:",
            view=UsuarioAcaoView(self.bot, "dar_lc"),
            ephemeral=True,
        )

    @discord.ui.button(label="Remover LC", style=discord.ButtonStyle.danger, emoji="➖")
    async def tirar_lc(self, interaction, button):
        await interaction.response.send_message(
            "Escolha o jogador:",
            view=UsuarioAcaoView(self.bot, "remover_lc"),
            ephemeral=True,
        )

    @discord.ui.button(label="Dar item", style=discord.ButtonStyle.success, emoji="🎁")
    async def dar_item(self, interaction, button):
        await interaction.response.send_message(
            "Escolha quem vai receber o item:",
            view=UsuarioAcaoView(self.bot, "dar_item"),
            ephemeral=True,
        )

    @discord.ui.button(label="Remover item", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def tirar_item(self, interaction, button):
        await interaction.response.send_message(
            "Escolha de quem remover o item:",
            view=UsuarioAcaoView(self.bot, "remover_item"),
            ephemeral=True,
        )

    @discord.ui.button(label="Histórico", style=discord.ButtonStyle.secondary, emoji="📜", row=1)
    async def historico(self, interaction, button):
        await interaction.response.send_message(
            "Escolha o jogador cujo extrato você quer consultar:",
            view=UsuarioAcaoView(self.bot, "historico"),
            ephemeral=True,
        )


class AdminPanelView(AdminView):
    def __init__(self, bot):
        super().__init__(timeout=600)
        self.bot = bot

    @discord.ui.button(label="Criar item", style=discord.ButtonStyle.success, emoji="✨")
    async def criar_item(self, interaction, button):
        await interaction.response.send_modal(CriarItemBasicoModal(self.bot))

    @discord.ui.button(label="Gerenciar item", style=discord.ButtonStyle.primary, emoji="📦")
    async def gerenciar_item(self, interaction, button):
        await interaction.response.send_message("Escolha o item que deseja administrar:", view=CatalogoSelectView(self.bot, 0), ephemeral=True)

    @discord.ui.button(label="Economia", style=discord.ButtonStyle.primary, emoji="💰")
    async def economia(self, interaction, button):
        await interaction.response.send_message("Administração de LC e C.U.:", view=AdminEconomiaView(self.bot), ephemeral=True)

    @discord.ui.button(label="Atualizar loja", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def atualizar_loja(self, interaction, button):
        recarregar_loja_e_catalogo()
        ok = await atualizar_mensagem_loja(self.bot)
        await interaction.response.send_message("✅ Loja e catálogo recarregados." if ok else "Os arquivos foram recarregados, mas não consegui editar a mensagem configurada da loja.", ephemeral=True)


# -----------------------------------------------------------------------------
# COG / COMANDOS ANTIGOS PRESERVADOS
# -----------------------------------------------------------------------------

class LojaCog(commands.Cog, name="Loja e Economia"):
    def __init__(self, bot):
        self.bot = bot
        self.compra_lock = asyncio.Lock()
        self._loja_restaurada = False
        self._ultima_data = None
        self.bot.add_view(ShopView(bot))
        self.bot.add_view(CUThreadView(bot))

    async def cog_load(self):
        self.verificar_mudanca_de_data.start()

    def cog_unload(self):
        self.verificar_mudanca_de_data.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if self._loja_restaurada:
            return
        self._loja_restaurada = True
        self._ultima_data = hoje_loja()
        await atualizar_mensagem_loja(self.bot)
        print("Loja v5 reconectada automaticamente.")

    @tasks.loop(minutes=15)
    async def verificar_mudanca_de_data(self):
        atual = hoje_loja()
        if self._ultima_data is None:
            self._ultima_data = atual
        elif atual != self._ultima_data:
            self._ultima_data = atual
            await atualizar_mensagem_loja(self.bot)

    @verificar_mudanca_de_data.before_loop
    async def antes_de_verificar_datas(self):
        await self.bot.wait_until_ready()

    @commands.command(name="admin")
    @is_admin()
    async def admin(self, ctx):
        embed = discord.Embed(
            title="⚙️ Administração do Leon",
            description="Gerencie itens, loja, estoque, datas, LC e C.U. pelos botões abaixo.",
            color=discord.Color.dark_teal(),
        )
        embed.add_field(name="Itens", value="Criar e gerenciar catálogo, preço, limite, estoque e datas.", inline=False)
        embed.add_field(name="Economia", value="Dar/remover LC e itens sem digitar os comandos antigos.", inline=False)
        await ctx.send(embed=embed, view=AdminPanelView(self.bot))

    @commands.command(name="admnovoitem")
    @is_admin()
    async def admnovoitem(self, ctx):
        await ctx.send("Clique abaixo para iniciar o cadastro guiado:", view=AdminNovoItemLauncher(self.bot))

    @commands.command(name="adminiciarloja")
    @is_admin()
    async def adminiciarloja(self, ctx, canal: discord.TextChannel = None):
        canal_alvo = canal or ctx.channel
        view = ShopView(self.bot)
        mensagem_loja = await canal_alvo.send(embed=view.criar_embed_pagina_atual(), view=view)
        print(f"\nID_CANAL_LOJA = {canal_alvo.id}\nID_MENSAGEM_LOJA = {mensagem_loja.id}\n")
        await ctx.send("Loja enviada. Copie os IDs exibidos no terminal para bot_leon.py.")

    @commands.command(name="admatualizarloja")
    @is_admin()
    async def admatualizarloja(self, ctx):
        recarregar_loja_e_catalogo()
        ok = await atualizar_mensagem_loja(self.bot)
        await ctx.send("Loja atualizada." if ok else "Arquivos recarregados, mas não consegui editar a mensagem configurada.")

    @commands.command(name="ajuda")
    async def ajuda(self, ctx):
        embed = discord.Embed(title="Manual de Comandos", color=discord.Color.from_rgb(79, 84, 92))
        embed.add_field(name="Loja", value="Use os botões da loja para comprar itens.", inline=False)
        embed.add_field(name="!cu [@membro]", value="Abre/consulta o C.U. O dono pode gastar itens pelo botão **Usar item**.", inline=False)
        embed.add_field(name="!saldo [@membro]", value="Exibe o saldo de LC.", inline=False)
        embed.add_field(name="!extrato", value="Mostra seu histórico de compras, usos e movimentações de LC.", inline=False)
        embed.add_field(name="!admin", value="Painel administrativo visual.", inline=False)
        embed.add_field(name="!usar quantidade id", value="Atalho antigo para gastar um item.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="saldo")
    async def saldo(self, ctx, membro: discord.Member = None):
        alvo = membro or ctx.author
        dados = get_dados_jogador(alvo.id)
        await ctx.send(embed=discord.Embed(title=f"Saldo de {alvo.display_name}", description=f"Total: {dados['saldo']} {self.bot.config['nome_moeda_plural']}", color=discord.Color.gold()))

    @commands.command(name="extrato")
    async def extrato(self, ctx):
        embed, _ = criar_embed_extrato(self.bot, ctx.author, 0, admin=False)
        await ctx.send(embed=embed, view=ExtratoView(self.bot, ctx.author, pagina=0, admin=False))

    @commands.command(name="admextrato")
    @is_admin()
    async def admextrato(self, ctx, membro: discord.Member = None):
        if membro is None:
            return await ctx.send(
                "Escolha o jogador abaixo:",
                view=UsuarioAcaoView(self.bot, "historico"),
            )
        embed, _ = criar_embed_extrato(self.bot, membro, 0, admin=True)
        await ctx.send(embed=embed, view=ExtratoView(self.bot, membro, pagina=0, admin=True))

    @commands.command(name="admsaldos")
    @is_admin()
    async def admsaldos(self, ctx):
        if not dados_jogadores:
            return await ctx.send("Banco de dados vazio.")
        ordenados = sorted(dados_jogadores.items(), key=lambda x: x[1].get("saldo", 0), reverse=True)
        txt = "\n".join(f"<@{uid}>: {info.get('saldo', 0)} LC" for uid, info in ordenados)
        await ctx.send(embed=discord.Embed(title="Saldo Geral", description=txt[:4000], color=0xFFD700))

    @commands.command(name="cu")
    async def cu(self, ctx, membro: discord.Member = None):
        alvo = membro or ctx.author
        dados = get_dados_jogador(alvo.id)
        if alvo.id != ctx.author.id:
            return await ctx.send(embed=criar_embed_cu(self.bot, alvo, dados))
        try:
            thread_cu, _ = await criar_ou_obter_topico_cu(self.bot, alvo)
            painel = await garantir_painel_cu(self.bot, alvo, thread_cu)
            await ctx.send(f"Seu C.U. interativo está em {thread_cu.mention}. Painel: {painel.jump_url}")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            await ctx.send(f"Não consegui abrir seu C.U.: {e}")

    @commands.command(name="usar")
    async def usar(self, ctx, quantidade: int, item_id: str):
        if quantidade <= 0:
            return await ctx.send("Quantidade inválida.")
        item_id = item_id.lower()
        dados = get_dados_jogador(ctx.author.id)
        if dados["cu"].count(item_id) < quantidade:
            return await ctx.send(f"Você não possui {quantidade} unidades do item '{item_id}' no seu C.U.")
        for _ in range(quantidade):
            dados["cu"].remove(item_id)
        registrar_historico(dados, "uso_item", item_id=item_id, quantidade=quantidade)
        salvar_dados_jogadores()
        item = find_item_by_id(item_id)
        nome = item.get("nome", item_id) if item else item_id
        await ctx.send(f"Você usou {quantidade}x {nome}.")
        await atualizar_painel_existente(self.bot, ctx.author)

    @commands.command(name="admgerarpainelcu")
    @is_admin()
    async def admgerarpainelcu(self, ctx):
        gerados = falhas = ignorados = 0
        for user_id, dados in list(dados_jogadores.items()):
            if not dados.get("id_topico_cu"):
                ignorados += 1
                continue
            try:
                thread = await self.bot.fetch_channel(dados["id_topico_cu"])
                usuario = ctx.guild.get_member(int(user_id)) or await self.bot.fetch_user(int(user_id))
                await garantir_painel_cu(self.bot, usuario, thread)
                gerados += 1
            except Exception as e:
                falhas += 1
                print(f"Falha ao gerar painel C.U. para {user_id}: {e}")
        await ctx.send(f"Painéis: {gerados} atualizado(s), {ignorados} sem tópico, {falhas} falha(s). Saldos e itens não foram alterados.")

    @commands.command(name="admganhar")
    @is_admin()
    async def admganhar(self, ctx, quantidade: int, *alvos: Union[discord.Member, discord.Role]):
        if quantidade <= 0:
            return await ctx.send("Valor inválido.")
        membros = set()
        for alvo in alvos:
            if isinstance(alvo, discord.Member):
                membros.add(alvo)
            elif isinstance(alvo, discord.Role):
                membros.update(alvo.members)
        if not alvos:
            membros.add(ctx.author)
        for membro in membros:
            dados = get_dados_jogador(membro.id)
            dados["saldo"] += quantidade
            registrar_historico(
                dados, "lc_admin_add", quantidade=quantidade,
                motivo="Ajuste administrativo via comando", admin_id=ctx.author.id
            )
        salvar_dados_jogadores()
        for membro in membros:
            await atualizar_painel_existente(self.bot, membro)
        await ctx.send(f"Adicionado {quantidade} LC a {len(membros)} alvo(s).")

    @commands.command(name="admgastar")
    @is_admin()
    async def admgastar(self, ctx, quantidade: int, *alvos: Union[discord.Member, discord.Role]):
        if quantidade <= 0:
            return await ctx.send("Valor inválido.")
        membros = set()
        for alvo in alvos:
            if isinstance(alvo, discord.Member):
                membros.add(alvo)
            elif isinstance(alvo, discord.Role):
                membros.update(alvo.members)
        if not alvos:
            membros.add(ctx.author)
        for membro in membros:
            dados = get_dados_jogador(membro.id)
            aplicado = min(quantidade, dados["saldo"])
            dados["saldo"] -= aplicado
            if aplicado > 0:
                registrar_historico(
                    dados, "lc_admin_remove", quantidade=aplicado,
                    motivo="Ajuste administrativo via comando", admin_id=ctx.author.id
                )
        salvar_dados_jogadores()
        for membro in membros:
            await atualizar_painel_existente(self.bot, membro)
        await ctx.send(f"Removido {quantidade} LC de {len(membros)} alvo(s).")

    @commands.command(name="admdaritem")
    @is_admin()
    async def admdaritem(self, ctx, quantidade: int, item_id: str, *alvos: Union[discord.Member, discord.Role]):
        if quantidade <= 0:
            return await ctx.send("Quantidade inválida.")
        item_id = item_id.lower()
        item = find_item_by_id(item_id)
        if not item:
            return await ctx.send("Item não registrado no catálogo.")
        membros = set()
        for alvo in alvos:
            if isinstance(alvo, discord.Member):
                membros.add(alvo)
            elif isinstance(alvo, discord.Role):
                membros.update(alvo.members)
        if not alvos:
            membros.add(ctx.author)
        for membro in membros:
            dados = get_dados_jogador(membro.id)
            dados["cu"].extend([item_id] * quantidade)
            registrar_historico(
                dados, "item_admin_add", item_id=item_id, quantidade=quantidade,
                motivo="Concedido via comando administrativo", admin_id=ctx.author.id
            )
        salvar_dados_jogadores()
        for membro in membros:
            await atualizar_painel_existente(self.bot, membro)
        await ctx.send(f"Item {item.get('nome')} adicionado a {len(membros)} alvo(s).")

    @commands.command(name="admremover")
    @is_admin()
    async def admremover(self, ctx, quantidade: int, item_id: str, *alvos: Union[discord.Member, discord.Role]):
        if quantidade <= 0:
            return await ctx.send("Quantidade inválida.")
        item_id = item_id.lower()
        membros = set()
        for alvo in alvos:
            if isinstance(alvo, discord.Member):
                membros.add(alvo)
            elif isinstance(alvo, discord.Role):
                membros.update(alvo.members)
        if not alvos:
            membros.add(ctx.author)
        for membro in membros:
            dados = get_dados_jogador(membro.id)
            remover = min(quantidade, dados["cu"].count(item_id))
            for _ in range(remover):
                dados["cu"].remove(item_id)
            if remover > 0:
                registrar_historico(
                    dados, "item_admin_remove", item_id=item_id, quantidade=remover,
                    motivo="Removido via comando administrativo", admin_id=ctx.author.id
                )
        salvar_dados_jogadores()
        for membro in membros:
            await atualizar_painel_existente(self.bot, membro)
        await ctx.send("Item removido.")


class AdminNovoItemLauncher(AdminView):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(label="Criar novo item", style=discord.ButtonStyle.success, emoji="✨")
    async def criar(self, interaction, button):
        await interaction.response.send_modal(CriarItemBasicoModal(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(LojaCog(bot))

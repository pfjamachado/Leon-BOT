# -*- coding: utf-8 -*-
"""Painel administrativo geral e persistente do Leon.

Uso:
    !instalaradmin

O comando só precisa ser usado para criar/recriar a mensagem fixa.
Depois, os botões continuam funcionando após reinícios do bot porque a View
é registrada como persistente no setup().

Integrações atuais:
- Personagens -> personagens_cog.py
- Economia    -> loja_cog.AdminEconomiaView
- Itens       -> criação e gerenciamento do catálogo da loja_cog
- Loja        -> atualização, gerenciamento de ofertas e status da loja
"""

import importlib

import discord
from discord.ext import commands


VERSAO_PAINEL_ADMIN = "3.0-CONECTADO-0903"


def usuario_tem_cargo_admin(bot, usuario, guild):
    """Usa a mesma lógica de permissão dos demais módulos do Leon."""
    if not guild:
        return False
    if usuario.id == guild.owner_id:
        return True

    config = getattr(bot, "config", {}) or {}
    cargos_admin = config.get("cargos_admin", [])
    nomes_usuario = [role.name for role in getattr(usuario, "roles", [])]
    return any(nome in nomes_usuario for nome in cargos_admin)


def is_admin():
    async def predicate(ctx):
        return usuario_tem_cargo_admin(ctx.bot, ctx.author, ctx.guild)
    return commands.check(predicate)


def carregar_modulo(nome):
    """Importa um módulo do Leon sem duplicar a lógica dele neste Cog."""
    try:
        return importlib.import_module(nome), None
    except ImportError as exc:
        print(f"ERRO AO IMPORTAR {nome}: {exc}")
        return None, exc


def carregar_loja():
    return carregar_modulo("loja_cog")


def embed_painel_geral():
    embed = discord.Embed(
        title="⚙️ PAINEL ADMINISTRATIVO — LEON",
        description=(
            "Central de administração do Leon.\n\n"
            "Use os botões abaixo para abrir os módulos administrativos. "
            "Os menus internos aparecem somente para você."
        ),
        color=discord.Color.dark_teal(),
    )
    embed.add_field(
        name="📜 Personagens",
        value="Fichas, XP, treinamentos, localização, afiliações e conhecimentos.",
        inline=False,
    )
    embed.add_field(
        name="💰 Economia",
        value="Dar/remover LC, dar/remover itens e consultar o extrato dos jogadores.",
        inline=False,
    )
    embed.add_field(
        name="🎒 Itens",
        value="Criar itens e administrar o catálogo, preço, estoque, limites e datas.",
        inline=False,
    )
    embed.add_field(
        name="🛒 Loja",
        value="Atualizar a loja, administrar ofertas e conferir o estado atual.",
        inline=False,
    )
    embed.set_footer(
        text=f"Painel persistente • versão {VERSAO_PAINEL_ADMIN} • comandos continuam como backup"
    )
    return embed


def embed_economia(bot):
    moeda = getattr(bot, "config", {}).get("nome_moeda_plural", "LC")
    return discord.Embed(
        title="💰 Administração da Economia",
        description=(
            f"Gerencie **{moeda}**, C.U. e movimentações dos jogadores.\n\n"
            "As alterações continuam usando o mesmo banco e o mesmo histórico da loja v3.2."
        ),
        color=discord.Color.gold(),
    )


def embed_itens():
    return discord.Embed(
        title="🎒 Administração de Itens",
        description=(
            "Crie novos itens ou abra o catálogo existente para alterar descrição, "
            "venda, estoque, limite individual e datas."
        ),
        color=discord.Color.blurple(),
    )


def criar_embed_status_loja(modulo):
    loja_data = getattr(modulo, "loja_data", {}) or {}
    catalogo = getattr(modulo, "catalogo_itens_completo", {}) or {}

    categorias = [
        nome for nome, itens in loja_data.items()
        if isinstance(itens, dict)
    ]

    total_ofertas = sum(
        len(itens)
        for itens in loja_data.values()
        if isinstance(itens, dict)
    )

    ativas = 0
    sem_estoque = 0
    com_limite = 0

    venda_ativa = getattr(modulo, "venda_ativa_por_data", None)

    for itens in loja_data.values():
        if not isinstance(itens, dict):
            continue
        for venda in itens.values():
            if not isinstance(venda, dict):
                continue

            if callable(venda_ativa):
                try:
                    if venda_ativa(venda):
                        ativas += 1
                except Exception:
                    pass
            else:
                ativas += 1

            estoque = venda.get("estoque_restante")
            if estoque is not None:
                try:
                    if int(estoque) <= 0:
                        sem_estoque += 1
                except (TypeError, ValueError):
                    pass

            if venda.get("limite_por_jogador") is not None:
                com_limite += 1

    embed = discord.Embed(
        title="🛒 Status da Loja",
        color=discord.Color.teal(),
    )
    embed.add_field(name="Itens no catálogo", value=str(len(catalogo)), inline=True)
    embed.add_field(name="Categorias", value=str(len(categorias)), inline=True)
    embed.add_field(name="Ofertas cadastradas", value=str(total_ofertas), inline=True)
    embed.add_field(name="Ofertas ativas hoje", value=str(ativas), inline=True)
    embed.add_field(name="Sem estoque", value=str(sem_estoque), inline=True)
    embed.add_field(name="Com limite individual", value=str(com_limite), inline=True)

    if categorias:
        embed.add_field(
            name="Categorias da loja",
            value=" • ".join(categorias)[:1024],
            inline=False,
        )

    embed.set_footer(text="Os valores são lidos diretamente de loja.json e catalogo_itens.json")
    return embed


class AdminBridgeView(discord.ui.View):
    """Base para os subpainéis administrativos deste Cog."""

    def __init__(self, bot, timeout=300):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message(
                "Você não tem permissão para usar este painel.",
                ephemeral=True,
            )
            return False
        return True


class ItensAdminBridgeView(AdminBridgeView):
    def __init__(self, bot):
        super().__init__(bot, timeout=300)

    @discord.ui.button(label="Criar item", emoji="✨", style=discord.ButtonStyle.success)
    async def criar_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja. Confira se `loja_cog.py` está carregado.",
                ephemeral=True,
            )

        modal_cls = getattr(modulo, "CriarItemBasicoModal", None)
        if modal_cls is None:
            return await interaction.response.send_message(
                "A versão atual de `loja_cog.py` não possui o criador de itens esperado.",
                ephemeral=True,
            )

        await interaction.response.send_modal(modal_cls(self.bot))

    @discord.ui.button(label="Gerenciar catálogo", emoji="📦", style=discord.ButtonStyle.primary)
    async def gerenciar_catalogo(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja. Confira se `loja_cog.py` está carregado.",
                ephemeral=True,
            )

        view_cls = getattr(modulo, "CatalogoSelectView", None)
        if view_cls is None:
            return await interaction.response.send_message(
                "A versão atual de `loja_cog.py` não possui o gerenciador de catálogo esperado.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "Escolha o item que deseja administrar:",
            view=view_cls(self.bot, 0),
            ephemeral=True,
        )

    @discord.ui.button(label="Recarregar arquivos", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def recarregar(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja.",
                ephemeral=True,
            )

        func = getattr(modulo, "recarregar_loja_e_catalogo", None)
        if not callable(func):
            return await interaction.response.send_message(
                "A versão atual da loja não possui a função de recarregamento esperada.",
                ephemeral=True,
            )

        func()
        await interaction.response.send_message(
            "✅ `loja.json` e `catalogo_itens.json` foram recarregados.",
            ephemeral=True,
        )


class LojaAdminBridgeView(AdminBridgeView):
    def __init__(self, bot):
        super().__init__(bot, timeout=300)

    @discord.ui.button(label="Atualizar loja", emoji="🔄", style=discord.ButtonStyle.success)
    async def atualizar_loja(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja. Confira se `loja_cog.py` está carregado.",
                ephemeral=True,
            )

        recarregar = getattr(modulo, "recarregar_loja_e_catalogo", None)
        atualizar = getattr(modulo, "atualizar_mensagem_loja", None)

        if not callable(recarregar) or not callable(atualizar):
            return await interaction.response.send_message(
                "A versão atual da loja não possui as funções de atualização esperadas.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        recarregar()
        ok = await atualizar(self.bot)

        if ok:
            texto = "✅ Loja, catálogo e mensagem fixa foram atualizados."
        else:
            texto = (
                "⚠️ Os arquivos foram recarregados, mas não consegui editar a mensagem fixa da loja. "
                "Confira `id_canal_loja` e `id_mensagem_loja` na configuração do Leon."
            )

        await interaction.followup.send(texto, ephemeral=True)

    @discord.ui.button(label="Gerenciar ofertas", emoji="🏷️", style=discord.ButtonStyle.primary)
    async def gerenciar_ofertas(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja.",
                ephemeral=True,
            )

        view_cls = getattr(modulo, "CatalogoSelectView", None)
        if view_cls is None:
            return await interaction.response.send_message(
                "A versão atual de `loja_cog.py` não possui o gerenciador esperado.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "Escolha um item. Dentro dele você pode alterar venda, estoque, datas e retirar da loja:",
            view=view_cls(self.bot, 0),
            ephemeral=True,
        )

    @discord.ui.button(label="Status", emoji="📊", style=discord.ButtonStyle.secondary)
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui abrir o módulo da loja.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            embed=criar_embed_status_loja(modulo),
            ephemeral=True,
        )


class PainelAdminGeralView(discord.ui.View):
    """View persistente do painel principal."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message(
                "Você não tem permissão para usar o painel administrativo do Leon.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Personagens",
        emoji="📜",
        style=discord.ButtonStyle.primary,
        custom_id="leon:admin_geral:personagens",
        row=0,
    )
    async def personagens(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            modulo = importlib.import_module("personagens_cog")
            painel_cls = getattr(modulo, "AdminPersonagensPanel")
            limite_historico = getattr(modulo, "LIMITE_HISTORICO", 120)
        except (ImportError, AttributeError) as exc:
            print(f"ERRO AO ABRIR PAINEL DE PERSONAGENS: {exc}")
            await interaction.response.send_message(
                "Não consegui carregar o módulo de Personagens. Confira se `personagens_cog.py` está carregado junto dos outros Cogs.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="⚙️ Administração de Personagens",
            description=(
                "Crie personagens, vincule jogadores e gerencie XP, treinamento, "
                "localização, data/hora do jogo, residência, afiliações e conhecimentos."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="Histórico enxuto",
            value=(
                "XP e treino são registrados; localização só entra quando você marcar **sim**. "
                f"O limite é de {limite_historico} registros por personagem."
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=painel_cls(self.bot),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Economia",
        emoji="💰",
        style=discord.ButtonStyle.primary,
        custom_id="leon:admin_geral:economia",
        row=0,
    )
    async def economia(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui carregar Economia. Confira se `loja_cog.py` está carregado junto dos outros Cogs.",
                ephemeral=True,
            )

        view_cls = getattr(modulo, "AdminEconomiaView", None)
        if view_cls is None:
            return await interaction.response.send_message(
                "A versão atual de `loja_cog.py` não possui `AdminEconomiaView`.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            embed=embed_economia(self.bot),
            view=view_cls(self.bot),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Itens",
        emoji="🎒",
        style=discord.ButtonStyle.primary,
        custom_id="leon:admin_geral:itens",
        row=0,
    )
    async def itens(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui carregar Itens. Confira se `loja_cog.py` está carregado junto dos outros Cogs.",
                ephemeral=True,
            )

        # Confere as integrações antes de mostrar um painel que não funcionaria.
        if not hasattr(modulo, "CriarItemBasicoModal") or not hasattr(modulo, "CatalogoSelectView"):
            return await interaction.response.send_message(
                "A versão atual de `loja_cog.py` não possui os componentes de itens esperados.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            embed=embed_itens(),
            view=ItensAdminBridgeView(self.bot),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Loja",
        emoji="🛒",
        style=discord.ButtonStyle.primary,
        custom_id="leon:admin_geral:loja",
        row=0,
    )
    async def loja(self, interaction: discord.Interaction, button: discord.ui.Button):
        modulo, erro = carregar_loja()
        if erro:
            return await interaction.response.send_message(
                "Não consegui carregar a Loja. Confira se `loja_cog.py` está carregado junto dos outros Cogs.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="🛒 Administração da Loja",
            description=(
                "Atualize a mensagem fixa da loja, administre ofertas ou confira rapidamente "
                "o estado do catálogo e do estoque."
            ),
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=LojaAdminBridgeView(self.bot),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Atualizar painel",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="leon:admin_geral:atualizar",
        row=1,
    )
    async def atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=embed_painel_geral(),
            view=self,
        )


class PainelAdminCog(commands.Cog, name="Painel Admin"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="instalaradmin", aliases=["paineladmin"])
    @is_admin()
    async def instalaradmin(self, ctx: commands.Context):
        """Cria ou recria a mensagem fixa do painel administrativo."""
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        mensagem = await ctx.send(
            embed=embed_painel_geral(),
            view=PainelAdminGeralView(self.bot),
        )

        try:
            await mensagem.pin(reason="Painel administrativo persistente do Leon")
        except (discord.Forbidden, discord.HTTPException):
            # O painel continua funcionando mesmo se o bot não puder fixar mensagens.
            pass


    @commands.command(name="versaoadmin")
    @is_admin()
    async def versaoadmin(self, ctx: commands.Context):
        await ctx.send(f"Painel administrativo: **{VERSAO_PAINEL_ADMIN}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(PainelAdminCog(bot))
    bot.add_view(PainelAdminGeralView(bot))
    print(f"Painel Admin {VERSAO_PAINEL_ADMIN} carregado: Personagens, Economia, Itens e Loja conectados.")

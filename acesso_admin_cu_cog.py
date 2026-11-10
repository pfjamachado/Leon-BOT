# -*- coding: utf-8 -*-
"""
LEON — Acesso administrativo real aos painéis pessoais do C.U.

Corrige as permissões diretamente no módulo de loja que está CARREGADO pelo bot.
Isso evita o problema de importar uma segunda instância de loja_cog.

Recursos:
- ADM pode usar o painel fixo do C.U. de qualquer jogador.
- ADM pode abrir inventário/uso de item, extrato e atualizar painel.
- Todas as ações continuam afetando o DONO do C.U., nunca o inventário do ADM.
- !admcu @Jogador abre/adiciona o ADM ao tópico privado e retorna o link do painel.
"""

import sys
import discord
from discord.ext import commands


def obter_modulo_loja(bot):
    """Retorna o módulo exato do Cog de loja/economia que o bot carregou."""
    cog = bot.get_cog("Loja e Economia")
    if cog is None:
        return None
    return sys.modules.get(cog.__class__.__module__)


def eh_admin(modulo_loja, bot, usuario, guild):
    return bool(
        modulo_loja
        and hasattr(modulo_loja, "usuario_tem_cargo_admin")
        and modulo_loja.usuario_tem_cargo_admin(bot, usuario, guild)
    )


def aplicar_override(bot):
    loja = obter_modulo_loja(bot)
    if loja is None:
        return False, "Cog 'Loja e Economia' ainda não está carregado."

    if getattr(loja, "_leon_admin_cu_override_v2", False):
        return True, "Override V2 já estava ativo."

    classes_necessarias = (
        "ConfirmarUsoView",
        "QuantidadeUsoView",
        "ItemSelectView",
        "CUThreadView",
        "ExtratoView",
    )
    faltando = [nome for nome in classes_necessarias if not hasattr(loja, nome)]
    if faltando:
        return False, "Classes não encontradas em loja_cog: " + ", ".join(faltando)

    # ItemSelectView não guardava o bot originalmente. Guardamos para a checagem ADM.
    if not getattr(loja.ItemSelectView, "_leon_init_admin_v2", False):
        original_init = loja.ItemSelectView.__init__

        def item_select_init(self, bot_obj, usuario, mensagem_painel):
            original_init(self, bot_obj, usuario, mensagem_painel)
            self.bot = bot_obj

        loja.ItemSelectView.__init__ = item_select_init
        loja.ItemSelectView._leon_init_admin_v2 = True

    async def check_dono_ou_admin(self, interaction):
        dono = getattr(self, "usuario", None)
        bot_obj = getattr(self, "bot", None) or bot
        permitido = bool(
            dono
            and (
                interaction.user.id == dono.id
                or eh_admin(loja, bot_obj, interaction.user, interaction.guild)
            )
        )
        if not permitido:
            await interaction.response.send_message(
                "Este menu pertence a outro jogador.", ephemeral=True
            )
            return False
        return True

    loja.ConfirmarUsoView.interaction_check = check_dono_ou_admin
    loja.QuantidadeUsoView.interaction_check = check_dono_ou_admin
    loja.ItemSelectView.interaction_check = check_dono_ou_admin

    async def resolver_usuario_dono_ou_admin(self, interaction):
        user_id, dados = loja.buscar_dono_por_topico(interaction.channel_id)
        if not user_id:
            return None, dados

        permitido = (
            interaction.user.id == user_id
            or eh_admin(loja, self.bot, interaction.user, interaction.guild)
        )
        if not permitido:
            return None, dados

        # Retorna SEMPRE o dono real do C.U.; o ADM é apenas autorizado a operar.
        usuario = None
        if interaction.guild:
            usuario = interaction.guild.get_member(user_id)
            if usuario is None:
                try:
                    usuario = await interaction.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    usuario = None

        if usuario is None:
            try:
                usuario = await self.bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None, dados

        return usuario, dados

    loja.CUThreadView.resolver_usuario = resolver_usuario_dono_ou_admin

    async def extrato_check(self, interaction):
        permitido = (
            self.admin
            or interaction.user.id == self.usuario.id
            or eh_admin(loja, self.bot, interaction.user, interaction.guild)
        )
        if not permitido:
            await interaction.response.send_message(
                "Esse extrato não pertence a você.", ephemeral=True
            )
            return False
        return True

    loja.ExtratoView.interaction_check = extrato_check
    loja._leon_admin_cu_override_v2 = True
    return True, f"Override aplicado em {loja.__name__}."


class AcessoAdminCUCog(commands.Cog, name="Acesso ADM ao C.U."):
    def __init__(self, bot):
        self.bot = bot
        self._aplicado = False

    async def cog_load(self):
        # Tenta já no carregamento; se a loja vier depois, on_ready tenta novamente.
        ok, msg = aplicar_override(self.bot)
        self._aplicado = ok
        print(f"[ADM C.U. V2] {msg}")

    @commands.Cog.listener()
    async def on_ready(self):
        if self._aplicado:
            return
        ok, msg = aplicar_override(self.bot)
        self._aplicado = ok
        print(f"[ADM C.U. V2/on_ready] {msg}")

    @commands.command(name="admcu")
    async def admcu(self, ctx, membro: discord.Member = None):
        loja = obter_modulo_loja(self.bot)
        if loja is None:
            return await ctx.send("O módulo de Loja e Economia não está carregado.")
        if not eh_admin(loja, self.bot, ctx.author, ctx.guild):
            return await ctx.send("Você não tem permissão para usar este comando.")
        if membro is None:
            return await ctx.send("Use **!admcu @Jogador**.")

        # Garante que o override esteja aplicado antes de abrir o painel.
        ok, msg = aplicar_override(self.bot)
        if not ok:
            return await ctx.send(f"Não consegui ativar o acesso ADM ao C.U.: {msg}")

        try:
            thread_cu, _ = await loja.criar_ou_obter_topico_cu(self.bot, membro)
            try:
                await thread_cu.add_user(ctx.author)
            except discord.HTTPException:
                pass

            painel = await loja.garantir_painel_cu(self.bot, membro, thread_cu)
            await ctx.send(
                f"⚙️ Acesso administrativo ao C.U. de {membro.mention}: "
                f"{thread_cu.mention}\nPainel: {painel.jump_url}"
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            await ctx.send(f"Não consegui abrir esse C.U.: {e}")

    @commands.command(name="testeadmincu")
    async def testeadmincu(self, ctx):
        loja = obter_modulo_loja(self.bot)
        if loja is None:
            return await ctx.send("❌ Loja e Economia não carregado.")
        if not eh_admin(loja, self.bot, ctx.author, ctx.guild):
            return await ctx.send("Você não tem permissão.")
        ok, msg = aplicar_override(self.bot)
        await ctx.send(f"{'✅' if ok else '❌'} ADM C.U. V2 — {msg}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AcessoAdminCUCog(bot))

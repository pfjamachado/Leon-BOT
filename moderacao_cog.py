# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import datetime

def is_admin():
    async def predicate(ctx):
        admin_roles = ctx.bot.config['cargos_admin']
        if ctx.author == ctx.guild.owner: return True
        author_roles = [role.name for role in ctx.author.roles]
        return any(role in author_roles for role in admin_roles)
    return commands.check(predicate)

class ModeracaoCog(commands.Cog, name="Moderação"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='admlimpar')
    @is_admin()
    async def admlimpar(self, ctx, quantidade: int):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if quantidade <= 0:
            return await ctx.send("A quantidade deve ser maior que zero.")
            
        await ctx.channel.purge(limit=quantidade)
        msg = await ctx.send(f"{quantidade} mensagens apagadas.")
        await msg.delete(delay=5)

    @commands.command(name='admsilenciar')
    @is_admin()
    async def admsilenciar(self, ctx, membro: discord.Member, minutos: int, *, motivo: str = "Não especificado."):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if minutos <= 0:
            return await ctx.send("O tempo deve ser maior que zero.")
        
        tempo_castigo = datetime.timedelta(minutes=minutos)
        try:
            await membro.timeout(tempo_castigo, reason=motivo)
            await ctx.send(f"{membro.mention} foi silenciado por {minutos} minuto(s). Motivo: {motivo}")
        except discord.Forbidden:
            await ctx.send("Permissão negada. Verifique se o cargo do bot está acima do cargo do alvo.")

    @commands.command(name='admdesilenciar')
    @is_admin()
    async def admdesilenciar(self, ctx, membro: discord.Member):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        try:
            await membro.timeout(None)
            await ctx.send(f"O silenciamento de {membro.mention} foi removido.")
        except discord.Forbidden:
            await ctx.send("Permissão negada.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ModeracaoCog(bot))

# -*- coding: utf-8 -*-

import discord
from discord.ext import commands
import traceback
import os


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Canal e mensagem principal da loja
ID_CANAL_LOJA = 1404701737771597875
ID_MENSAGEM_LOJA = 1495274562365952020

# Canal onde os tópicos privados dos C.U.s são criados
ID_CANAL_CU = 1404767212715114556


CONFIG = {
    'id_canal_loja': ID_CANAL_LOJA,
    'id_mensagem_loja': ID_MENSAGEM_LOJA,
    'id_canal_cu': ID_CANAL_CU,

    'nome_moeda_singular': 'LC',
    'nome_moeda_plural': 'LC',

    # Deve ser exatamente igual ao nome do cargo no Discord
    'cargos_admin': ['Líder Supremo']
}


# ============================================================
# BOT PRINCIPAL
# ============================================================

class LeonBot(commands.Bot):

    def __init__(self):

        # Intents necessários
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

        self.config = CONFIG


    # ========================================================
    # CARREGAMENTO DOS MÓDULOS
    # ========================================================

    async def setup_hook(self):

        print("\n==================================================")
        print("INICIANDO MÓDULOS DO LEON")
        print("==================================================")

        extensoes = [
            'loja_cog',
            'personagens_cog',
            'painel_admin_cog',
            'acesso_admin_cu_cog',
            'moderacao_cog'
        ]

        for extensao in extensoes:

            try:
                await self.load_extension(extensao)

                print(
                    f"[OK] Módulo '{extensao}' carregado com sucesso."
                )

            except Exception as erro:

                print(
                    f"\n[ERRO] Não foi possível carregar "
                    f"o módulo '{extensao}'."
                )

                print(f"Motivo: {erro}\n")

                # Mostra o traceback completo no terminal
                traceback.print_exc()

        # Mostra todos os comandos que realmente foram carregados
        print("\n==================================================")
        print("COMANDOS CARREGADOS")
        print("==================================================")

        comandos = sorted(
            self.commands,
            key=lambda comando: comando.name
        )

        if not comandos:

            print("[AVISO] Nenhum comando foi carregado!")

        else:

            for comando in comandos:
                print(f"  !{comando.name}")

        print("==================================================\n")


    # ========================================================
    # QUANDO O BOT FICA ONLINE
    # ========================================================

    async def on_ready(self):

        print("==================================================")
        print(f"LEON ONLINE")
        print(f"Usuário: {self.user}")
        print(f"ID: {self.user.id}")
        print("==================================================")


    # ========================================================
    # SISTEMA GLOBAL DE ERROS
    # ========================================================

    async def on_command_error(self, ctx, error):

        # ----------------------------------------------------
        # Comando inexistente
        # ----------------------------------------------------

        if isinstance(error, commands.CommandNotFound):

            await ctx.send(
                f"❌ O comando `!{ctx.invoked_with}` "
                f"não foi encontrado.\n"
                f"Verifique se o comando existe ou se o módulo "
                f"responsável foi carregado corretamente."
            )

            return


        # ----------------------------------------------------
        # Argumento obrigatório faltando
        # ----------------------------------------------------

        if isinstance(error, commands.MissingRequiredArgument):

            if ctx.command:

                await ctx.send(
                    f"❌ Está faltando informação no comando.\n\n"
                    f"Uso correto:\n"
                    f"`!{ctx.command.qualified_name} "
                    f"{ctx.command.signature}`"
                )

            else:

                await ctx.send(
                    "❌ Está faltando informação nesse comando."
                )

            return


        # ----------------------------------------------------
        # Argumento inválido
        # ----------------------------------------------------

        if isinstance(error, commands.BadArgument):

            await ctx.send(
                "❌ Não consegui interpretar algum dos valores "
                "informados.\n"
                "Confira nomes, menções, números e o formato "
                "do comando."
            )

            return


        # ----------------------------------------------------
        # Usuário sem permissão
        # ----------------------------------------------------

        if isinstance(error, commands.CheckFailure):

            await ctx.send(
                "❌ Você não tem permissão para usar esse comando."
            )

            return


        # ----------------------------------------------------
        # Comando em cooldown
        # ----------------------------------------------------

        if isinstance(error, commands.CommandOnCooldown):

            await ctx.send(
                f"⏳ Esse comando está em espera.\n"
                f"Tente novamente em "
                f"{error.retry_after:.1f} segundos."
            )

            return


        # ----------------------------------------------------
        # Erro ocorrido dentro de um comando
        # ----------------------------------------------------

        if isinstance(error, commands.CommandInvokeError):

            comando_nome = (
                ctx.command.qualified_name
                if ctx.command
                else "desconhecido"
            )

            print("\n==================================================")
            print(f"[ERRO NO COMANDO] !{comando_nome}")
            print("==================================================")

            erro_original = error.original

            traceback.print_exception(
                type(erro_original),
                erro_original,
                erro_original.__traceback__
            )

            print("==================================================\n")

            await ctx.send(
                f"⚠️ O comando `!{comando_nome}` encontrou um "
                f"erro durante a execução.\n"
                f"O erro completo foi registrado no terminal "
                f"do Leon."
            )

            return


        # ----------------------------------------------------
        # Qualquer outro erro inesperado
        # ----------------------------------------------------

        print("\n==================================================")
        print("[ERRO DESCONHECIDO]")
        print("==================================================")

        traceback.print_exception(
            type(error),
            error,
            error.__traceback__
        )

        print("==================================================\n")

        await ctx.send(
            "⚠️ Aconteceu um erro inesperado.\n"
            "Os detalhes foram registrados no terminal do Leon."
        )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

bot = LeonBot()


if __name__ == '__main__':

    # Configure DISCORD_TOKEN no ambiente antes de iniciar o Leon.
    TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
    if not TOKEN:

        print("==================================================")
        print("ERRO")
        print("==================================================")
        print(
            "Você precisa inserir o token do bot "
            "na variável de ambiente DISCORD_TOKEN."
        )
        print("==================================================")

    else:

        try:

            bot.run(TOKEN)

        except discord.LoginFailure:

            print("\n==================================================")
            print("ERRO DE LOGIN")
            print("==================================================")
            print(
                "O token informado é inválido ou foi revogado."
            )
            print("==================================================")

        except Exception:

            print("\n==================================================")
            print("ERRO FATAL AO INICIAR O LEON")
            print("==================================================")

            traceback.print_exc()

            print("==================================================")

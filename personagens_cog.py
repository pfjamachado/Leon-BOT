# -*- coding: utf-8 -*-
"""
LEON — Módulo de Personagens

Separado do C.U. e da economia.
Armazena dados de personagem em personagens.json.

Recursos:
- Ficha visual do personagem
- Vínculo opcional com jogador do Discord
- Localização atual
- Data/hora dentro do jogo
- Residência fixa
- Objetivo atual
- Afiliações e cargos
- XP atual + meta de XP
- Horas de treinamento acumuladas por área e finalidade
- Conhecimentos separados por categorias, editáveis por mestre e jogador
- Histórico enxuto (XP, treino e localizações marcadas como relevantes)
- Painel administrativo com botões e menus

Comandos:
!personagens      -> abre os personagens ligados ao próprio jogador
!personagem       -> abre a ficha se houver apenas um personagem ligado
!personagem NOME  -> abre um personagem próprio pelo nome/ID
!admpersonagens   -> painel administrativo completo

IMPORTANTE:
Este arquivo NÃO usa banco_de_dados.json e NÃO altera o C.U.
Ele cria/usa apenas personagens.json.
"""
import datetime
import json
import os
import math
import re
import unicodedata
from typing import Optional
from decimal import Decimal, InvalidOperation
import discord
from discord.ext import commands
DIRETORIO_DADOS = os.environ.get("LEON_DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "."
ARQUIVO_PERSONAGENS = os.path.join(DIRETORIO_DADOS, "personagens.json")
LIMITE_HISTORICO = 120
ITENS_POR_PAGINA = 25
CONHECIMENTOS_POR_PAGINA = 8
LIMITE_EXTRATO_MONETARIO = 200
CATEGORIAS_CONHECIMENTO = ('Pessoas', 'Lugares', 'Organizações', 'Objetos', 'Eventos', 'Magia', 'Outros')

def carregar_json(arquivo):
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            return dados if isinstance(dados, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"ERRO AO CARREGAR '{arquivo}': {e}")
        return {}

def salvar_json(arquivo, dados):
    os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
    with open(arquivo, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

def estrutura_inicial():
    return {'proximo_id': 1, 'personagens': {}, 'paineis_ficha': {}}

def normalizar_banco(dados):
    if not isinstance(dados, dict):
        dados = estrutura_inicial()
    dados.setdefault('proximo_id', 1)
    dados.setdefault('personagens', {})
    dados.setdefault('paineis_ficha', {})
    if not isinstance(dados['personagens'], dict):
        dados['personagens'] = {}
    if not isinstance(dados['paineis_ficha'], dict):
        dados['paineis_ficha'] = {}
    return dados
banco = normalizar_banco(carregar_json(ARQUIVO_PERSONAGENS))

def salvar_banco():
    salvar_json(ARQUIVO_PERSONAGENS, banco)

def registrar_painel_ficha(bot, message_id, personagem_id, usuario_id):
    """
    Guarda os dados necessários para
    reativar a ficha após reinícios.
    """
    message_id = str(message_id)
    personagem_id = str(personagem_id)
    usuario_id = int(usuario_id)
    banco.setdefault('paineis_ficha', {})[message_id] = {'personagem_id': personagem_id, 'usuario_id': usuario_id}
    salvar_banco()

def restaurar_paineis_ficha(bot):
    """
    Reativa fichas persistentes
    gravadas em personagens.json.
    """
    restaurados = 0
    invalidos = []
    for message_id, info in banco.setdefault('paineis_ficha', {}).items():
        try:
            personagem_id = str(info['personagem_id'])
            usuario_id = int(info['usuario_id'])
            if not get_personagem(personagem_id):
                invalidos.append(message_id)
                continue
            bot.add_view(FichaPersonagemView(bot, personagem_id, usuario_id), message_id=int(message_id))
            restaurados += 1
        except (KeyError, TypeError, ValueError):
            invalidos.append(message_id)
    if invalidos:
        for message_id in invalidos:
            banco['paineis_ficha'].pop(message_id, None)
        salvar_banco()
    return restaurados

def agora_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

def sem_acento(texto):
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join((c for c in texto if not unicodedata.combining(c)))

def chave_texto(texto):
    texto = sem_acento(texto).lower().strip()
    texto = re.sub('\\s+', ' ', texto)
    return texto

def texto_ou_traco(valor):
    valor = str(valor or '').strip()
    return valor if valor else '—'

def limitar(texto, limite=1024):
    texto = str(texto or '')
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1] + '…'

def formatar_horas(minutos):
    try:
        minutos = max(0, int(minutos or 0))
    except (TypeError, ValueError):
        minutos = 0
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f'{horas}h {resto}min'
    if horas:
        return f'{horas}h'
    return f'{resto}min'

def parse_tempo_treino(texto):
    """
    Aceita:

    2       -> 2 horas
    2,5     -> 2h30
    2.5     -> 2h30
    1:30    -> 1h30
    45min   -> 45min
    2h      -> 2h
    2h30    -> 2h30
    -1h     -> remove 1h
    """
    raw = str(texto or '').strip().lower().replace(' ', '')
    if not raw:
        raise ValueError('Informe a duração do treinamento.')
    sinal = -1 if raw.startswith('-') else 1
    if raw[0] in '+-':
        raw = raw[1:]
    if not raw:
        raise ValueError('Duração inválida.')
    if raw.endswith('min'):
        numero = raw[:-3].replace(',', '.')
        try:
            minutos = round(float(numero))
        except ValueError:
            raise ValueError('Duração inválida. Ex.: 2, 1,5, 1:30, 45min ou 2h30.')
        if minutos <= 0:
            raise ValueError('A duração precisa ser maior que zero.')
        return sinal * minutos
    if 'h' in raw:
        partes = raw.split('h', 1)
        try:
            horas = int(partes[0] or 0)
            resto_minutos = partes[1].replace('min', '').replace('m', '')
            minutos = int(resto_minutos or 0)
        except ValueError:
            raise ValueError('Duração inválida. Ex.: 2h, 2h30 ou 45min.')
        total = horas * 60 + minutos
        if total <= 0 or minutos >= 60:
            raise ValueError('Duração inválida.')
        return sinal * total
    if ':' in raw:
        partes = raw.split(':', 1)
        try:
            horas = int(partes[0])
            minutos = int(partes[1])
        except ValueError:
            raise ValueError('Duração inválida. Ex.: 1:30.')
        if horas < 0 or minutos < 0 or minutos >= 60:
            raise ValueError('Duração inválida.')
        total = horas * 60 + minutos
        if total <= 0:
            raise ValueError('A duração precisa ser maior que zero.')
        return sinal * total
    try:
        horas = float(raw.replace(',', '.'))
    except ValueError:
        raise ValueError('Duração inválida. Ex.: 2, 1,5, 1:30, 45min ou 2h30.')
    minutos = round(horas * 60)
    if minutos <= 0:
        raise ValueError('A duração precisa ser maior que zero.')
    return sinal * minutos

def parse_inteiro(texto, nome='Valor', permitir_zero=True, permitir_negativo=False):
    try:
        valor = int(str(texto).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{nome} precisa ser um número inteiro.')
    if not permitir_negativo and valor < 0:
        raise ValueError(f'{nome} não pode ser negativo.')
    if not permitir_zero and valor == 0:
        raise ValueError(f'{nome} não pode ser zero.')
    return valor

def novo_personagem(nome):
    personagem_id = str(int(banco.get('proximo_id', 1)))
    banco['proximo_id'] = int(personagem_id) + 1
    personagem = {'id': personagem_id, 'nome': nome.strip(), 'jogador_id': None, 'residencia_fixa': '', 'localizacao_atual': '', 'data_hora_jogo': '', 'objetivo_atual': '', 'afiliacoes': [], 'monetario': {}, 'monetario_extrato': [], 'xp': 0, 'xp_meta': None, 'treinos': {}, 'conhecimentos': {categoria: [] for categoria in CATEGORIAS_CONHECIMENTO}, 'historico': [], 'criado_em': agora_iso(), 'atualizado_em': agora_iso()}
    banco['personagens'][personagem_id] = personagem
    salvar_banco()
    return personagem

def migrar_personagem(p):
    p.setdefault('id', '')
    p.setdefault('nome', 'Sem nome')
    p.setdefault('jogador_id', None)
    p.setdefault('residencia_fixa', '')
    p.setdefault('localizacao_atual', '')
    p.setdefault('data_hora_jogo', '')
    p.setdefault('objetivo_atual', '')
    p.setdefault('afiliacoes', [])
    p.setdefault('monetario', {})
    p.setdefault('monetario_extrato', [])
    p.setdefault('xp', 0)
    p.setdefault('xp_meta', None)
    p.setdefault('treinos', {})
    p.setdefault('conhecimentos', {})
    p.setdefault('historico', [])
    p.setdefault('criado_em', agora_iso())
    p.setdefault('atualizado_em', agora_iso())
    if not isinstance(p['afiliacoes'], list):
        p['afiliacoes'] = []
    if not isinstance(p['monetario'], dict):
        p['monetario'] = {}
    if not isinstance(p['monetario_extrato'], list):
        p['monetario_extrato'] = []
    for moeda_id, info in list(p['monetario'].items()):
        if not isinstance(info, dict):
            p['monetario'].pop(moeda_id, None)
            continue
        info.setdefault('nome', str(moeda_id))
        info.setdefault('simbolo', '')
        info.setdefault('maos', '0')
        info.setdefault('banco', '0')
        for campo in ('maos', 'banco'):
            try:
                info[campo] = decimal_para_texto(Decimal(str(info.get(campo, '0')).replace(',', '.')))
            except (InvalidOperation, ValueError, TypeError):
                info[campo] = '0'
    if not isinstance(p['treinos'], dict):
        p['treinos'] = {}
    for treino_id, info in list(p['treinos'].items()):
        if not isinstance(info, dict):
            continue
        meta = info.get('meta_minutos')
        try:
            meta = int(meta) if meta not in (None, '') else None
        except (TypeError, ValueError):
            meta = None
        if meta is not None and meta <= 0:
            meta = None
        info['meta_minutos'] = meta
    if not isinstance(p['conhecimentos'], dict):
        p['conhecimentos'] = {}
    for categoria in CATEGORIAS_CONHECIMENTO:
        if not isinstance(p['conhecimentos'].get(categoria), list):
            p['conhecimentos'][categoria] = []
    if not isinstance(p['historico'], list):
        p['historico'] = []
    return p

def todos_personagens():
    resultado = []
    for personagem_id, p in banco.get('personagens', {}).items():
        if not isinstance(p, dict):
            continue
        p = migrar_personagem(p)
        p['id'] = str(personagem_id)
        resultado.append(p)
    return sorted(resultado, key=lambda x: chave_texto(x.get('nome')))

def get_personagem(personagem_id):
    p = banco.get('personagens', {}).get(str(personagem_id))
    if not isinstance(p, dict):
        return None
    p = migrar_personagem(p)
    p['id'] = str(personagem_id)
    return p

def personagens_do_jogador(user_id):
    uid = str(user_id)
    return [p for p in todos_personagens() if str(p.get('jogador_id') or '') == uid]

def buscar_personagem(consulta, candidatos=None):
    consulta = str(consulta or '').strip()
    if not consulta:
        return (None, 'Informe o nome ou ID do personagem.')
    candidatos = candidatos if candidatos is not None else todos_personagens()
    if consulta.isdigit():
        for p in candidatos:
            if str(p.get('id')) == consulta:
                return (p, None)
    alvo = chave_texto(consulta)
    exatos = [p for p in candidatos if chave_texto(p.get('nome')) == alvo]
    if len(exatos) == 1:
        return (exatos[0], None)
    parciais = [p for p in candidatos if alvo in chave_texto(p.get('nome'))]
    if len(parciais) == 1:
        return (parciais[0], None)
    if len(parciais) > 1:
        nomes = ', '.join((f"{p['nome']} (#{p['id']})" for p in parciais[:8]))
        return (None, f'Encontrei mais de um personagem: {nomes}. Use o ID.')
    return (None, 'Não encontrei esse personagem.')

def personagem_nome_existe(nome, ignorar_id=None):
    chave = chave_texto(nome)
    for p in todos_personagens():
        if ignorar_id is not None and str(p['id']) == str(ignorar_id):
            continue
        if chave_texto(p.get('nome')) == chave:
            return True
    return False

def tocar(personagem):
    personagem['atualizado_em'] = agora_iso()

def registrar_historico(personagem, tipo, **campos):
    historico = personagem.setdefault('historico', [])
    historico.append({'tipo': tipo, 'data': agora_iso(), **campos})
    if len(historico) > LIMITE_HISTORICO:
        del historico[:-LIMITE_HISTORICO]

def total_treino_minutos(personagem):
    total = 0
    for info in personagem.get('treinos', {}).values():
        if isinstance(info, dict):
            total += max(0, int(info.get('minutos', 0) or 0))
    return total

def get_treino(personagem, nome):
    chave = chave_texto(nome)
    for treino_id, info in personagem.get('treinos', {}).items():
        if chave_texto(info.get('nome', treino_id)) == chave:
            return (treino_id, info)
    return (None, None)

def meta_treino_minutos(info):
    if not isinstance(info, dict):
        return None
    meta = info.get('meta_minutos')
    try:
        meta = int(meta) if meta not in (None, '') else None
    except (TypeError, ValueError):
        return None
    return meta if meta and meta > 0 else None

def treino_concluido(info):
    meta = meta_treino_minutos(info)
    if meta is None:
        return False
    try:
        atual = int(info.get('minutos', 0) or 0)
    except (TypeError, ValueError):
        atual = 0
    return atual >= meta

def barra_treino(atual, meta, tamanho=14):
    if not meta or meta <= 0:
        return None
    proporcao = min(1.0, max(0.0, atual / meta))
    cheios = round(proporcao * tamanho)
    return '█' * cheios + '░' * (tamanho - cheios)

def definir_meta_treino(personagem, treino_id, meta_minutos):
    info = personagem.get('treinos', {}).get(str(treino_id))
    if not isinstance(info, dict):
        raise ValueError('Treinamento não encontrado.')
    if meta_minutos is None:
        info['meta_minutos'] = None
        tocar(personagem)
        return
    try:
        meta_minutos = int(meta_minutos)
    except (TypeError, ValueError):
        raise ValueError('Meta de treinamento inválida.')
    if meta_minutos <= 0:
        raise ValueError('A meta precisa ser maior que zero.')
    info['meta_minutos'] = meta_minutos
    tocar(personagem)

def corrigir_total_treino(personagem, treino_id, novo_total):
    info = personagem.get('treinos', {}).get(str(treino_id))
    if not isinstance(info, dict):
        raise ValueError('Treinamento não encontrado.')
    try:
        novo_total = int(novo_total)
    except (TypeError, ValueError):
        raise ValueError('Total de treinamento inválido.')
    if novo_total < 0:
        raise ValueError('O total de treinamento não pode ser negativo.')
    antigo_total = max(0, int(info.get('minutos', 0) or 0))
    info['minutos'] = novo_total
    finalidades = info.get('finalidades', {})
    if isinstance(finalidades, dict) and novo_total < antigo_total:
        itens = [dados for dados in finalidades.values() if isinstance(dados, dict)]
        soma = sum((max(0, int(dados.get('minutos', 0) or 0)) for dados in itens))
        if soma > novo_total and soma > 0:
            fator = novo_total / soma
            acumulado = 0
            for i, dados in enumerate(itens):
                anterior = max(0, int(dados.get('minutos', 0) or 0))
                if i == len(itens) - 1:
                    ajustado = max(0, novo_total - acumulado)
                else:
                    ajustado = max(0, round(anterior * fator))
                    ajustado = min(ajustado, max(0, novo_total - acumulado))
                    acumulado += ajustado
                dados['minutos'] = ajustado
    tocar(personagem)

def apagar_treino(personagem, treino_id):
    treino_id = str(treino_id)
    info = personagem.get('treinos', {}).pop(treino_id, None)
    if not isinstance(info, dict):
        raise ValueError('Treinamento não encontrado.')
    tocar(personagem)
    return info

def adicionar_treino(personagem, nome, minutos, finalidade=''):
    nome = nome.strip()
    finalidade = finalidade.strip()
    treino_id, info = get_treino(personagem, nome)
    if info is None:
        treino_id = re.sub('[^a-z0-9]+', '_', sem_acento(nome).lower()).strip('_') or 'treino'
        base = treino_id
        contador = 2
        while treino_id in personagem['treinos']:
            treino_id = f'{base}_{contador}'
            contador += 1
        info = {'nome': nome, 'minutos': 0, 'meta_minutos': None, 'finalidades': {}}
        personagem['treinos'][treino_id] = info
    atual = int(info.get('minutos', 0) or 0)
    novo_total = atual + minutos
    if novo_total < 0:
        raise ValueError(f"Esse ajuste deixaria **{info.get('nome', nome)}** com tempo negativo. Total atual: {formatar_horas(atual)}.")
    info['minutos'] = novo_total
    if finalidade:
        finais = info.setdefault('finalidades', {})
        final_id = chave_texto(finalidade)
        existente = None
        for chave, dados in finais.items():
            if chave_texto(dados.get('nome', chave)) == final_id:
                existente = dados
                break
        if existente is None:
            existente = {'nome': finalidade, 'minutos': 0}
            finais[finalidade] = existente
        novo_final = int(existente.get('minutos', 0) or 0) + minutos
        existente['minutos'] = max(0, novo_final)
    if info['minutos'] == 0:
        personagem['treinos'].pop(treino_id, None)

def total_conhecimentos(personagem):
    total = 0
    conhecimentos = personagem.get('conhecimentos', {})
    if not isinstance(conhecimentos, dict):
        return 0
    for categoria in CATEGORIAS_CONHECIMENTO:
        itens = conhecimentos.get(categoria, [])
        if isinstance(itens, list):
            total += len(itens)
    return total

def categorias_com_conhecimento(personagem):
    conhecimentos = personagem.get('conhecimentos', {})
    return sum((1 for categoria in CATEGORIAS_CONHECIMENTO if isinstance(conhecimentos.get(categoria), list) and conhecimentos.get(categoria)))

def adicionar_conhecimento(personagem, categoria, titulo, descricao='', fonte=''):
    if categoria not in CATEGORIAS_CONHECIMENTO:
        raise ValueError('Categoria de conhecimento inválida.')
    titulo = str(titulo or '').strip()
    descricao = str(descricao or '').strip()
    fonte = str(fonte or '').strip()
    if not titulo:
        raise ValueError('Informe o conhecimento.')
    conhecimentos = personagem.setdefault('conhecimentos', {})
    lista = conhecimentos.setdefault(categoria, [])
    lista.append({'titulo': titulo, 'descricao': descricao, 'fonte': fonte, 'adicionado_em': agora_iso()})
    tocar(personagem)

def parse_valor_monetario(texto, nome='Valor'):
    raw = str(texto or '').strip().replace(' ', '')
    if not raw:
        return Decimal('0')
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f'{nome} inválido. Use, por exemplo: 100, 25,50, +10 ou -7,25.')

def decimal_para_texto(valor):
    valor = Decimal(str(valor))
    if valor == 0:
        return '0'
    texto = format(valor.normalize(), 'f')
    return texto.rstrip('0').rstrip('.') if '.' in texto else texto

def formatar_valor_monetario(valor, simbolo=''):
    try:
        numero = Decimal(str(valor or '0'))
    except InvalidOperation:
        numero = Decimal('0')
    negativo = numero < 0
    numero = abs(numero)
    texto = f'{numero:,.2f}'
    inteiro, decimais = texto.split('.')
    inteiro = inteiro.replace(',', '.')
    if decimais == '00':
        texto = inteiro
    else:
        texto = f'{inteiro},{decimais}'
    if negativo:
        texto = '-' + texto
    simbolo = str(simbolo or '').strip()
    return f'{simbolo} {texto}' if simbolo else texto

def moeda_id_por_nome(nome):
    base = re.sub('[^a-z0-9]+', '_', sem_acento(nome).lower()).strip('_') or 'moeda'
    return base

def get_moeda(personagem, moeda_id):
    return personagem.get('monetario', {}).get(str(moeda_id))

def resumo_monetario(personagem, limite_itens=4):
    moedas = personagem.get('monetario', {})
    if not moedas:
        return 'Nenhuma moeda registrada.'
    linhas = []
    for _, info in list(moedas.items())[:limite_itens]:
        nome = info.get('nome', 'Moeda')
        simbolo = info.get('simbolo', '')
        maos = formatar_valor_monetario(info.get('maos', '0'), simbolo)
        banco = formatar_valor_monetario(info.get('banco', '0'), simbolo)
        linhas.append(f'• **{nome}** — mãos: {maos} • banco: {banco}')
    if len(moedas) > limite_itens:
        linhas.append(f'• … e mais {len(moedas) - limite_itens} moeda(s)')
    return '\n'.join(linhas)


def criar_embed_monetario(personagem):
    embed = discord.Embed(
        title=f"💰 Monetário — {personagem.get('nome', 'Personagem')}",
        description='Saldos separados por moeda e por local onde o dinheiro está guardado.',
        color=discord.Color.gold(),
    )
    moedas = personagem.get('monetario', {})
    if not moedas:
        embed.add_field(name='Sem registros', value='Nenhuma moeda foi cadastrada para este personagem.', inline=False)
        return embed
    for _, info in list(moedas.items())[:25]:
        simbolo = info.get('simbolo', '')
        maos = formatar_valor_monetario(info.get('maos', '0'), simbolo)
        banco = formatar_valor_monetario(info.get('banco', '0'), simbolo)
        try:
            total = Decimal(str(info.get('maos', '0'))) + Decimal(str(info.get('banco', '0')))
        except InvalidOperation:
            total = Decimal('0')
        embed.add_field(
            name=info.get('nome', 'Moeda'),
            value=f"**Em mãos:** {maos}\n**No banco:** {banco}\n**Total:** {formatar_valor_monetario(total, simbolo)}",
            inline=True,
        )
    embed.set_footer(text='Movimentações por soma/subtração entram no extrato. Correções administrativas só entram quando o ADM escolher registrar.')
    return embed


def registrar_extrato_monetario(personagem, moeda_id, tipo, autor_id=None, **campos):
    extrato = personagem.setdefault('monetario_extrato', [])
    extrato.append({'data': agora_iso(), 'moeda_id': str(moeda_id), 'tipo': tipo, 'autor_id': autor_id, **campos})
    if len(extrato) > LIMITE_EXTRATO_MONETARIO:
        del extrato[:-LIMITE_EXTRATO_MONETARIO]


def descricao_extrato_monetario(personagem, registro):
    info = get_moeda(personagem, registro.get('moeda_id')) or {}
    nome = info.get('nome', registro.get('moeda_nome', 'Moeda'))
    simbolo = info.get('simbolo', registro.get('simbolo', ''))
    tipo = registro.get('tipo')
    motivo = str(registro.get('motivo') or '').strip()
    if tipo == 'movimentacao':
        dm = Decimal(str(registro.get('delta_maos', '0')))
        db = Decimal(str(registro.get('delta_banco', '0')))
        partes = []
        if dm:
            partes.append(f"Mãos: **{'+' if dm > 0 else ''}{formatar_valor_monetario(dm, simbolo)}**")
        if db:
            partes.append(f"Banco: **{'+' if db > 0 else ''}{formatar_valor_monetario(db, simbolo)}**")
        texto = f"💸 **{nome}**\n" + (' • '.join(partes) if partes else 'Sem alteração de saldo.')
    elif tipo == 'correcao_admin':
        texto = (
            f"✏️ **Correção administrativa — {nome}**\n"
            f"Mãos: {formatar_valor_monetario(registro.get('antes_maos', '0'), simbolo)} → {formatar_valor_monetario(registro.get('depois_maos', '0'), simbolo)}\n"
            f"Banco: {formatar_valor_monetario(registro.get('antes_banco', '0'), simbolo)} → {formatar_valor_monetario(registro.get('depois_banco', '0'), simbolo)}"
        )
    else:
        texto = f"• {nome} — {tipo or 'registro'}"
    if motivo:
        texto += f"\nJustificativa: {motivo}"
    return texto


def criar_embed_extrato_monetario(personagem, pagina=0, por_pagina=8, admin=False):
    registros = list(reversed(personagem.get('monetario_extrato', [])))
    total_paginas = max(1, math.ceil(len(registros) / por_pagina))
    pagina = min(max(0, pagina), total_paginas - 1)
    inicio = pagina * por_pagina
    fatia = registros[inicio:inicio + por_pagina]
    embed = discord.Embed(
        title=f"📜 Extrato monetário — {personagem.get('nome', 'Personagem')}",
        description=f'Últimas movimentações monetárias. O Leon conserva até {LIMITE_EXTRATO_MONETARIO} registros por personagem.',
        color=discord.Color.gold(),
    )
    if not fatia:
        embed.add_field(name='Extrato', value='Ainda não há movimentações registradas.', inline=False)
    else:
        for registro in fatia:
            valor = descricao_extrato_monetario(personagem, registro)
            if admin and registro.get('autor_id'):
                valor += f"\nResponsável: <@{registro['autor_id']}>"
            embed.add_field(name=formatar_data_registro(registro.get('data')), value=limitar(valor, 1024), inline=False)
    embed.set_footer(text=f'Página {pagina + 1}/{total_paginas}')
    return embed, total_paginas

def usuario_tem_cargo_admin(bot, usuario, guild):
    if not guild:
        return False
    if usuario.id == guild.owner_id:
        return True
    cargos_admin = bot.config.get('cargos_admin', [])
    nomes = [role.name for role in getattr(usuario, 'roles', [])]
    return any((nome in nomes for nome in cargos_admin))


def pode_acessar_ficha_ou_subpainel(bot, interaction, personagem, usuario_id):
    """Permite acesso ao jogador atualmente vinculado OU a um administrador.

    O usuario_id identifica o dono para o qual a view foi criada. Isso evita que
    uma ficha persistente antiga continue acessível ao antigo dono depois de uma
    troca de vínculo.
    """
    if usuario_tem_cargo_admin(bot, interaction.user, interaction.guild):
        return True
    if personagem is None:
        return False
    dono_atual = str(personagem.get('jogador_id') or '')
    return dono_atual and str(interaction.user.id) == dono_atual and str(usuario_id) == dono_atual

def is_admin():

    async def predicate(ctx):
        return usuario_tem_cargo_admin(ctx.bot, ctx.author, ctx.guild)
    return commands.check(predicate)

def barra_xp(atual, meta, tamanho=16):
    if meta is None or meta <= 0:
        return None
    proporcao = min(1.0, max(0.0, atual / meta))
    cheios = round(proporcao * tamanho)
    return '█' * cheios + '░' * (tamanho - cheios)

def formatar_afiliacoes(personagem):
    afiliacoes = personagem.get('afiliacoes', [])
    if not afiliacoes:
        return '—'
    linhas = []
    for a in afiliacoes[:12]:
        if not isinstance(a, dict):
            continue
        nome = str(a.get('nome') or '').strip()
        cargo = str(a.get('cargo') or '').strip()
        if not nome:
            continue
        linhas.append(f'• **{nome}**' + (f' — {cargo}' if cargo else ''))
    return '\n'.join(linhas) if linhas else '—'

def formatar_top_treinos(personagem, limite_itens=5):
    treinos = []
    for treino_id, info in personagem.get('treinos', {}).items():
        if not isinstance(info, dict) or treino_concluido(info):
            continue
        minutos = int(info.get('minutos', 0) or 0)
        if minutos <= 0:
            continue
        treinos.append((minutos, info.get('nome', treino_id)))
    treinos.sort(reverse=True)
    if not treinos:
        return 'Nenhum treinamento em progresso.'
    return '\n'.join(f'• **{nome}** — {formatar_horas(minutos)}' for minutos, nome in treinos[:limite_itens])

def criar_embed_ficha(personagem, guild=None):
    nome = personagem.get('nome', 'Sem nome')
    jogador_id = personagem.get('jogador_id')
    embed = discord.Embed(title=f'📜 {nome}', description=f"Registro de personagem • ID **#{personagem.get('id')}**", color=discord.Color.blurple())
    if jogador_id:
        jogador_txt = f'<@{jogador_id}>'
    else:
        jogador_txt = 'Não vinculado'
    embed.add_field(name='👤 Jogador', value=jogador_txt, inline=True)
    embed.add_field(name='🏠 Residência fixa', value=limitar(texto_ou_traco(personagem.get('residencia_fixa')), 1024), inline=True)
    embed.add_field(name='📍 Localização atual', value=limitar(texto_ou_traco(personagem.get('localizacao_atual')), 1024), inline=False)
    embed.add_field(name='🕒 Data e hora no jogo', value=limitar(texto_ou_traco(personagem.get('data_hora_jogo')), 1024), inline=False)
    embed.add_field(name='🏛️ Afiliações', value=limitar(formatar_afiliacoes(personagem), 1024), inline=False)
    embed.add_field(name='💰 Monetário', value=limitar(resumo_monetario(personagem), 1024), inline=False)
    embed.add_field(name='🎯 Objetivo atual', value=limitar(texto_ou_traco(personagem.get('objetivo_atual')), 1024), inline=False)
    xp = int(personagem.get('xp', 0) or 0)
    meta = personagem.get('xp_meta')
    meta = int(meta) if meta not in (None, '') else None
    barra = barra_xp(xp, meta)
    if meta:
        porcentagem = min(100, max(0, round(xp / meta * 100)))
        xp_txt = f'**{xp:,} / {meta:,} XP**\n{barra} {porcentagem}%'.replace(',', '.')
    else:
        xp_txt = f'**{xp:,} XP**\nSem meta definida.'.replace(',', '.')
    total_treino = total_treino_minutos(personagem)
    embed.add_field(name='⭐ Experiência', value=xp_txt, inline=True)
    embed.add_field(name='⏱️ Treinamento acumulado', value=f'**{formatar_horas(total_treino)}**', inline=True)
    embed.add_field(name='📚 Principais treinos em progresso', value=limitar(formatar_top_treinos(personagem), 1024), inline=False)
    qtd_conhecimentos = total_conhecimentos(personagem)
    qtd_categorias = categorias_com_conhecimento(personagem)
    if qtd_conhecimentos:
        conhecimento_txt = f'**{qtd_conhecimentos}** registros em **{qtd_categorias}** categorias.'
    else:
        conhecimento_txt = 'Nenhum conhecimento registrado.'
    embed.add_field(name='🧠 Conhecimentos', value=conhecimento_txt, inline=False)
    embed.set_footer(text='C.U. e ficha de personagem são sistemas separados.')
    return embed

def formatar_data_registro(valor):
    try:
        dt = datetime.datetime.fromisoformat(str(valor))
        return dt.strftime('%d/%m/%Y • %H:%M')
    except (ValueError, TypeError):
        return str(valor or 'Data desconhecida')

def descricao_historico(registro):
    tipo = registro.get('tipo')
    if tipo == 'xp':
        delta = int(registro.get('delta', 0) or 0)
        sinal = '+' if delta >= 0 else ''
        texto = f'⭐ **{sinal}{delta} XP**'
        if registro.get('motivo'):
            texto += f"\n{registro['motivo']}"
        return texto
    if tipo == 'treino':
        minutos = int(registro.get('minutos', 0) or 0)
        sinal = '+' if minutos >= 0 else '−'
        texto = f"⏱️ **{sinal}{formatar_horas(abs(minutos))}** — {registro.get('treino', 'Treinamento')}"
        if registro.get('finalidade'):
            texto += f"\nPara: {registro['finalidade']}"
        return texto
    if tipo == 'localizacao':
        texto = f"📍 **{registro.get('localizacao', 'Localização atualizada')}**"
        if registro.get('data_hora_jogo'):
            texto += f"\n{registro['data_hora_jogo']}"
        if registro.get('nota'):
            texto += f"\n{registro['nota']}"
        return texto
    return f"• {tipo or 'Registro'}"

def criar_embed_historico(personagem, pagina=0, por_pagina=8):
    registros = list(reversed(personagem.get('historico', [])))
    total_paginas = max(1, math.ceil(len(registros) / por_pagina))
    pagina = min(max(0, pagina), total_paginas - 1)
    inicio = pagina * por_pagina
    fatia = registros[inicio:inicio + por_pagina]
    embed = discord.Embed(title=f"📜 Histórico — {personagem.get('nome')}", description=f'Histórico enxuto: XP, treinamentos e apenas localizações marcadas como relevantes. O Leon conserva no máximo as {LIMITE_HISTORICO} entradas mais recentes.', color=discord.Color.dark_teal())
    if not fatia:
        embed.add_field(name='Histórico', value='Ainda não há registros.', inline=False)
    else:
        for registro in fatia:
            embed.add_field(name=formatar_data_registro(registro.get('data')), value=limitar(descricao_historico(registro), 1024), inline=False)
    embed.set_footer(text=f'Página {pagina + 1}/{total_paginas}')
    return (embed, total_paginas)

def criar_embed_treinos(personagem, modo='andamento'):
    concluido = modo == 'concluidos'
    titulo = '✅ Treinamentos concluídos' if concluido else '⏱️ Treinamentos em progresso'
    descricao = (
        'Treinos que alcançaram a meta definida.' if concluido
        else 'Treinos sem meta ou que ainda não alcançaram a meta. Metas são opcionais.'
    )
    embed = discord.Embed(
        title=f"{titulo} — {personagem.get('nome')}",
        description=f"{descricao}\nTotal acumulado geral: **{formatar_horas(total_treino_minutos(personagem))}**",
        color=discord.Color.green(),
    )
    itens = []
    for treino_id, info in personagem.get('treinos', {}).items():
        if not isinstance(info, dict):
            continue
        minutos = int(info.get('minutos', 0) or 0)
        if minutos < 0 or treino_concluido(info) != concluido:
            continue
        itens.append((minutos, treino_id, info))
    itens.sort(reverse=True)
    if not itens:
        embed.add_field(
            name='Nenhum treinamento',
            value='Nenhum treinamento concluído.' if concluido else 'Nenhum treinamento em progresso.',
            inline=False,
        )
        return embed

    for minutos, treino_id, info in itens[:20]:
        meta = meta_treino_minutos(info)
        linhas = []
        if meta:
            porcentagem = min(100, max(0, round(minutos / meta * 100)))
            linhas.append(f"🎯 **{formatar_horas(minutos)} / {formatar_horas(meta)}**\n{barra_treino(minutos, meta)} {porcentagem}%")
            if minutos > meta:
                linhas.append(f'↳ **+{formatar_horas(minutos - meta)}** além da meta')
        else:
            linhas.append(f'⏱️ **{formatar_horas(minutos)}** • sem meta')
        finais = []
        for dados in info.get('finalidades', {}).values():
            if not isinstance(dados, dict):
                continue
            mins = int(dados.get('minutos', 0) or 0)
            if mins > 0:
                finais.append((mins, dados.get('nome', 'Finalidade')))
        finais.sort(reverse=True)
        if finais:
            linhas.append('')
            linhas.extend(f'• {nome}: {formatar_horas(mins)}' for mins, nome in finais[:8])
        else:
            linhas.append('Sem finalidade detalhada.')
        prefixo = '✅ ' if concluido else ''
        embed.add_field(name=f"{prefixo}{info.get('nome', treino_id)}", value=limitar('\n'.join(linhas), 1024), inline=False)
    if len(itens) > 20:
        embed.set_footer(text=f'Mostrando 20 de {len(itens)} treinamentos desta seção.')
    return embed

def criar_embed_conhecimentos(personagem, categoria=None, pagina=0):
    nome = personagem.get('nome', 'Sem nome')
    conhecimentos = personagem.get('conhecimentos', {})
    if categoria is None:
        embed = discord.Embed(title=f'🧠 Conhecimentos — {nome}', description='Escolha uma categoria abaixo. Mestre e jogador usam a mesma lista: qualquer conhecimento adicionado aparece para ambos.', color=discord.Color.purple())
        for cat in CATEGORIAS_CONHECIMENTO:
            itens = conhecimentos.get(cat, [])
            quantidade = len(itens) if isinstance(itens, list) else 0
            embed.add_field(name=cat, value=f'{quantidade} registro(s)', inline=True)
        embed.set_footer(text=f'Total: {total_conhecimentos(personagem)} conhecimentos')
        return (embed, 1)
    if categoria not in CATEGORIAS_CONHECIMENTO:
        categoria = 'Outros'
    itens = conhecimentos.get(categoria, [])
    if not isinstance(itens, list):
        itens = []
    total_paginas = max(1, math.ceil(len(itens) / CONHECIMENTOS_POR_PAGINA))
    pagina = min(max(0, pagina), total_paginas - 1)
    inicio = pagina * CONHECIMENTOS_POR_PAGINA
    fatia = itens[inicio:inicio + CONHECIMENTOS_POR_PAGINA]
    embed = discord.Embed(title=f'🧠 {categoria} — {nome}', description=f'{len(itens)} conhecimento(s) nesta categoria.', color=discord.Color.purple())
    if not fatia:
        embed.add_field(name='Nenhum conhecimento', value='Use **Adicionar conhecimento** para registrar o primeiro.', inline=False)
    else:
        for item in fatia:
            if not isinstance(item, dict):
                continue
            titulo = texto_ou_traco(item.get('titulo'))
            descricao = str(item.get('descricao') or '').strip() or 'Sem observação adicional.'
            fonte = str(item.get('fonte') or '').strip()
            valor = descricao
            if fonte:
                valor += f'\n\n**Fonte / como descobriu:** {fonte}'
            embed.add_field(name=limitar(titulo, 256), value=limitar(valor, 1024), inline=False)
    embed.set_footer(text=f'Página {pagina + 1}/{total_paginas} • Categoria: {categoria}')
    return (embed, total_paginas)

class HistoricoView(discord.ui.View):

    def __init__(self, bot, personagem_id, pagina=0, usuario_id=None, admin=False):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.pagina = pagina
        self.usuario_id = usuario_id
        self.admin = admin
        personagem = get_personagem(self.personagem_id)
        if personagem:
            _, total_paginas = criar_embed_historico(personagem, pagina)
        else:
            total_paginas = 1
        self.total_paginas = total_paginas
        anterior = discord.ui.Button(label='Anterior', style=discord.ButtonStyle.secondary, disabled=pagina <= 0)
        proxima = discord.ui.Button(label='Próxima', style=discord.ButtonStyle.secondary, disabled=pagina >= total_paginas - 1)
        voltar = discord.ui.Button(label='Voltar à ficha', style=discord.ButtonStyle.primary)

        async def anterior_cb(interaction):
            nova = max(0, self.pagina - 1)
            personagem_atual = get_personagem(self.personagem_id)
            embed, _ = criar_embed_historico(personagem_atual, nova)
            await interaction.response.edit_message(embed=embed, view=HistoricoView(self.bot, self.personagem_id, nova, self.usuario_id, self.admin))

        async def proxima_cb(interaction):
            nova = min(self.total_paginas - 1, self.pagina + 1)
            personagem_atual = get_personagem(self.personagem_id)
            embed, _ = criar_embed_historico(personagem_atual, nova)
            await interaction.response.edit_message(embed=embed, view=HistoricoView(self.bot, self.personagem_id, nova, self.usuario_id, self.admin))

        async def voltar_cb(interaction):
            personagem_atual = get_personagem(self.personagem_id)
            if not personagem_atual:
                return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
            if self.admin:
                view = AdminPersonagemView(self.bot, self.personagem_id)
            else:
                view = FichaPersonagemView(self.bot, self.personagem_id, self.usuario_id)
            await interaction.response.edit_message(embed=criar_embed_ficha(personagem_atual, interaction.guild), view=view)
        anterior.callback = anterior_cb
        proxima.callback = proxima_cb
        voltar.callback = voltar_cb
        self.add_item(anterior)
        self.add_item(proxima)
        self.add_item(voltar)

    async def interaction_check(self, interaction):
        personagem = get_personagem(self.personagem_id)
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, personagem, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este painel não pertence a você.', ephemeral=True)
            return False
        return True

class CategoriaConhecimentoSelect(discord.ui.Select):

    def __init__(self, bot, personagem_id, usuario_id, admin=False, categoria_atual=None):
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = usuario_id
        self.admin = admin
        options = []
        p = get_personagem(personagem_id)
        conhecimentos = p.get('conhecimentos', {}) if p else {}
        for categoria in CATEGORIAS_CONHECIMENTO:
            lista_categoria = conhecimentos.get(categoria, [])
            qtd = len(lista_categoria) if isinstance(lista_categoria, list) else 0
            options.append(discord.SelectOption(label=categoria, value=categoria, description=f'{qtd} conhecimento(s)', default=categoria == categoria_atual))
        super().__init__(placeholder='Escolha uma categoria', min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction):
        categoria = self.values[0]
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        embed, _ = criar_embed_conhecimentos(p, categoria, 0)
        await interaction.response.edit_message(content=None, embed=embed, view=ConhecimentosCategoriaView(self.bot, self.personagem_id, categoria, self.usuario_id, self.admin, pagina=0))

class ConhecimentosView(discord.ui.View):

    def __init__(self, bot, personagem_id, usuario_id, admin=False):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = usuario_id
        self.admin = admin
        self.add_item(CategoriaConhecimentoSelect(bot, personagem_id, usuario_id, admin))
        voltar = discord.ui.Button(label='Voltar à ficha', style=discord.ButtonStyle.secondary, emoji='◀️', row=1)

        async def voltar_cb(interaction):
            p = get_personagem(self.personagem_id)
            if not p:
                return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
            if self.admin:
                view = AdminPersonagemView(self.bot, self.personagem_id)
            else:
                view = FichaPersonagemView(self.bot, self.personagem_id, self.usuario_id)
            await interaction.response.edit_message(content=None, embed=criar_embed_ficha(p, interaction.guild), view=view)
        voltar.callback = voltar_cb
        self.add_item(voltar)

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
            return False
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este painel não pertence a você.', ephemeral=True)
            return False
        return True

class ConhecimentosCategoriaView(discord.ui.View):

    def __init__(self, bot, personagem_id, categoria, usuario_id, admin=False, pagina=0):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.categoria = categoria
        self.usuario_id = usuario_id
        self.admin = admin
        self.pagina = pagina
        p = get_personagem(personagem_id)
        if p:
            _, total_paginas = criar_embed_conhecimentos(p, categoria, pagina)
        else:
            total_paginas = 1
        self.total_paginas = total_paginas
        self.add_item(CategoriaConhecimentoSelect(bot, personagem_id, usuario_id, admin, categoria_atual=categoria))
        anterior = discord.ui.Button(label='Anterior', style=discord.ButtonStyle.secondary, disabled=pagina <= 0, row=1)
        proxima = discord.ui.Button(label='Próxima', style=discord.ButtonStyle.secondary, disabled=pagina >= total_paginas - 1, row=1)
        adicionar = discord.ui.Button(label='Adicionar conhecimento', style=discord.ButtonStyle.success, emoji='➕', row=1)
        categorias = discord.ui.Button(label='Categorias', style=discord.ButtonStyle.primary, emoji='🧠', row=1)
        voltar = discord.ui.Button(label='Voltar à ficha', style=discord.ButtonStyle.secondary, emoji='◀️', row=1)

        async def anterior_cb(interaction):
            nova = max(0, self.pagina - 1)
            atual = get_personagem(self.personagem_id)
            embed, _ = criar_embed_conhecimentos(atual, self.categoria, nova)
            await interaction.response.edit_message(embed=embed, view=ConhecimentosCategoriaView(self.bot, self.personagem_id, self.categoria, self.usuario_id, self.admin, nova))

        async def proxima_cb(interaction):
            nova = min(self.total_paginas - 1, self.pagina + 1)
            atual = get_personagem(self.personagem_id)
            embed, _ = criar_embed_conhecimentos(atual, self.categoria, nova)
            await interaction.response.edit_message(embed=embed, view=ConhecimentosCategoriaView(self.bot, self.personagem_id, self.categoria, self.usuario_id, self.admin, nova))

        async def adicionar_cb(interaction):
            await interaction.response.send_modal(AdicionarConhecimentoModal(self.bot, self.personagem_id, self.categoria, self.usuario_id, self.admin))

        async def categorias_cb(interaction):
            atual = get_personagem(self.personagem_id)
            embed, _ = criar_embed_conhecimentos(atual, None, 0)
            await interaction.response.edit_message(content=None, embed=embed, view=ConhecimentosView(self.bot, self.personagem_id, self.usuario_id, self.admin))

        async def voltar_cb(interaction):
            atual = get_personagem(self.personagem_id)
            if self.admin:
                view = AdminPersonagemView(self.bot, self.personagem_id)
            else:
                view = FichaPersonagemView(self.bot, self.personagem_id, self.usuario_id)
            await interaction.response.edit_message(content=None, embed=criar_embed_ficha(atual, interaction.guild), view=view)
        anterior.callback = anterior_cb
        proxima.callback = proxima_cb
        adicionar.callback = adicionar_cb
        categorias.callback = categorias_cb
        voltar.callback = voltar_cb
        for item in (anterior, proxima, adicionar, categorias, voltar):
            self.add_item(item)

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
            return False
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este painel não pertence a você.', ephemeral=True)
            return False
        return True

class FichaPersonagemView(discord.ui.View):

    def __init__(self, bot, personagem_id, usuario_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = int(usuario_id)

    async def interaction_check(self, interaction):
        personagem = get_personagem(self.personagem_id)
        permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, personagem, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Esta ficha não está vinculada à sua conta.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Treinamentos', style=discord.ButtonStyle.success, emoji='⏱️', custom_id='leon:ficha:treinos')
    async def treinos(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        await interaction.response.send_message(embed=criar_embed_treinos(personagem, 'andamento'), view=TreinosJogadorView(self.bot, self.personagem_id, self.usuario_id, 'andamento'), ephemeral=True)

    @discord.ui.button(label='Histórico', style=discord.ButtonStyle.secondary, emoji='📜', custom_id='leon:ficha:historico')
    async def historico(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        embed, _ = criar_embed_historico(personagem, 0)
        await interaction.response.send_message(embed=embed, view=HistoricoView(self.bot, self.personagem_id, 0, self.usuario_id, admin=False), ephemeral=True)

    @discord.ui.button(label='Conhecimentos', style=discord.ButtonStyle.primary, emoji='🧠', custom_id='leon:ficha:conhecimentos')
    async def conhecimentos(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        embed, _ = criar_embed_conhecimentos(personagem, None, 0)
        await interaction.response.send_message(embed=embed, view=ConhecimentosView(self.bot, self.personagem_id, self.usuario_id, admin=False), ephemeral=True)

    @discord.ui.button(label='Monetário', style=discord.ButtonStyle.secondary, emoji='💰', custom_id='leon:ficha:monetario')
    async def monetario(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        await interaction.response.send_message(embed=criar_embed_monetario(personagem), view=MonetarioJogadorView(self.bot, self.personagem_id, self.usuario_id), ephemeral=True)

    @discord.ui.button(label='Atualizar', style=discord.ButtonStyle.secondary, emoji='🔄', custom_id='leon:ficha:atualizar')
    async def atualizar(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        await interaction.response.edit_message(embed=criar_embed_ficha(personagem, interaction.guild), view=self)

class TreinosJogadorView(discord.ui.View):
    def __init__(self, bot, personagem_id, usuario_id, modo='andamento'):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = int(usuario_id)
        self.modo = modo

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este painel não pertence a você.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Em progresso', style=discord.ButtonStyle.success, emoji='⏱️')
    async def andamento(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(embed=criar_embed_treinos(p, 'andamento'), view=TreinosJogadorView(self.bot, self.personagem_id, self.usuario_id, 'andamento'))

    @discord.ui.button(label='Concluídos', style=discord.ButtonStyle.secondary, emoji='✅')
    async def concluidos(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(embed=criar_embed_treinos(p, 'concluidos'), view=TreinosJogadorView(self.bot, self.personagem_id, self.usuario_id, 'concluidos'))

    @discord.ui.button(label='Voltar à ficha', style=discord.ButtonStyle.secondary, emoji='◀️')
    async def voltar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(embed=criar_embed_ficha(p, interaction.guild), view=FichaPersonagemView(self.bot, self.personagem_id, self.usuario_id))


class VoltarFichaView(discord.ui.View):

    def __init__(self, bot, personagem_id, usuario_id, admin=False):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = usuario_id
        self.admin = admin

    async def interaction_check(self, interaction):
        personagem = get_personagem(self.personagem_id)
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, personagem, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este painel não pertence a você.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Voltar à ficha', style=discord.ButtonStyle.primary, emoji='◀️')
    async def voltar(self, interaction, button):
        personagem = get_personagem(self.personagem_id)
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        if self.admin:
            view = AdminPersonagemView(self.bot, self.personagem_id)
        else:
            view = FichaPersonagemView(self.bot, self.personagem_id, self.usuario_id)
        await interaction.response.edit_message(embed=criar_embed_ficha(personagem, interaction.guild), view=view)

class PersonagemSelect(discord.ui.Select):

    def __init__(self, bot, personagens, usuario_id, admin=False, pagina=0):
        self.bot = bot
        self.personagens = personagens
        self.usuario_id = usuario_id
        self.admin = admin
        self.pagina = pagina
        inicio = pagina * ITENS_POR_PAGINA
        fatia = personagens[inicio:inicio + ITENS_POR_PAGINA]
        options = []
        for p in fatia:
            descricao = texto_ou_traco(p.get('localizacao_atual'))
            options.append(discord.SelectOption(label=limitar(p.get('nome', 'Sem nome'), 100), value=str(p.get('id')), description=limitar(descricao, 100), emoji='📜'))
        super().__init__(placeholder='Escolha um personagem...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        personagem = get_personagem(self.values[0])
        if not personagem:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        if self.admin:
            view = AdminPersonagemView(self.bot, personagem['id'])
        else:
            view = FichaPersonagemView(self.bot, personagem['id'], self.usuario_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_ficha(personagem, interaction.guild), view=view)
        if not self.admin and interaction.message:
            registrar_painel_ficha(self.bot, interaction.message.id, personagem['id'], self.usuario_id)

class PersonagemSelectView(discord.ui.View):

    def __init__(self, bot, personagens, usuario_id, admin=False, pagina=0):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagens = personagens
        self.usuario_id = usuario_id
        self.admin = admin
        self.pagina = pagina
        self.total_paginas = max(1, math.ceil(len(personagens) / ITENS_POR_PAGINA))
        if personagens:
            self.add_item(PersonagemSelect(bot, personagens, usuario_id, admin, pagina))
        if self.total_paginas > 1:
            anterior = discord.ui.Button(label='Anterior', style=discord.ButtonStyle.secondary, disabled=pagina <= 0, row=1)
            proxima = discord.ui.Button(label='Próxima', style=discord.ButtonStyle.secondary, disabled=pagina >= self.total_paginas - 1, row=1)

            async def anterior_cb(interaction):
                await interaction.response.edit_message(content=f'Personagens — página {self.pagina}/{self.total_paginas}', view=PersonagemSelectView(self.bot, self.personagens, self.usuario_id, self.admin, self.pagina - 1))

            async def proxima_cb(interaction):
                await interaction.response.edit_message(content=f'Personagens — página {self.pagina + 2}/{self.total_paginas}', view=PersonagemSelectView(self.bot, self.personagens, self.usuario_id, self.admin, self.pagina + 1))
            anterior.callback = anterior_cb
            proxima.callback = proxima_cb
            self.add_item(anterior)
            self.add_item(proxima)

    async def interaction_check(self, interaction):
        # Neste menu ainda não existe um personagem selecionado, então a
        # autorização depende apenas de quem abriu o seletor ou de ser ADM.
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = interaction.user.id == self.usuario_id or usuario_tem_cargo_admin(
                self.bot, interaction.user, interaction.guild
            )
        if not permitido:
            await interaction.response.send_message('Este menu não pertence a você.', ephemeral=True)
            return False
        return True

class CriarPersonagemModal(discord.ui.Modal, title='Criar personagem'):

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.nome = discord.ui.TextInput(label='Nome', max_length=100)
        self.residencia = discord.ui.TextInput(label='Residência fixa', required=False, max_length=200)
        self.localizacao = discord.ui.TextInput(label='Localização atual', required=False, max_length=200)
        self.xp = discord.ui.TextInput(label='XP inicial', default='0', required=False, max_length=12)
        self.xp_meta = discord.ui.TextInput(label='Meta de XP', placeholder='vazio = sem meta', required=False, max_length=12)
        for campo in (self.nome, self.residencia, self.localizacao, self.xp, self.xp_meta):
            self.add_item(campo)

    async def on_submit(self, interaction):
        nome = self.nome.value.strip()
        if not nome:
            return await interaction.response.send_message('O personagem precisa ter nome.', ephemeral=True)
        if personagem_nome_existe(nome):
            return await interaction.response.send_message('Já existe um personagem com esse nome.', ephemeral=True)
        try:
            xp = parse_inteiro(self.xp.value or '0', 'XP', permitir_zero=True)
            meta = None
            if self.xp_meta.value.strip():
                meta = parse_inteiro(self.xp_meta.value, 'Meta de XP', permitir_zero=False)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        p = novo_personagem(nome)
        p['residencia_fixa'] = self.residencia.value.strip()
        p['localizacao_atual'] = self.localizacao.value.strip()
        p['xp'] = xp
        p['xp_meta'] = meta
        tocar(p)
        salvar_banco()
        await interaction.response.send_message(content='✅ Personagem criado. Use **Vincular jogador** se quiser associá-lo a uma conta do Discord.', embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, p['id']), ephemeral=True)

class EditarFichaModal(discord.ui.Modal, title='Editar ficha'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        p = get_personagem(personagem_id)
        self.nome = discord.ui.TextInput(label='Nome', default=p.get('nome', ''), max_length=100)
        self.residencia = discord.ui.TextInput(label='Residência fixa', default=p.get('residencia_fixa', ''), required=False, max_length=200)
        self.data_hora = discord.ui.TextInput(label='Data e hora no jogo', default=p.get('data_hora_jogo', ''), required=False, max_length=100)
        self.objetivo = discord.ui.TextInput(label='Objetivo atual', default=p.get('objetivo_atual', ''), required=False, style=discord.TextStyle.paragraph, max_length=500)
        self.xp_meta = discord.ui.TextInput(label='Meta de XP', default='' if p.get('xp_meta') is None else str(p.get('xp_meta')), placeholder='vazio = sem meta', required=False, max_length=12)
        for campo in (self.nome, self.residencia, self.data_hora, self.objetivo, self.xp_meta):
            self.add_item(campo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        nome = self.nome.value.strip()
        if not nome:
            return await interaction.response.send_message('O nome não pode ficar vazio.', ephemeral=True)
        if personagem_nome_existe(nome, ignorar_id=self.personagem_id):
            return await interaction.response.send_message('Já existe outro personagem com esse nome.', ephemeral=True)
        try:
            meta = None
            if self.xp_meta.value.strip():
                meta = parse_inteiro(self.xp_meta.value, 'Meta de XP', permitir_zero=False)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        p['nome'] = nome
        p['residencia_fixa'] = self.residencia.value.strip()
        p['data_hora_jogo'] = self.data_hora.value.strip()
        p['objetivo_atual'] = self.objetivo.value.strip()
        p['xp_meta'] = meta
        tocar(p)
        salvar_banco()
        await interaction.response.send_message('✅ Ficha atualizada. Essas alterações rotineiras não entram no histórico.', embed=criar_embed_ficha(p, interaction.guild), ephemeral=True)

class LocalizacaoModal(discord.ui.Modal, title='Atualizar localização'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        p = get_personagem(personagem_id)
        self.localizacao = discord.ui.TextInput(label='Localização atual', default=p.get('localizacao_atual', ''), max_length=250)
        self.data_hora = discord.ui.TextInput(label='Data e hora no jogo', default=p.get('data_hora_jogo', ''), required=False, max_length=100)
        self.registrar = discord.ui.TextInput(label='Guardar no histórico?', placeholder='sim ou não', default='não', required=False, max_length=5)
        self.nota = discord.ui.TextInput(label='Nota do deslocamento', placeholder='opcional; só é usada se guardar no histórico', required=False, style=discord.TextStyle.paragraph, max_length=300)
        for campo in (self.localizacao, self.data_hora, self.registrar, self.nota):
            self.add_item(campo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        local = self.localizacao.value.strip()
        data_hora = self.data_hora.value.strip()
        resposta = chave_texto(self.registrar.value)
        guardar = resposta in {'sim', 's', 'yes', 'y', '1'}
        p['localizacao_atual'] = local
        p['data_hora_jogo'] = data_hora
        if guardar:
            registrar_historico(p, 'localizacao', localizacao=local, data_hora_jogo=data_hora, nota=self.nota.value.strip())
        tocar(p)
        salvar_banco()
        mensagem = '✅ Localização atualizada'
        if guardar:
            mensagem += ' e guardada no histórico.'
        else:
            mensagem += '. Não foi adicionada ao histórico.'
        await interaction.response.send_message(mensagem, embed=criar_embed_ficha(p, interaction.guild), ephemeral=True)

class AjustarXPModal(discord.ui.Modal, title='Ajustar XP'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.valor = discord.ui.TextInput(label='Alteração de XP', placeholder='Ex.: 300 ou -150', max_length=12)
        self.motivo = discord.ui.TextInput(label='Motivo', placeholder='Ex.: missão concluída', required=False, style=discord.TextStyle.paragraph, max_length=300)
        self.add_item(self.valor)
        self.add_item(self.motivo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        try:
            delta = parse_inteiro(self.valor.value, 'XP', permitir_zero=False, permitir_negativo=True)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        atual = int(p.get('xp', 0) or 0)
        novo = atual + delta
        if novo < 0:
            return await interaction.response.send_message(f'Esse ajuste deixaria o XP negativo. XP atual: {atual}.', ephemeral=True)
        p['xp'] = novo
        registrar_historico(p, 'xp', delta=delta, motivo=self.motivo.value.strip())
        tocar(p)
        salvar_banco()
        sinal = '+' if delta > 0 else ''
        await interaction.response.send_message(f"✅ **{sinal}{delta} XP** para **{p['nome']}**. Total: **{novo} XP**.", embed=criar_embed_ficha(p, interaction.guild), ephemeral=True)

class RegistrarTreinoModal(discord.ui.Modal, title='Registrar treinamento'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.treino = discord.ui.TextInput(label='Treinamento / área', placeholder='Ex.: Latim, Esgrima, Controle Hormonal', max_length=100)
        self.tempo = discord.ui.TextInput(label='Tempo', placeholder='Ex.: 2, 1,5, 1:30, 45min ou -1h', max_length=20)
        self.finalidade = discord.ui.TextInput(label='Para quê?', placeholder='Ex.: magia de tradução, combate com florete', required=False, style=discord.TextStyle.paragraph, max_length=300)
        self.meta = discord.ui.TextInput(label='Meta de horas (opcional)', placeholder='Ex.: 20h, 40 ou 12:30. Vazio = mantém/sem meta', required=False, max_length=20)
        for campo in (self.treino, self.tempo, self.finalidade, self.meta):
            self.add_item(campo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        nome = self.treino.value.strip()
        if not nome:
            return await interaction.response.send_message('Informe o treinamento.', ephemeral=True)
        try:
            minutos = parse_tempo_treino(self.tempo.value)
            adicionar_treino(p, nome, minutos, self.finalidade.value)
            treino_id, info = get_treino(p, nome)
            if self.meta.value.strip():
                meta_minutos = parse_tempo_treino(self.meta.value)
                if meta_minutos <= 0:
                    raise ValueError('A meta precisa ser maior que zero.')
                definir_meta_treino(p, treino_id, meta_minutos)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        registrar_historico(p, 'treino', treino=nome, minutos=minutos, finalidade=self.finalidade.value.strip())
        tocar(p)
        salvar_banco()
        sinal = '+' if minutos > 0 else '−'
        _, info = get_treino(p, nome)
        meta = meta_treino_minutos(info) if info else None
        status = ''
        if info and treino_concluido(info):
            status = '\n✅ **Meta concluída.**'
        elif meta:
            status = f'\n🎯 Meta: **{formatar_horas(meta)}**.'
        await interaction.response.send_message(f"✅ **{sinal}{formatar_horas(abs(minutos))}** em **{nome}** para **{p['nome']}**.{status}", embed=criar_embed_treinos(p), ephemeral=True)

class DefinirMetaTreinoModal(discord.ui.Modal, title='Definir meta de treinamento'):

    def __init__(self, bot, personagem_id, treino_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.treino_id = str(treino_id)
        p = get_personagem(self.personagem_id)
        info = p.get('treinos', {}).get(self.treino_id, {}) if p else {}
        meta = meta_treino_minutos(info)
        self.meta = discord.ui.TextInput(label='Meta total', placeholder='Ex.: 20h, 40 ou 12:30. Digite REMOVER para ficar sem meta.', default=formatar_horas(meta) if meta else '', required=False, max_length=20)
        self.add_item(self.meta)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        info = p.get('treinos', {}).get(self.treino_id)
        if not isinstance(info, dict):
            return await interaction.response.send_message('Treinamento não encontrado.', ephemeral=True)
        texto = self.meta.value.strip()
        try:
            if not texto or chave_texto(texto) in {'remover', 'sem meta', 'nenhuma', 'nenhum'}:
                definir_meta_treino(p, self.treino_id, None)
                mensagem_meta = 'sem meta'
            else:
                meta = parse_tempo_treino(texto)
                if meta <= 0:
                    raise ValueError('A meta precisa ser maior que zero.')
                definir_meta_treino(p, self.treino_id, meta)
                mensagem_meta = formatar_horas(meta)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        salvar_banco()
        info = p.get('treinos', {}).get(self.treino_id, {})
        status = ' ✅ Concluído.' if treino_concluido(info) else ''
        await interaction.response.send_message(f"🎯 Meta de **{info.get('nome', 'Treinamento')}** definida como **{mensagem_meta}**.{status}", embed=criar_embed_treinos(p), ephemeral=True)

class CorrigirTreinoModal(discord.ui.Modal, title='Corrigir treinamento'):

    def __init__(self, bot, personagem_id, treino_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.treino_id = str(treino_id)
        p = get_personagem(self.personagem_id)
        info = p.get('treinos', {}).get(self.treino_id, {}) if p else {}
        self.total = discord.ui.TextInput(label='Total correto de horas', placeholder='Ex.: 12h30, 8 ou 1:45', default=formatar_horas(int(info.get('minutos', 0) or 0)), max_length=20)
        self.add_item(self.total)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        info = p.get('treinos', {}).get(self.treino_id)
        if not isinstance(info, dict):
            return await interaction.response.send_message('Treinamento não encontrado.', ephemeral=True)
        antigo = int(info.get('minutos', 0) or 0)
        try:
            texto = self.total.value.strip()
            if texto in {'0', '0h', '0min', '0:00'}:
                novo = 0
            else:
                novo = parse_tempo_treino(texto)
                if novo < 0:
                    raise ValueError('Informe o total correto, não um ajuste negativo.')
            corrigir_total_treino(p, self.treino_id, novo)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        salvar_banco()
        await interaction.response.send_message(f"✏️ **{info.get('nome', 'Treinamento')}** corrigido: **{formatar_horas(antigo)} → {formatar_horas(novo)}**.", embed=criar_embed_treinos(p), ephemeral=True)

class AdicionarConhecimentoModal(discord.ui.Modal, title='Adicionar conhecimento'):

    def __init__(self, bot, personagem_id, categoria, usuario_id, admin=False):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.categoria = categoria
        self.usuario_id = usuario_id
        self.admin = admin
        self.titulo_conhecimento = discord.ui.TextInput(label='Conhecimento', placeholder='Ex.: Marco Belladonna', max_length=150)
        self.descricao_conhecimento = discord.ui.TextInput(label='O que o personagem sabe?', placeholder='Ex.: É o irmão mais velho de Sophia Belladonna.', required=False, style=discord.TextStyle.paragraph, max_length=1000)
        self.fonte_conhecimento = discord.ui.TextInput(label='Fonte / como descobriu?', placeholder='Ex.: Alastair contou durante a aula.', required=False, style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.titulo_conhecimento)
        self.add_item(self.descricao_conhecimento)
        self.add_item(self.fonte_conhecimento)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            return await interaction.response.send_message('Você não pode alterar os conhecimentos deste personagem.', ephemeral=True)
        try:
            adicionar_conhecimento(p, self.categoria, self.titulo_conhecimento.value, self.descricao_conhecimento.value, self.fonte_conhecimento.value)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        salvar_banco()
        embed, _ = criar_embed_conhecimentos(p, self.categoria, 0)
        await interaction.response.send_message(f"✅ Conhecimento adicionado em **{self.categoria}** para **{p['nome']}**.", embed=embed, ephemeral=True)

class AdicionarAfiliacaoModal(discord.ui.Modal, title='Adicionar afiliação'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.nome = discord.ui.TextInput(label='Organização / afiliação', max_length=120)
        self.cargo = discord.ui.TextInput(label='Cargo, posto ou condição', placeholder='Ex.: Ferro, estudante, membro, capitão', required=False, max_length=120)
        self.add_item(self.nome)
        self.add_item(self.cargo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        nome = self.nome.value.strip()
        cargo = self.cargo.value.strip()
        if not nome:
            return await interaction.response.send_message('Informe a afiliação.', ephemeral=True)
        existentes = p.setdefault('afiliacoes', [])
        for a in existentes:
            if isinstance(a, dict) and chave_texto(a.get('nome')) == chave_texto(nome):
                a['nome'] = nome
                a['cargo'] = cargo
                tocar(p)
                salvar_banco()
                return await interaction.response.send_message('✅ Afiliação já existia e foi atualizada.', embed=criar_embed_ficha(p, interaction.guild), ephemeral=True)
        existentes.append({'nome': nome, 'cargo': cargo})
        tocar(p)
        salvar_banco()
        await interaction.response.send_message('✅ Afiliação adicionada. Afiliações não poluem o histórico.', embed=criar_embed_ficha(p, interaction.guild), ephemeral=True)

class ExcluirPersonagemModal(discord.ui.Modal, title='Excluir personagem'):

    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        p = get_personagem(personagem_id)
        self.confirmacao = discord.ui.TextInput(label=f"Digite EXCLUIR {p.get('nome', '')}"[:45], placeholder='Confirmação obrigatória', max_length=120)
        self.add_item(self.confirmacao)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        esperado = chave_texto(f"EXCLUIR {p.get('nome', '')}")
        if chave_texto(self.confirmacao.value) != esperado:
            return await interaction.response.send_message('Confirmação incorreta. Nada foi apagado.', ephemeral=True)
        nome = p.get('nome')
        banco['personagens'].pop(self.personagem_id, None)
        salvar_banco()
        await interaction.response.send_message(f'🗑️ **{nome}** foi excluído do registro de personagens.', ephemeral=True)

class VincularJogadorSelect(discord.ui.UserSelect):

    def __init__(self, bot, personagem_id):
        self.bot = bot
        self.personagem_id = str(personagem_id)
        super().__init__(placeholder='Escolha o jogador dono do personagem...', min_values=1, max_values=1)

    async def callback(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', view=None)
        membro = self.values[0]
        p['jogador_id'] = str(membro.id)
        tocar(p)
        salvar_banco()
        await interaction.response.edit_message(content=f"✅ **{p['nome']}** agora está vinculado a {membro.mention}.", embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

class VincularJogadorView(discord.ui.View):

    def __init__(self, bot, personagem_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.add_item(VincularJogadorSelect(bot, personagem_id))

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este menu.', ephemeral=True)
            return False
        return True

class RemoverAfiliacaoSelect(discord.ui.Select):

    def __init__(self, bot, personagem_id):
        self.bot = bot
        self.personagem_id = str(personagem_id)
        p = get_personagem(personagem_id)
        options = []
        for i, a in enumerate(p.get('afiliacoes', [])[:25]):
            if not isinstance(a, dict):
                continue
            options.append(discord.SelectOption(label=limitar(a.get('nome', 'Afiliação'), 100), value=str(i), description=limitar(a.get('cargo', 'Sem cargo'), 100)))
        super().__init__(placeholder='Escolha a afiliação para remover...', options=options)

    async def callback(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', view=None)
        indice = int(self.values[0])
        afiliacoes = p.get('afiliacoes', [])
        if indice < 0 or indice >= len(afiliacoes):
            return await interaction.response.send_message('Afiliação não encontrada.', ephemeral=True)
        removida = afiliacoes.pop(indice)
        tocar(p)
        salvar_banco()
        await interaction.response.edit_message(content=f"✅ Afiliação **{removida.get('nome', '')}** removida.", embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

class RemoverAfiliacaoView(discord.ui.View):

    def __init__(self, bot, personagem_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.add_item(RemoverAfiliacaoSelect(bot, personagem_id))

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este menu.', ephemeral=True)
            return False
        return True

class AfiliacoesAdminView(discord.ui.View):

    def __init__(self, bot, personagem_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Adicionar / atualizar', style=discord.ButtonStyle.success, emoji='➕')
    async def adicionar(self, interaction, button):
        await interaction.response.send_modal(AdicionarAfiliacaoModal(self.bot, self.personagem_id))

    @discord.ui.button(label='Remover', style=discord.ButtonStyle.danger, emoji='➖')
    async def remover(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('afiliacoes'):
            return await interaction.response.send_message('Esse personagem não possui afiliações.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha a afiliação que deseja remover:', embed=None, view=RemoverAfiliacaoView(self.bot, self.personagem_id))

    @discord.ui.button(label='Voltar', style=discord.ButtonStyle.secondary, emoji='◀️')
    async def voltar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

class TreinoAcaoSelect(discord.ui.Select):

    def __init__(self, bot, personagem_id, acao):
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.acao = acao
        p = get_personagem(self.personagem_id)
        options = []
        if p:
            treinos = []
            for treino_id, info in p.get('treinos', {}).items():
                if not isinstance(info, dict):
                    continue
                minutos = int(info.get('minutos', 0) or 0)
                meta = meta_treino_minutos(info)
                if meta:
                    descricao = f'{formatar_horas(minutos)} / {formatar_horas(meta)}'
                else:
                    descricao = f'{formatar_horas(minutos)} • sem meta'
                treinos.append((chave_texto(info.get('nome', treino_id)), treino_id, info, descricao))
            treinos.sort(key=lambda item: item[0])
            for _, treino_id, info, descricao in treinos[:25]:
                options.append(discord.SelectOption(label=limitar(info.get('nome', treino_id), 100), value=str(treino_id), description=limitar(descricao, 100), emoji='✅' if treino_concluido(info) else '⏱️'))
        super().__init__(placeholder='Escolha um treinamento...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        treino_id = self.values[0]
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        info = p.get('treinos', {}).get(treino_id)
        if not isinstance(info, dict):
            return await interaction.response.send_message('Treinamento não encontrado.', ephemeral=True)
        if self.acao == 'meta':
            return await interaction.response.send_modal(DefinirMetaTreinoModal(self.bot, self.personagem_id, treino_id))
        if self.acao == 'corrigir':
            return await interaction.response.send_modal(CorrigirTreinoModal(self.bot, self.personagem_id, treino_id))
        if self.acao == 'apagar':
            embed = discord.Embed(title='🗑️ Apagar treinamento', description=f"Você está prestes a apagar **{info.get('nome', 'Treinamento')}** da ficha atual.\n\nIsso remove o total, a meta e as finalidades desse treinamento. O histórico antigo da campanha não é reescrito.", color=discord.Color.red())
            return await interaction.response.edit_message(content=None, embed=embed, view=ConfirmarApagarTreinoView(self.bot, self.personagem_id, treino_id))

class SelecionarTreinoAcaoView(discord.ui.View):

    def __init__(self, bot, personagem_id, acao):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.acao = acao
        self.add_item(TreinoAcaoSelect(bot, personagem_id, acao))

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

class ConfirmarApagarTreinoView(discord.ui.View):

    def __init__(self, bot, personagem_id, treino_id):
        super().__init__(timeout=120)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.treino_id = str(treino_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Apagar treinamento', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def confirmar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        try:
            info = apagar_treino(p, self.treino_id)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        salvar_banco()
        await interaction.response.edit_message(content=f"🗑️ Treinamento **{info.get('nome', 'Treinamento')}** apagado.", embed=criar_embed_treinos(p), view=TreinosAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Cancelar', style=discord.ButtonStyle.secondary, emoji='✖️')
    async def cancelar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content='Exclusão cancelada.', embed=criar_embed_treinos(p), view=TreinosAdminView(self.bot, self.personagem_id))

class TreinosConcluidosAdminView(discord.ui.View):
    def __init__(self, bot, personagem_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Em progresso', style=discord.ButtonStyle.success, emoji='⏱️')
    async def andamento(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_treinos(p, 'andamento'), view=TreinosAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Voltar à ficha', style=discord.ButtonStyle.secondary, emoji='◀️')
    async def voltar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))


class TreinosAdminView(discord.ui.View):
    def __init__(self, bot, personagem_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Registrar horas', style=discord.ButtonStyle.success, emoji='➕', row=0)
    async def registrar(self, interaction, button):
        await interaction.response.send_modal(RegistrarTreinoModal(self.bot, self.personagem_id))

    @discord.ui.button(label='Definir meta', style=discord.ButtonStyle.primary, emoji='🎯', row=0)
    async def meta(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('treinos'):
            return await interaction.response.send_message('Esse personagem ainda não possui treinamentos.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha o treinamento cuja meta deseja alterar:', embed=None, view=SelecionarTreinoAcaoView(self.bot, self.personagem_id, 'meta'))

    @discord.ui.button(label='Corrigir', style=discord.ButtonStyle.secondary, emoji='✏️', row=0)
    async def corrigir(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('treinos'):
            return await interaction.response.send_message('Esse personagem ainda não possui treinamentos.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha o treinamento que deseja corrigir:', embed=None, view=SelecionarTreinoAcaoView(self.bot, self.personagem_id, 'corrigir'))

    @discord.ui.button(label='Apagar', style=discord.ButtonStyle.danger, emoji='🗑️', row=0)
    async def apagar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('treinos'):
            return await interaction.response.send_message('Esse personagem ainda não possui treinamentos.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha o treinamento que deseja apagar:', embed=None, view=SelecionarTreinoAcaoView(self.bot, self.personagem_id, 'apagar'))

    @discord.ui.button(label='Concluídos', style=discord.ButtonStyle.secondary, emoji='✅', row=1)
    async def concluidos(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_treinos(p, 'concluidos'), view=TreinosConcluidosAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Voltar', style=discord.ButtonStyle.secondary, emoji='◀️', row=1)
    async def voltar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

class AdicionarMoedaModal(discord.ui.Modal, title='Adicionar moeda'):
    def __init__(self, bot, personagem_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.nome_moeda = discord.ui.TextInput(label='Moeda', placeholder='Ex.: Coroa de Prata ou Libra Esterlina', max_length=80)
        self.simbolo = discord.ui.TextInput(label='Símbolo / abreviação', placeholder='Ex.: CP ou £', required=False, max_length=12)
        self.em_maos = discord.ui.TextInput(label='Valor inicial em mãos', default='0', required=False, max_length=30)
        self.no_banco = discord.ui.TextInput(label='Valor inicial no banco', default='0', required=False, max_length=30)
        for campo in (self.nome_moeda, self.simbolo, self.em_maos, self.no_banco):
            self.add_item(campo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        nome = self.nome_moeda.value.strip()
        if not nome:
            return await interaction.response.send_message('Informe o nome da moeda.', ephemeral=True)
        try:
            maos = parse_valor_monetario(self.em_maos.value, 'Valor em mãos')
            banco_val = parse_valor_monetario(self.no_banco.value, 'Valor no banco')
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if maos < 0 or banco_val < 0:
            return await interaction.response.send_message('O saldo inicial não pode ser negativo.', ephemeral=True)
        moedas = p.setdefault('monetario', {})
        for info in moedas.values():
            if chave_texto(info.get('nome')) == chave_texto(nome):
                return await interaction.response.send_message('Essa moeda já está cadastrada para o personagem.', ephemeral=True)
        moeda_id = moeda_id_por_nome(nome)
        base = moeda_id
        contador = 2
        while moeda_id in moedas:
            moeda_id = f'{base}_{contador}'
            contador += 1
        moedas[moeda_id] = {'nome': nome, 'simbolo': self.simbolo.value.strip(), 'maos': decimal_para_texto(maos), 'banco': decimal_para_texto(banco_val)}
        tocar(p)
        salvar_banco()
        await interaction.response.send_message(f"✅ **{nome}** adicionada ao monetário de **{p['nome']}**.", embed=criar_embed_monetario(p), ephemeral=True)


class AjustarMoedaModal(discord.ui.Modal, title='Movimentar saldo'):
    def __init__(self, bot, personagem_id, moeda_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.moeda_id = str(moeda_id)
        info = get_moeda(get_personagem(personagem_id) or {}, moeda_id) or {}
        nome = info.get('nome', 'Moeda')
        self.delta_maos = discord.ui.TextInput(label='Soma/subtração em mãos', placeholder='Ex.: +50, -12,50 ou 0', default='0', required=False, max_length=30)
        self.delta_banco = discord.ui.TextInput(label='Soma/subtração no banco', placeholder='Ex.: +100, -40 ou 0', default='0', required=False, max_length=30)
        self.observacao = discord.ui.TextInput(label='Motivo / observação', placeholder=f'Ex.: pagamento, depósito, saque — {nome}'[:100], required=False, max_length=200)
        for campo in (self.delta_maos, self.delta_banco, self.observacao):
            self.add_item(campo)

    async def on_submit(self, interaction):
        p = get_personagem(self.personagem_id)
        info = get_moeda(p or {}, self.moeda_id)
        if not p or not info:
            return await interaction.response.send_message('Moeda ou personagem não encontrado.', ephemeral=True)
        jogador_id = str(p.get('jogador_id') or '')
        eh_dono = str(interaction.user.id) == jogador_id
        eh_admin = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        if not (eh_dono or eh_admin):
            return await interaction.response.send_message('Você não pode movimentar este monetário.', ephemeral=True)
        try:
            d_maos = parse_valor_monetario(self.delta_maos.value, 'Alteração em mãos')
            d_banco = parse_valor_monetario(self.delta_banco.value, 'Alteração no banco')
            atual_maos = Decimal(str(info.get('maos', '0')))
            atual_banco = Decimal(str(info.get('banco', '0')))
        except (ValueError, InvalidOperation) as e:
            return await interaction.response.send_message(str(e) if str(e) else 'Saldo inválido.', ephemeral=True)
        if d_maos == 0 and d_banco == 0:
            return await interaction.response.send_message('Informe pelo menos uma soma ou subtração diferente de zero.', ephemeral=True)
        novo_maos = atual_maos + d_maos
        novo_banco = atual_banco + d_banco
        if novo_maos < 0 or novo_banco < 0:
            return await interaction.response.send_message('Essa movimentação deixaria o saldo negativo.', ephemeral=True)
        info['maos'] = decimal_para_texto(novo_maos)
        info['banco'] = decimal_para_texto(novo_banco)
        registrar_extrato_monetario(
            p, self.moeda_id, 'movimentacao', autor_id=interaction.user.id,
            delta_maos=decimal_para_texto(d_maos), delta_banco=decimal_para_texto(d_banco),
            antes_maos=decimal_para_texto(atual_maos), antes_banco=decimal_para_texto(atual_banco),
            depois_maos=decimal_para_texto(novo_maos), depois_banco=decimal_para_texto(novo_banco),
            motivo=self.observacao.value.strip(), moeda_nome=info.get('nome'), simbolo=info.get('simbolo', ''),
        )
        tocar(p)
        salvar_banco()
        await interaction.response.send_message(f"✅ Movimentação registrada em **{info.get('nome', 'Moeda')}** e adicionada ao extrato.", embed=criar_embed_monetario(p), ephemeral=True)


class CorrigirMoedaModal(discord.ui.Modal, title='Corrigir saldo — ADM'):
    def __init__(self, bot, personagem_id, moeda_id):
        super().__init__()
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.moeda_id = str(moeda_id)
        info = get_moeda(get_personagem(personagem_id) or {}, moeda_id) or {}
        self.em_maos = discord.ui.TextInput(label='Total correto em mãos', default=str(info.get('maos', '0')), max_length=30)
        self.no_banco = discord.ui.TextInput(label='Total correto no banco', default=str(info.get('banco', '0')), max_length=30)
        self.registrar = discord.ui.TextInput(label='Registrar no extrato? sim/não', default='não', required=False, max_length=5)
        self.justificativa = discord.ui.TextInput(label='Justificativa (opcional)', placeholder='Usada no extrato se você escolher registrar', required=False, max_length=250)
        self.simbolo = discord.ui.TextInput(label='Símbolo / abreviação', default=str(info.get('simbolo', '')), required=False, max_length=12)
        for campo in (self.em_maos, self.no_banco, self.registrar, self.justificativa, self.simbolo):
            self.add_item(campo)

    async def on_submit(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            return await interaction.response.send_message('Apenas administradores podem corrigir o valor absoluto.', ephemeral=True)
        p = get_personagem(self.personagem_id)
        info = get_moeda(p or {}, self.moeda_id)
        if not p or not info:
            return await interaction.response.send_message('Moeda ou personagem não encontrado.', ephemeral=True)
        try:
            maos = parse_valor_monetario(self.em_maos.value, 'Saldo em mãos')
            banco_val = parse_valor_monetario(self.no_banco.value, 'Saldo no banco')
            antes_maos = Decimal(str(info.get('maos', '0')))
            antes_banco = Decimal(str(info.get('banco', '0')))
        except (ValueError, InvalidOperation) as e:
            return await interaction.response.send_message(str(e) if str(e) else 'Saldo inválido.', ephemeral=True)
        if maos < 0 or banco_val < 0:
            return await interaction.response.send_message('Os saldos não podem ser negativos.', ephemeral=True)
        info['maos'] = decimal_para_texto(maos)
        info['banco'] = decimal_para_texto(banco_val)
        info['simbolo'] = self.simbolo.value.strip()
        registrar = chave_texto(self.registrar.value) in {'sim', 's', 'yes', 'y', '1'}
        if registrar:
            registrar_extrato_monetario(
                p, self.moeda_id, 'correcao_admin', autor_id=interaction.user.id,
                antes_maos=decimal_para_texto(antes_maos), antes_banco=decimal_para_texto(antes_banco),
                depois_maos=decimal_para_texto(maos), depois_banco=decimal_para_texto(banco_val),
                motivo=self.justificativa.value.strip(), moeda_nome=info.get('nome'), simbolo=info.get('simbolo', ''),
            )
        tocar(p)
        salvar_banco()
        aviso = ' A correção foi registrada no extrato.' if registrar else ' A correção foi silenciosa e não entrou no extrato.'
        await interaction.response.send_message('✅ Saldo absoluto corrigido.' + aviso, embed=criar_embed_monetario(p), ephemeral=True)


class MoedaSelect(discord.ui.Select):
    def __init__(self, bot, personagem_id, acao, usuario_id=None, admin=True):
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.acao = acao
        self.usuario_id = usuario_id
        self.admin = admin
        p = get_personagem(self.personagem_id)
        options = []
        if p:
            for moeda_id, info in list(p.get('monetario', {}).items())[:25]:
                options.append(discord.SelectOption(
                    label=limitar(info.get('nome', 'Moeda'), 100), value=str(moeda_id),
                    description=limitar(f"Mãos {formatar_valor_monetario(info.get('maos', '0'), info.get('simbolo', ''))} • Banco {formatar_valor_monetario(info.get('banco', '0'), info.get('simbolo', ''))}", 100),
                ))
        super().__init__(placeholder='Escolha uma moeda...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        moeda_id = self.values[0]
        if self.acao == 'ajustar':
            return await interaction.response.send_modal(AjustarMoedaModal(self.bot, self.personagem_id, moeda_id))
        if self.acao == 'corrigir':
            return await interaction.response.send_modal(CorrigirMoedaModal(self.bot, self.personagem_id, moeda_id))
        if self.acao == 'apagar':
            info = get_moeda(get_personagem(self.personagem_id) or {}, moeda_id) or {}
            embed = discord.Embed(title='🗑️ Apagar moeda', description=f"Apagar **{info.get('nome', 'Moeda')}** do personagem? O extrato antigo não será apagado.", color=discord.Color.red())
            return await interaction.response.edit_message(content=None, embed=embed, view=ConfirmarApagarMoedaView(self.bot, self.personagem_id, moeda_id))


class MoedaSelectView(discord.ui.View):
    def __init__(self, bot, personagem_id, acao, usuario_id=None, admin=True):
        super().__init__(timeout=300)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = usuario_id
        self.admin = admin
        self.add_item(MoedaSelect(bot, personagem_id, acao, usuario_id, admin))

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        if self.admin:
            permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild)
        else:
            permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Você não pode usar este menu.', ephemeral=True)
            return False
        return True


class ExtratoMonetarioView(discord.ui.View):
    def __init__(self, bot, personagem_id, usuario_id=None, pagina=0, admin=False):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = usuario_id
        self.pagina = pagina
        self.admin = admin
        p = get_personagem(personagem_id)
        _, self.total_paginas = criar_embed_extrato_monetario(p or {}, pagina, admin=admin)
        anterior = discord.ui.Button(label='Anterior', style=discord.ButtonStyle.secondary, disabled=pagina <= 0)
        proxima = discord.ui.Button(label='Próxima', style=discord.ButtonStyle.secondary, disabled=pagina >= self.total_paginas - 1)
        voltar = discord.ui.Button(label='Voltar ao monetário', style=discord.ButtonStyle.primary, emoji='◀️')
        async def anterior_cb(interaction):
            nova = max(0, self.pagina - 1)
            p2 = get_personagem(self.personagem_id)
            embed, _ = criar_embed_extrato_monetario(p2, nova, admin=self.admin)
            await interaction.response.edit_message(embed=embed, view=ExtratoMonetarioView(self.bot, self.personagem_id, self.usuario_id, nova, self.admin))
        async def proxima_cb(interaction):
            nova = min(self.total_paginas - 1, self.pagina + 1)
            p2 = get_personagem(self.personagem_id)
            embed, _ = criar_embed_extrato_monetario(p2, nova, admin=self.admin)
            await interaction.response.edit_message(embed=embed, view=ExtratoMonetarioView(self.bot, self.personagem_id, self.usuario_id, nova, self.admin))
        async def voltar_cb(interaction):
            p2 = get_personagem(self.personagem_id)
            view = MonetarioAdminView(self.bot, self.personagem_id) if self.admin else MonetarioJogadorView(self.bot, self.personagem_id, self.usuario_id)
            await interaction.response.edit_message(embed=criar_embed_monetario(p2), view=view)
        anterior.callback = anterior_cb
        proxima.callback = proxima_cb
        voltar.callback = voltar_cb
        self.add_item(anterior); self.add_item(proxima); self.add_item(voltar)

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        permitido = usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild) if self.admin else pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Você não pode abrir este extrato.', ephemeral=True)
            return False
        return True


class MonetarioJogadorView(discord.ui.View):
    def __init__(self, bot, personagem_id, usuario_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.usuario_id = int(usuario_id)

    async def interaction_check(self, interaction):
        p = get_personagem(self.personagem_id)
        permitido = pode_acessar_ficha_ou_subpainel(self.bot, interaction, p, self.usuario_id)
        if not permitido:
            await interaction.response.send_message('Este monetário não pertence ao seu personagem.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Movimentar saldo', style=discord.ButtonStyle.primary, emoji='💸')
    async def ajustar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('monetario'):
            return await interaction.response.send_message('Não há moedas cadastradas.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha a moeda para somar ou subtrair valores:', embed=None, view=MoedaSelectView(self.bot, self.personagem_id, 'ajustar', self.usuario_id, admin=False))

    @discord.ui.button(label='Extrato', style=discord.ButtonStyle.secondary, emoji='📜')
    async def extrato(self, interaction, button):
        p = get_personagem(self.personagem_id)
        embed, _ = criar_embed_extrato_monetario(p, 0, admin=False)
        await interaction.response.edit_message(embed=embed, view=ExtratoMonetarioView(self.bot, self.personagem_id, self.usuario_id, 0, False))

    @discord.ui.button(label='Atualizar', style=discord.ButtonStyle.secondary, emoji='🔄')
    async def atualizar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(embed=criar_embed_monetario(p), view=self)


class ConfirmarApagarMoedaView(discord.ui.View):
    def __init__(self, bot, personagem_id, moeda_id):
        super().__init__(timeout=120)
        self.bot = bot
        self.personagem_id = str(personagem_id)
        self.moeda_id = str(moeda_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem apagar moedas.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Apagar', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def apagar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        info = get_moeda(p or {}, self.moeda_id)
        if not p or not info:
            return await interaction.response.edit_message(content='Moeda não encontrada.', view=None)
        nome = info.get('nome', 'Moeda')
        p.get('monetario', {}).pop(self.moeda_id, None)
        tocar(p); salvar_banco()
        await interaction.response.edit_message(content=f'🗑️ **{nome}** foi removida do monetário.', embed=None, view=None)

    @discord.ui.button(label='Cancelar', style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_monetario(p), view=MonetarioAdminView(self.bot, self.personagem_id))


class MonetarioAdminView(discord.ui.View):
    def __init__(self, bot, personagem_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Adicionar moeda', style=discord.ButtonStyle.success, emoji='➕', row=0)
    async def adicionar(self, interaction, button):
        await interaction.response.send_modal(AdicionarMoedaModal(self.bot, self.personagem_id))

    @discord.ui.button(label='Movimentar saldo', style=discord.ButtonStyle.primary, emoji='💸', row=0)
    async def ajustar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('monetario'):
            return await interaction.response.send_message('Cadastre uma moeda primeiro.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha a moeda que deseja movimentar:', embed=None, view=MoedaSelectView(self.bot, self.personagem_id, 'ajustar', interaction.user.id, admin=True))

    @discord.ui.button(label='Corrigir valor absoluto', style=discord.ButtonStyle.secondary, emoji='✏️', row=0)
    async def corrigir(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('monetario'):
            return await interaction.response.send_message('Cadastre uma moeda primeiro.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha a moeda cujo valor absoluto deseja corrigir:', embed=None, view=MoedaSelectView(self.bot, self.personagem_id, 'corrigir', interaction.user.id, admin=True))

    @discord.ui.button(label='Apagar moeda', style=discord.ButtonStyle.danger, emoji='🗑️', row=0)
    async def apagar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p or not p.get('monetario'):
            return await interaction.response.send_message('Não há moedas para apagar.', ephemeral=True)
        await interaction.response.edit_message(content='Escolha a moeda que deseja apagar:', embed=None, view=MoedaSelectView(self.bot, self.personagem_id, 'apagar', interaction.user.id, admin=True))

    @discord.ui.button(label='Extrato', style=discord.ButtonStyle.secondary, emoji='📜', row=1)
    async def extrato(self, interaction, button):
        p = get_personagem(self.personagem_id)
        embed, _ = criar_embed_extrato_monetario(p, 0, admin=True)
        await interaction.response.edit_message(content=None, embed=embed, view=ExtratoMonetarioView(self.bot, self.personagem_id, interaction.user.id, 0, True))

    @discord.ui.button(label='Voltar', style=discord.ButtonStyle.secondary, emoji='◀️', row=1)
    async def voltar(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

class AdminPersonagemView(discord.ui.View):

    def __init__(self, bot, personagem_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.personagem_id = str(personagem_id)

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Editar ficha', style=discord.ButtonStyle.primary, emoji='✏️', row=0)
    async def editar(self, interaction, button):
        await interaction.response.send_modal(EditarFichaModal(self.bot, self.personagem_id))

    @discord.ui.button(label='Localização', style=discord.ButtonStyle.primary, emoji='📍', row=0)
    async def localizacao(self, interaction, button):
        await interaction.response.send_modal(LocalizacaoModal(self.bot, self.personagem_id))

    @discord.ui.button(label='XP', style=discord.ButtonStyle.success, emoji='⭐', row=0)
    async def xp(self, interaction, button):
        await interaction.response.send_modal(AjustarXPModal(self.bot, self.personagem_id))

    @discord.ui.button(label='Treinos', style=discord.ButtonStyle.success, emoji='⏱️', row=0)
    async def treino(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_treinos(p), view=TreinosAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Afiliações', style=discord.ButtonStyle.secondary, emoji='🏛️', row=0)
    async def afiliacoes(self, interaction, button):
        p = get_personagem(self.personagem_id)
        embed = discord.Embed(title=f"🏛️ Afiliações — {p.get('nome')}", description=formatar_afiliacoes(p), color=discord.Color.dark_gold())
        await interaction.response.edit_message(embed=embed, view=AfiliacoesAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Vincular jogador', style=discord.ButtonStyle.secondary, emoji='👤', row=1)
    async def vincular(self, interaction, button):
        await interaction.response.edit_message(content='Escolha o jogador que controla este personagem:', embed=None, view=VincularJogadorView(self.bot, self.personagem_id))

    @discord.ui.button(label='Desvincular', style=discord.ButtonStyle.secondary, emoji='🔓', row=1)
    async def desvincular(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        p['jogador_id'] = None
        tocar(p)
        salvar_banco()
        await interaction.response.edit_message(content='✅ Personagem desvinculado de qualquer conta do Discord.', embed=criar_embed_ficha(p, interaction.guild), view=AdminPersonagemView(self.bot, self.personagem_id))

    @discord.ui.button(label='Ver treinos', style=discord.ButtonStyle.secondary, emoji='📚', row=1)
    async def ver_treinos(self, interaction, button):
        p = get_personagem(self.personagem_id)
        await interaction.response.edit_message(content=None, embed=criar_embed_treinos(p, 'andamento'), view=TreinosAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Histórico', style=discord.ButtonStyle.secondary, emoji='📜', row=1)
    async def historico(self, interaction, button):
        p = get_personagem(self.personagem_id)
        embed, _ = criar_embed_historico(p, 0)
        await interaction.response.edit_message(embed=embed, view=HistoricoView(self.bot, self.personagem_id, 0, interaction.user.id, admin=True))

    @discord.ui.button(label='Conhecimentos', style=discord.ButtonStyle.primary, emoji='🧠', row=2)
    async def conhecimentos(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.edit_message(content='Personagem não encontrado.', embed=None, view=None)
        embed, _ = criar_embed_conhecimentos(p, None, 0)
        await interaction.response.edit_message(embed=embed, view=ConhecimentosView(self.bot, self.personagem_id, interaction.user.id, admin=True))

    @discord.ui.button(label='Monetário', style=discord.ButtonStyle.secondary, emoji='💰', row=2)
    async def monetario(self, interaction, button):
        p = get_personagem(self.personagem_id)
        if not p:
            return await interaction.response.send_message('Personagem não encontrado.', ephemeral=True)
        await interaction.response.edit_message(content=None, embed=criar_embed_monetario(p), view=MonetarioAdminView(self.bot, self.personagem_id))

    @discord.ui.button(label='Excluir', style=discord.ButtonStyle.danger, emoji='🗑️', row=1)
    async def excluir(self, interaction, button):
        await interaction.response.send_modal(ExcluirPersonagemModal(self.bot, self.personagem_id))

class AdminPersonagensPanel(discord.ui.View):

    def __init__(self, bot):
        super().__init__(timeout=600)
        self.bot = bot

    async def interaction_check(self, interaction):
        if not usuario_tem_cargo_admin(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message('Apenas administradores podem usar este painel.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Criar personagem', style=discord.ButtonStyle.success, emoji='✨')
    async def criar(self, interaction, button):
        await interaction.response.send_modal(CriarPersonagemModal(self.bot))

    @discord.ui.button(label='Gerenciar personagem', style=discord.ButtonStyle.primary, emoji='📜')
    async def gerenciar(self, interaction, button):
        personagens = todos_personagens()
        if not personagens:
            return await interaction.response.send_message('Ainda não há personagens cadastrados.', ephemeral=True)
        await interaction.response.send_message('Escolha o personagem que deseja administrar:', view=PersonagemSelectView(self.bot, personagens, interaction.user.id, admin=True), ephemeral=True)

    @discord.ui.button(label='Lista geral', style=discord.ButtonStyle.secondary, emoji='📋')
    async def lista(self, interaction, button):
        personagens = todos_personagens()
        if not personagens:
            return await interaction.response.send_message('Ainda não há personagens cadastrados.', ephemeral=True)
        linhas = []
        for p in personagens[:80]:
            dono = f"<@{p['jogador_id']}>" if p.get('jogador_id') else 'sem jogador'
            local = texto_ou_traco(p.get('localizacao_atual'))
            linhas.append(f"**#{p['id']} — {p['nome']}** • {dono}\n↳ {local}")
        descricao = '\n'.join(linhas)
        if len(personagens) > 80:
            descricao += f'\n\n… e mais {len(personagens) - 80}.'
        embed = discord.Embed(title='📋 Personagens cadastrados', description=limitar(descricao, 4000), color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class PersonagensCog(commands.Cog, name='Personagens'):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='personagens')
    async def personagens(self, ctx):
        personagens = personagens_do_jogador(ctx.author.id)
        if not personagens:
            return await ctx.send('Você ainda não possui nenhum personagem vinculado à sua conta. Um administrador pode vinculá-lo pelo painel **!admpersonagens**.')
        if len(personagens) == 1:
            p = personagens[0]
            mensagem = await ctx.send(embed=criar_embed_ficha(p, ctx.guild), view=FichaPersonagemView(self.bot, p['id'], ctx.author.id))
            registrar_painel_ficha(self.bot, mensagem.id, p['id'], ctx.author.id)
            return mensagem
        await ctx.send('Escolha qual dos seus personagens deseja abrir:', view=PersonagemSelectView(self.bot, personagens, ctx.author.id, admin=False))

    @commands.command(name='personagem')
    async def personagem(self, ctx, *, consulta: Optional[str]=None):
        admin = usuario_tem_cargo_admin(self.bot, ctx.author, ctx.guild)
        candidatos = todos_personagens() if admin else personagens_do_jogador(ctx.author.id)
        if not consulta:
            if len(candidatos) == 1:
                p = candidatos[0]
            elif not candidatos:
                return await ctx.send('Nenhum personagem disponível para você.')
            else:
                return await ctx.send('Você possui mais de um personagem. Use **!personagens** para escolher ou **!personagem nome**.')
        else:
            p, erro = buscar_personagem(consulta, candidatos)
            if not p:
                return await ctx.send(erro)
        if admin:
            view = AdminPersonagemView(self.bot, p['id'])
        else:
            view = FichaPersonagemView(self.bot, p['id'], ctx.author.id)
        mensagem = await ctx.send(embed=criar_embed_ficha(p, ctx.guild), view=view)
        if not admin:
            registrar_painel_ficha(self.bot, mensagem.id, p['id'], ctx.author.id)

    @commands.command(name='admpersonagens')
    @is_admin()
    async def admpersonagens(self, ctx):
        embed = discord.Embed(title='⚙️ Administração de Personagens', description='Este módulo é independente do C.U. e da economia.\n\nCrie personagens, vincule jogadores, acompanhe XP, treinamento, localização, data/hora do jogo, residência, afiliações e conhecimentos.', color=discord.Color.dark_teal())
        embed.add_field(name='Histórico enxuto', value=f'XP e treino são registrados; localização só entra quando você marcar **sim**. O limite é de {LIMITE_HISTORICO} registros por personagem.', inline=False)
        await ctx.send(embed=embed, view=AdminPersonagensPanel(self.bot))

    @commands.command(name='admpersonagem')
    @is_admin()
    async def admpersonagem(self, ctx, *, consulta: str):
        p, erro = buscar_personagem(consulta)
        if not p:
            return await ctx.send(erro)
        await ctx.send(embed=criar_embed_ficha(p, ctx.guild), view=AdminPersonagemView(self.bot, p['id']))

async def setup(bot: commands.Bot):
    await bot.add_cog(PersonagensCog(bot))
    restaurados = restaurar_paineis_ficha(bot)
    print(f'Módulo de Personagens carregado. Fichas persistentes restauradas: {restaurados}.')

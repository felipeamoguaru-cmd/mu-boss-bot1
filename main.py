import discord
from discord.ext import commands, tasks
from discord import ui
from datetime import datetime, timedelta
import pytz
import json
import os

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise Exception("DISCORD_TOKEN não definido!")

CANAL_ID = 1489651007343427705
FUSO_HORARIO = "America/Sao_Paulo"
CARGO_AVISO = "CaçadorDeBoss"
PAINEL_MSG_ID = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tz = pytz.timezone(FUSO_HORARIO)

BOSSES_FIXOS = {
    "Death Bone": {"local": "Shadow Abyss", "horarios": ["21:45", "00:45", "03:45", "06:45"], "emoji": "💀"},
    "Cursed Santa": {"local": "Devias", "horarios": ["02:35", "08:35", "14:35", "20:35"], "emoji": "🎅"},
}

BOSSES_TIMER = {
    "Kharzul":       {"local": "Ruined Lorencia",    "horas_min": 7,  "horas_max": 8,  "emoji": "👹"},
    "Vescrya":       {"local": "Ruined Devias",      "horas_min": 7,  "horas_max": 8,  "emoji": "🦇"},
    "Muggron":       {"local": "Crywolf / Barracks", "horas_min": 7,  "horas_max": 8,  "emoji": "👑"},
    "Blue Goblin":   {"local": "Shadow Abyss",       "horas_min": 10, "horas_max": 11, "emoji": "👺"},
    "Red Goblin":    {"local": "Shadow Abyss",       "horas_min": 10, "horas_max": 11, "emoji": "🔴"},
    "Yellow Goblin": {"local": "Shadow Abyss",       "horas_min": 10, "horas_max": 11, "emoji": "🟡"},
}

ARQUIVO_DADOS  = "boss_timers.json"
ARQUIVO_PAINEL = "painel_id.json"


def carregar_dados():
    if os.path.exists(ARQUIVO_DADOS):
        with open(ARQUIVO_DADOS, "r") as f:
            return json.load(f)
    return {}


def salvar_dados(dados):
    with open(ARQUIVO_DADOS, "w") as f:
        json.dump(dados, f, indent=2)


def carregar_painel_id():
    if os.path.exists(ARQUIVO_PAINEL):
        with open(ARQUIVO_PAINEL, "r") as f:
            return json.load(f).get("msg_id")
    return None


def salvar_painel_id(msg_id):
    with open(ARQUIVO_PAINEL, "w") as f:
        json.dump({"msg_id": msg_id}, f)


def proximo_respawn_fixo(boss_nome):
    agora = datetime.now(tz)
    proximos = []
    for h in BOSSES_FIXOS[boss_nome]["horarios"]:
        hora, minuto = map(int, h.split(":"))
        dt = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if dt <= agora:
            dt += timedelta(days=1)
        proximos.append(dt)
    return min(proximos)


def tempo_faltando(dt_futuro):
    agora = datetime.now(tz)
    diff = dt_futuro - agora
    total_segundos = int(diff.total_seconds())
    if total_segundos <= 0:
        return "**AGORA!** 🚨"
    horas   = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    segundos = total_segundos % 60
    if horas > 0:
        return f"{horas}h {minutos}min"
    elif minutos > 0:
        return f"{minutos}min {segundos}s"
    else:
        return f"{segundos}s"


def get_cargo_mention(guild):
    cargo = discord.utils.get(guild.roles, name=CARGO_AVISO)
    return cargo.mention if cargo else "@here"


def build_painel_embed():
    agora = datetime.now(tz)
    embed = discord.Embed(
        title="📡 Painel de Bosses — MU Dream Online",
        description=f"🕐 Atualizado em: `{agora.strftime('%H:%M:%S')}`",
        color=discord.Color.dark_gold()
    )

    texto_fixos = ""
    for nome, info in BOSSES_FIXOS.items():
        proximo = proximo_respawn_fixo(nome)
        faltando = tempo_faltando(proximo)
        texto_fixos += f"{info['emoji']} **{nome}** — {info['local']}\n"
        texto_fixos += f"   ⏰ `{proximo.strftime('%H:%M')}` · {faltando}\n\n"
    embed.add_field(name="🕐 Horário Fixo", value=texto_fixos or "—", inline=False)

    dados = carregar_dados()
    texto_timer = ""
    for nome, info in BOSSES_TIMER.items():
        if nome in dados:
            dt_respawn = datetime.fromisoformat(dados[nome]).astimezone(tz)
            faltando = tempo_faltando(dt_respawn)
            texto_timer += f"{info['emoji']} **{nome}** — {info['local']}\n"
            texto_timer += f"   ⏰ `{dt_respawn.strftime('%H:%M')}` · {faltando}\n\n"
        else:
            texto_timer += f"{info['emoji']} **{nome}** — {info['local']}\n"
            texto_timer += f"   ❓ Use `!morreu {nome}` ou clique em **Registrar Morte**\n\n"
    embed.add_field(name="⏱️ Timer após morte", value=texto_timer or "—", inline=False)
    embed.set_footer(text="Este painel atualiza sozinho a cada 30s")
    return embed


def registrar_morte(boss_nome, horario_morte: datetime):
    """Salva o respawn calculado a partir do horário da morte."""
    info = BOSSES_TIMER[boss_nome]
    dt_respawn = horario_morte + timedelta(hours=info["horas_min"])
    dados = carregar_dados()
    dados[boss_nome] = dt_respawn.isoformat()
    salvar_dados(dados)
    return dt_respawn


# ─── Modal: horário manual ───────────────────────────────────

class ModalHorarioManual(ui.Modal, title="Registrar horário da morte"):
    horario = ui.TextInput(
        label="Horário que o boss morreu (HH:MM)",
        placeholder="Ex: 18:37",
        min_length=4,
        max_length=5,
    )

    def __init__(self, boss_nome: str):
        super().__init__()
        self.boss_nome = boss_nome

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hora, minuto = map(int, self.horario.value.strip().split(":"))
        except ValueError:
            await interaction.response.send_message(
                "❌ Formato inválido. Use `HH:MM`, ex: `18:37`", ephemeral=True
            )
            return

        agora = datetime.now(tz)
        horario_morte = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)

        # Se o horário informado for "no futuro", assume que foi ontem
        if horario_morte > agora:
            horario_morte -= timedelta(days=1)

        dt_respawn = registrar_morte(self.boss_nome, horario_morte)
        info = BOSSES_TIMER[self.boss_nome]

        embed = discord.Embed(
            title=f"{info['emoji']} {self.boss_nome} foi derrotado!",
            color=discord.Color.red()
        )
        embed.add_field(name="📍 Local",           value=info["local"],                        inline=True)
        embed.add_field(name="💀 Morreu às",        value=horario_morte.strftime("%H:%M"),      inline=True)
        embed.add_field(name="⏰ Próximo respawn",  value=dt_respawn.strftime("%H:%M"),         inline=True)
        embed.add_field(name="⏱️ Tempo",            value=f"~{info['horas_min']}h - {info['horas_max']}h", inline=True)
        embed.set_footer(text=f"Registrado às {agora.strftime('%H:%M:%S')} (horário ajustado)")
        await interaction.response.send_message(embed=embed)


# ─── View: botões Matei agora / Matei em outro horário ───────

class ViewMorreu(ui.View):
    def __init__(self, boss_nome: str):
        super().__init__(timeout=120)
        self.boss_nome = boss_nome

    @ui.button(label="✅ Matei agora", style=discord.ButtonStyle.green)
    async def matei_agora(self, interaction: discord.Interaction, button: ui.Button):
        agora = datetime.now(tz)
        dt_respawn = registrar_morte(self.boss_nome, agora)
        info = BOSSES_TIMER[self.boss_nome]

        embed = discord.Embed(
            title=f"{info['emoji']} {self.boss_nome} foi derrotado!",
            color=discord.Color.red()
        )
        embed.add_field(name="📍 Local",          value=info["local"],                        inline=True)
        embed.add_field(name="⏰ Próximo respawn", value=dt_respawn.strftime("%H:%M"),         inline=True)
        embed.add_field(name="⏱️ Tempo",           value=f"~{info['horas_min']}h - {info['horas_max']}h", inline=True)
        embed.set_footer(text=f"Registrado às {agora.strftime('%H:%M:%S')}")
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)

    @ui.button(label="🕐 Matei em outro horário", style=discord.ButtonStyle.blurple)
    async def matei_outro_horario(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ModalHorarioManual(self.boss_nome))
        self.stop()

    @ui.button(label="❌ Cancelar", style=discord.ButtonStyle.grey)
    async def cancelar(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Cancelado.", embed=None, view=None)
        self.stop()


# ─── Comandos ────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} está online!")
    verificar_respawns.start()
    atualizar_painel.start()


@bot.command(name="lista")
async def listar_bosses(ctx):
    await ctx.send(embed=build_painel_embed())


@bot.command(name="painel")
async def criar_painel(ctx):
    global PAINEL_MSG_ID
    msg = await ctx.send(embed=build_painel_embed())
    PAINEL_MSG_ID = msg.id
    salvar_painel_id(msg.id)
    await ctx.message.delete()


@bot.command(name="morreu")
async def boss_morreu(ctx, *, nome_boss: str = None):
    if nome_boss is None:
        nomes = "\n".join([f"• `{n}`" for n in BOSSES_TIMER.keys()])
        await ctx.send(f"❗ Informe o nome do boss. Opções:\n{nomes}")
        return

    boss_encontrado = None
    for nome in BOSSES_TIMER:
        if nome.lower() == nome_boss.lower():
            boss_encontrado = nome
            break

    if not boss_encontrado:
        await ctx.send(f"❌ Boss `{nome_boss}` não encontrado. Use `!lista`.")
        return

    info = BOSSES_TIMER[boss_encontrado]
    embed = discord.Embed(
        title=f"{info['emoji']} {boss_encontrado}",
        description="Quando o boss morreu?",
        color=discord.Color.orange()
    )
    embed.add_field(name="📍 Local", value=info["local"], inline=True)
    embed.add_field(name="⏱️ Respawn", value=f"~{info['horas_min']}h - {info['horas_max']}h", inline=True)

    await ctx.send(embed=embed, view=ViewMorreu(boss_encontrado))


@bot.command(name="resetar")
async def resetar_boss(ctx, *, nome_boss: str = None):
    if nome_boss is None:
        await ctx.send("❗ Informe o nome do boss. Ex: `!resetar Blue Goblin`")
        return

    boss_encontrado = None
    for nome in BOSSES_TIMER:
        if nome.lower() == nome_boss.lower():
            boss_encontrado = nome
            break

    if not boss_encontrado:
        await ctx.send(f"❌ Boss `{nome_boss}` não encontrado nos bosses de timer.")
        return

    dados = carregar_dados()
    if boss_encontrado not in dados:
        await ctx.send(f"⚠️ **{boss_encontrado}** não tinha timer registrado.")
        return

    del dados[boss_encontrado]
    salvar_dados(dados)
    info = BOSSES_TIMER[boss_encontrado]
    await ctx.send(f"✅ {info['emoji']} Timer do **{boss_encontrado}** foi removido com sucesso!")


@bot.command(name="quando")
async def quando_respawn(ctx, *, nome_boss: str = None):
    if nome_boss is None:
        await ctx.send("❗ Ex: `!quando Red Dragon`")
        return

    for nome, info in BOSSES_FIXOS.items():
        if nome.lower() == nome_boss.lower():
            proximo = proximo_respawn_fixo(nome)
            faltando = tempo_faltando(proximo)
            embed = discord.Embed(title=f"{info['emoji']} {nome}", color=discord.Color.blue())
            embed.add_field(name="📍 Local",          value=info["local"],              inline=True)
            embed.add_field(name="⏰ Próximo respawn", value=proximo.strftime("%H:%M"), inline=True)
            embed.add_field(name="⏱️ Faltam",          value=faltando,                  inline=True)
            embed.add_field(name="🗓️ Todos os horários", value=" | ".join(info["horarios"]), inline=False)
            await ctx.send(embed=embed)
            return

    for nome, info in BOSSES_TIMER.items():
        if nome.lower() == nome_boss.lower():
            dados = carregar_dados()
            if nome not in dados:
                await ctx.send(f"❓ Use `!morreu {nome}` quando ele morrer.")
                return
            dt_respawn = datetime.fromisoformat(dados[nome]).astimezone(tz)
            faltando = tempo_faltando(dt_respawn)
            embed = discord.Embed(title=f"{info['emoji']} {nome}", color=discord.Color.orange())
            embed.add_field(name="📍 Local",             value=info["local"],                   inline=True)
            embed.add_field(name="⏰ Respawn estimado",  value=dt_respawn.strftime("%H:%M"),    inline=True)
            embed.add_field(name="⏱️ Faltam",             value=faltando,                        inline=True)
            await ctx.send(embed=embed)
            return

    await ctx.send(f"❌ Boss `{nome_boss}` não encontrado.")


@bot.command(name="ajuda")
async def ajuda(ctx):
    embed = discord.Embed(title="🤖 Comandos do Boss Bot", color=discord.Color.purple())
    embed.add_field(name="`!lista`",          value="Ver todos os bosses e próximos respawns", inline=False)
    embed.add_field(name="`!painel`",         value="Criar painel ao vivo que se atualiza sozinho", inline=False)
    embed.add_field(name="`!quando <nome>`",  value="Ver quando um boss específico vai nascer", inline=False)
    embed.add_field(name="`!morreu <nome>`",  value="Registrar morte — escolha 'agora' ou informe o horário", inline=False)
    embed.add_field(name="`!resetar <nome>`", value="Remover timer registrado errado", inline=False)
    embed.add_field(name="`!ajuda`",          value="Mostrar esta mensagem", inline=False)
    await ctx.send(embed=embed)


# ─── Tasks ───────────────────────────────────────────────────

avisos_enviados = set()

@tasks.loop(seconds=30)
async def verificar_respawns():
    canal = bot.get_channel(CANAL_ID)
    if canal is None:
        return
    agora = datetime.now(tz)
    mencao = get_cargo_mention(canal.guild)

    for nome, info in BOSSES_FIXOS.items():
        proximo = proximo_respawn_fixo(nome)
        diff_minutos = (proximo - agora).total_seconds() / 60
        for aviso in [10, 5]:
            chave = f"{nome}_{proximo.strftime('%H%M')}_{aviso}min"
            if aviso - 0.5 <= diff_minutos <= aviso + 0.5 and chave not in avisos_enviados:
                avisos_enviados.add(chave)
                embed = discord.Embed(
                    title=f"⚠️ {info['emoji']} {nome} em {aviso} minutos!",
                    description=f"📍 Vá para **{info['local']}**!",
                    color=discord.Color.yellow() if aviso == 10 else discord.Color.red()
                )
                embed.add_field(name="⏰ Hora do respawn", value=proximo.strftime("%H:%M"), inline=True)
                embed.set_footer(text=f"Horário atual: {agora.strftime('%H:%M')}")
                await canal.send(mencao, embed=embed)

        chave_spawn = f"{nome}_{proximo.strftime('%H%M')}_spawn"
        if -0.5 <= diff_minutos <= 0.5 and chave_spawn not in avisos_enviados:
            avisos_enviados.add(chave_spawn)
            embed = discord.Embed(
                title=f"🚨 {info['emoji']} {nome} NASCEU AGORA!",
                description=f"📍 Corra para **{info['local']}**!",
                color=discord.Color.green()
            )
            await canal.send(mencao, embed=embed)

    dados = carregar_dados()
    for nome, info in BOSSES_TIMER.items():
        if nome not in dados:
            continue
        dt_respawn = datetime.fromisoformat(dados[nome]).astimezone(tz)
        diff_minutos = (dt_respawn - agora).total_seconds() / 60
        for aviso in [10, 5]:
            chave = f"{nome}_{dt_respawn.isoformat()}_{aviso}min"
            if aviso - 0.5 <= diff_minutos <= aviso + 0.5 and chave not in avisos_enviados:
                avisos_enviados.add(chave)
                embed = discord.Embed(
                    title=f"⚠️ {info['emoji']} {nome} em {aviso} minutos!",
                    description=f"📍 Vá para **{info['local']}**!",
                    color=discord.Color.yellow() if aviso == 10 else discord.Color.red()
                )
                embed.add_field(name="⏰ Respawn estimado", value=dt_respawn.strftime("%H:%M"), inline=True)
                await canal.send(mencao, embed=embed)

        chave_spawn = f"{nome}_{dt_respawn.isoformat()}_spawn"
        if -0.5 <= diff_minutos <= 0.5 and chave_spawn not in avisos_enviados:
            avisos_enviados.add(chave_spawn)
            embed = discord.Embed(
                title=f"🚨 {info['emoji']} {nome} DEVE NASCER AGORA!",
                description=f"📍 Vá para **{info['local']}**!",
                color=discord.Color.green()
            )
            await canal.send(mencao, embed=embed)
            del dados[nome]
            salvar_dados(dados)


@tasks.loop(seconds=30)
async def atualizar_painel():
    global PAINEL_MSG_ID
    if PAINEL_MSG_ID is None:
        PAINEL_MSG_ID = carregar_painel_id()
    if PAINEL_MSG_ID is None:
        return
    canal = bot.get_channel(CANAL_ID)
    if canal is None:
        return
    try:
        msg = await canal.fetch_message(PAINEL_MSG_ID)
        await msg.edit(embed=build_painel_embed())
    except discord.NotFound:
        PAINEL_MSG_ID = None
        salvar_painel_id(None)


bot.run(TOKEN)

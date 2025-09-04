import sqlite3
import datetime
import re
import os
import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)

# Configura o logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TOKEN")

# --- BANCO DE DADOS ---
def iniciar_banco():
    os.makedirs("fotos", exist_ok=True)
    try:
        conn = sqlite3.connect("study.db")
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT,
            tipo TEXT,
            detalhes TEXT,
            minutos INTEGER,
            foto TEXT,
            datahora TEXT
        )
        """)
        cur.execute("PRAGMA table_info(atividades)")
        colunas = [info[1] for info in cur.fetchall()]
        if 'foto' not in colunas:
            cur.execute("ALTER TABLE atividades ADD COLUMN foto TEXT")
        
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Erro ao iniciar o banco de dados: {e}")
    finally:
        if conn:
            conn.close()

def salvar_atividade(usuario, tipo, detalhes, minutos, foto=None):
    try:
        conn = sqlite3.connect("study.db")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO atividades (usuario, tipo, detalhes, minutos, foto, datahora) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario, tipo, detalhes, minutos, foto, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Erro ao salvar atividade no banco de dados: {e}")
        return False
    finally:
        if conn:
            conn.close()

def pegar_timeline(limit=10):
    rows = []
    try:
        conn = sqlite3.connect("study.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT usuario, tipo, detalhes, minutos, foto, datahora FROM atividades ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar timeline do banco de dados: {e}")
    finally:
        if conn:
            conn.close()
    return rows

def pegar_ranking_semana():
    rows = []
    try:
        inicio_semana = (datetime.datetime.now() - datetime.timedelta(days=datetime.datetime.now().weekday())).strftime("%Y-%m-%d")
        conn = sqlite3.connect("study.db")
        cur = conn.cursor()
        cur.execute("""
            SELECT usuario, SUM(minutos) as total_min
            FROM atividades
            WHERE date(datahora) >= date(?)
            GROUP BY usuario
            ORDER BY total_min DESC
        """, (inicio_semana,))
        rows = cur.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar ranking do banco de dados: {e}")
    finally:
        if conn:
            conn.close()
    return rows

# --- CONVERSOR DE TEMPO ---
def texto_para_minutos(texto):
    try:
        texto = texto.lower().strip()
        h, m = 0, 0

        match = re.match(r"(\d+):(\d+)", texto)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
        else:
            horas = re.search(r"(\d+)\s*h", texto)
            minutos = re.search(r"(\d+)\s*m", texto)
            if horas:
                h = int(horas.group(1))
            if minutos:
                m = int(minutos.group(1))
            if not horas and not minutos:
                m = int(texto)
        return h * 60 + m
    except (ValueError, TypeError):
        return 0

# --- CONVERSATION HANDLERS ---
ESTUDO_TEMAS, ESTUDO_TEMPOS, ESTUDO_FOTOS = range(3)
LEITURA_LIVROS, LEITURA_TEMPOS, LEITURA_FOTOS = range(3)

# Trilhas predefinidas
TRILHA_ESTUDO = ["Matemática", "Física", "Química", "Programação", "Inglês"]
TRILHA_LEITURA = ["Livro1", "Livro2", "Livro3"]

async def estudo_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Digite os temas estudados separados por linha (ex: Matemática, Física)...")
    return ESTUDO_TEMAS

async def estudo_temas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    linhas = update.message.text.split("\n")
    context.user_data["temas"] = linhas
    await update.message.reply_text("⏱ Agora digite o tempo correspondente para cada tema, mesma ordem (ex: 1h20min, 45min)")
    return ESTUDO_TEMPOS

async def estudo_tempos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    linhas = update.message.text.split("\n")
    temas = context.user_data.get("temas")
    if len(linhas) != len(temas):
        await update.message.reply_text("⚠️ O número de tempos não bate com o número de temas. Tente novamente.")
        return ESTUDO_TEMPOS
    
    minutos_lista = [texto_para_minutos(l) for l in linhas]
    context.user_data["minutos_lista"] = minutos_lista
    await update.message.reply_text("📸 Quer enviar uma foto do estudo? Se sim, envie agora. Caso não, digite /pular")
    return ESTUDO_FOTOS

async def estudo_fotos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    temas = context.user_data.get("temas")
    minutos_lista = context.user_data.get("minutos_lista")

    if not temas or not minutos_lista:
        await update.message.reply_text("❌ Ocorreu um erro. Por favor, reinicie o registro com /estudo.")
        return ConversationHandler.END

    if update.message.photo:
        try:
            foto_file = await update.message.photo[-1].get_file()
            caminho = f"fotos/{user}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            await foto_file.download_to_drive(caminho)
            for i, tema in enumerate(temas):
                salvar_atividade(user, "Estudo", tema, minutos_lista[i], caminho)
            await update.message.reply_text("✅ Estudos registrados com foto!")
        except Exception as e:
            logger.error(f"Erro ao salvar foto ou registrar atividade: {e}")
            await update.message.reply_text("❌ Ocorreu um erro ao salvar a foto e registrar os estudos. Tente novamente.")
    else:
        await update.message.reply_text("❌ Nenhuma foto detectada. Envie uma foto ou digite /pular para pular.")
        return ESTUDO_FOTOS

    return ConversationHandler.END

async def pular_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    temas = context.user_data.get("temas") or context.user_data.get("livros")
    minutos_lista = context.user_data.get("minutos_lista")
    
    if not temas or not minutos_lista:
        await update.message.reply_text("❌ Ocorreu um erro. Por favor, reinicie o registro.")
        return ConversationHandler.END

    tipo = "Estudo" if "temas" in context.user_data else "Leitura"
    for i, tema in enumerate(temas):
        salvar_atividade(user, tipo, tema, minutos_lista[i])
    await update.message.reply_text(f"✅ {tipo}s registrados sem foto!")
    return ConversationHandler.END

# --- Leitura ---
async def leitura_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📘 Digite os livros/material de leitura separados por linha:")
    return LEITURA_LIVROS

async def leitura_livros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    linhas = update.message.text.split("\n")
    context.user_data["livros"] = linhas
    await update.message.reply_text("⏱ Agora digite o tempo correspondente para cada leitura, mesma ordem (ex: 30min, 1h)")
    return LEITURA_TEMPOS

async def leitura_tempos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    linhas = update.message.text.split("\n")
    livros = context.user_data.get("livros")
    if len(linhas) != len(livros):
        await update.message.reply_text("⚠️ O número de tempos não bate com o número de livros. Tente novamente.")
        return LEITURA_TEMPOS
    
    minutos_lista = [texto_para_minutos(l) for l in linhas]
    context.user_data["minutos_lista"] = minutos_lista
    await update.message.reply_text("📸 Quer enviar uma foto da leitura? Se sim, envie agora. Caso não, digite /pular")
    return LEITURA_FOTOS

async def leitura_fotos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    livros = context.user_data.get("livros")
    minutos_lista = context.user_data.get("minutos_lista")

    if not livros or not minutos_lista:
        await update.message.reply_text("❌ Ocorreu um erro. Por favor, reinicie o registro com /leitura.")
        return ConversationHandler.END

    if update.message.photo:
        try:
            foto_file = await update.message.photo[-1].get_file()
            caminho = f"fotos/{user}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            await foto_file.download_to_drive(caminho)
            for i, livro in enumerate(livros):
                salvar_atividade(user, "Leitura", livro, minutos_lista[i], caminho)
            await update.message.reply_text("✅ Leituras registradas com foto!")
        except Exception as e:
            logger.error(f"Erro ao salvar foto ou registrar atividade: {e}")
            await update.message.reply_text("❌ Ocorreu um erro ao salvar a foto e registrar as leituras. Tente novamente.")
    else:
        await update.message.reply_text("❌ Nenhuma foto detectada. Envie uma foto ou digite /pular para pular.")
        return LEITURA_FOTOS

    return ConversationHandler.END

# --- Cancelar ---
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Registro cancelado.")
    return ConversationHandler.END

# --- Timeline, Ranking e Trilha ---
async def timeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = pegar_timeline()
    if not rows:
        await update.message.reply_text("📭 Ainda não há registros na timeline.")
        return
    
    texto = "📚 Timeline (últimos registros):\n\n"
    for r in rows:
        texto += f"{r[0]} → {r[1]}: {r[2]} | ⏱ {r[3]}min | 🕒 {r[5]}\n"
        if r[4]:
            try:
                with open(r[4], "rb") as foto:
                    await update.message.reply_photo(photo=foto)
            except FileNotFoundError:
                logger.warning(f"Foto não encontrada no caminho: {r[4]}")
                # Envia apenas o texto, já que a foto não está disponível
    
    await update.message.reply_text(texto)

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = pegar_ranking_semana()
    if not rows:
        await update.message.reply_text("📭 Ainda não há registros no ranking desta semana.")
        return
    texto = "🏆 Ranking da Semana:\n\n"
    for i, r in enumerate(rows, 1):
        horas = r[1] // 60
        minutos = r[1] % 60
        texto += f"{i}. {r[0]} → {horas}h{minutos:02d}\n"
    await update.message.reply_text(texto)

async def trilha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    
    rows = []
    try:
        conn = sqlite3.connect("study.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT tipo, detalhes, minutos, foto, datahora FROM atividades WHERE usuario=? ORDER BY id DESC",
            (user,)
        )
        rows = cur.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Erro ao buscar trilha do usuário {user}: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao carregar sua trilha. Tente novamente mais tarde.")
        return
    finally:
        if conn:
            conn.close()

    if not rows:
        await update.message.reply_text("📭 Você ainda não registrou nenhuma atividade.")
        return

    texto = f"📚 Sua trilha de estudos, {user}:\n\n"
    total_minutos = 0
    for r in rows:
        texto += f"{r[0]}: {r[1]} | ⏱ {r[2]} min | 🕒 {r[4]}\n"
        total_minutos += r[2]
        if r[3]:
            try:
                with open(r[3], "rb") as foto:
                    await update.message.reply_photo(photo=foto)
            except FileNotFoundError:
                logger.warning(f"Foto não encontrada no caminho: {r[3]}")

    texto += f"\n⏱ Total de estudo: {total_minutos // 60}h {total_minutos % 60}min"
    await update.message.reply_text(texto)


# --- Menu ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✏️ Registrar Estudo", callback_data="estudo")],
        [InlineKeyboardButton("📘 Registrar Leitura", callback_data="leitura")],
        [InlineKeyboardButton("🕒 Timeline", callback_data="timeline")],
        [InlineKeyboardButton("🏆 Ranking", callback_data="ranking")],
        [InlineKeyboardButton("📖 Minha Trilha", callback_data="trilha")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📚 Bem-vindo ao Miltinho 2.0!\nEscolha uma opção abaixo:", reply_markup=reply_markup)

async def botao_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "estudo":
        await query.edit_message_text("✏️ Digite /estudo para registrar um estudo.")
    elif query.data == "leitura":
        await query.edit_message_text("📘 Digite /leitura para registrar uma leitura.")
    elif query.data == "timeline":
        await timeline(update, context)
    elif query.data == "ranking":
        await ranking(update, context)
    elif query.data == "trilha":
        await trilha(update, context)

# --- MAIN ---
def main():
    iniciar_banco()
    app = Application.builder().token(TOKEN).build()
    
    # ... (restante do código main) ...
    commands = [
        BotCommand("start", "Iniciar e ver o menu principal"),
        BotCommand("estudo", "Registrar estudo"),
        BotCommand("leitura", "Registrar leitura"),
        BotCommand("timeline", "Ver timeline de atividades"),
        BotCommand("ranking", "Ver ranking semanal"),
        BotCommand("trilha", "Ver sua trilha individual"),
        BotCommand("cancelar", "Cancelar registro atual"),
        BotCommand("pular", "Pular envio de foto")
    ]
    app.bot.set_my_commands(commands)
    
    # Conversas
    conv_estudo = ConversationHandler(
        entry_points=[CommandHandler("estudo", estudo_inicio)],
        states={
            ESTUDO_TEMAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, estudo_temas)],
            ESTUDO_TEMPOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, estudo_tempos)],
            ESTUDO_FOTOS: [
                MessageHandler(filters.PHOTO, estudo_fotos),
                CommandHandler("pular", pular_foto)
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )

    conv_leitura = ConversationHandler(
        entry_points=[CommandHandler("leitura", leitura_inicio)],
        states={
            LEITURA_LIVROS: [MessageHandler(filters.TEXT & ~filters.COMMAND, leitura_livros)],
            LEITURA_TEMPOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, leitura_tempos)],
            LEITURA_FOTOS: [
                MessageHandler(filters.PHOTO, leitura_fotos),
                CommandHandler("pular", pular_foto)
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_estudo)
    app.add_handler(conv_leitura)
    app.add_handler(CommandHandler("timeline", timeline))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("trilha", trilha))
    app.add_handler(CommandHandler("pular", pular_foto))
    app.add_handler(CallbackQueryHandler(botao_handler))

    print("Miltinho rodando...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
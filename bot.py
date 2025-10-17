import discord
from discord import app_commands
from discord.ext import commands
import json, os, datetime, asyncio, logging

# ========= CONFIG =========
CONFIG_PATH = "config.json"
DEFAULT_CONFIG = {
    "TOKEN": "your-token-here",
    "ADMIN_ROLE_ID": 1422528388756799489,
    "EMBED_COLOR": 0x5865F2
}

if not os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    print("🛠 Created config.json.  Please edit it with your bot token and admin role ID before running again.")
    exit()

config = json.load(open(CONFIG_PATH))
TOKEN = config["TOKEN"]
ADMIN_ROLE_ID = config["ADMIN_ROLE_ID"]
EMBED_COLOR = config["EMBED_COLOR"]

# ========= LOGGING =========
logging.basicConfig(filename="bot.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# ========= DISCORD SETUP =========
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ========= DATABASE =========
DB_FILE = "containers.json"
if not os.path.exists(DB_FILE):
    json.dump([], open(DB_FILE, "w"))
def load_db(): return json.load(open(DB_FILE))
def save_db(data): json.dump(data, open(DB_FILE, "w"), indent=2)

# ========= UTILITIES =========
async def is_admin(interaction):
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

def get_container(cid):
    for c in load_db():
        if c["id"] == cid:
            return c
    return None

# ========= COMMANDS =========
@bot.tree.command(name="deploy", description="(Admin) Mock deploy a VPS for a user.")
async def deploy(interaction: discord.Interaction, user: discord.User, os: str, ram: str, cpu: str):
    if not await is_admin(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)

    # --- mock container creation ---
    cid = f"mock_{int(datetime.datetime.utcnow().timestamp())}"
    data = load_db()
    item = {
        "id": cid,
        "user_id": str(user.id),
        "os": os,
        "ram": ram,
        "cpu": cpu,
        "ssh": f"ssh user@mockhost -p 22  # fake SSH for {cid}",
        "created": datetime.datetime.utcnow().isoformat()
    }
    data.append(item)
    save_db(data)
    embed = discord.Embed(
        title="✅ VPS Deployed (mock)",
        description=f"User: {user.mention}\nOS: {os}\nRAM: {ram}\nCPU: {cpu}\nSSH:\n```{item['ssh']}```",
        color=0x00FF00)
    await interaction.followup.send(embed=embed)
    logging.info(f"Deployed {cid} for {user} ({user.id})")

@bot.tree.command(name="list", description="Show your VPS list (mock).")
async def list_vps(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    data = [c for c in load_db() if c["user_id"] == uid]
    if not data:
        await interaction.response.send_message("📋 You have no VPS (mock).", ephemeral=True)
        return
    e = discord.Embed(title=f"📋 VPS for {interaction.user}", color=EMBED_COLOR)
    for c in data:
        e.add_field(name=f"{c['os']} | {c['id']}",
                    value=f"{c['ram']} RAM • {c['cpu']} CPU\nSSH: `{c['ssh']}`",
                    inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="list-all", description="(Admin) List all VPS (mock).")
async def list_all(interaction: discord.Interaction):
    if not await is_admin(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    data = load_db()
    if not data:
        await interaction.response.send_message("No VPS found.", ephemeral=True)
        return
    e = discord.Embed(title="📋 All VPS (mock)", color=EMBED_COLOR)
    for c in data:
        e.add_field(name=f"{c['os']} | {c['id']}",
                    value=f"User <@{c['user_id']}> • {c['ram']} RAM • {c['cpu']} CPU",
                    inline=False)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="delete-vps", description="(Admin) Delete a VPS record (mock).")
async def delete_vps(interaction: discord.Interaction, container_id: str):
    if not await is_admin(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    data = load_db()
    data = [c for c in data if c["id"] != container_id]
    save_db(data)
    await interaction.response.send_message(f"🗑 Deleted record `{container_id}` (mock).")

@bot.tree.command(name="ping", description="Check bot latency.")
async def ping(i: discord.Interaction):
    await i.response.send_message(embed=discord.Embed(
        title="🏓 Pong!", description=f"{round(bot.latency*1000)} ms", color=0x00FF00))

@bot.tree.command(name="help", description="Show available commands.")
async def help_cmd(i: discord.Interaction):
    e = discord.Embed(title="📘 VPS Bot Commands", color=EMBED_COLOR)
    e.description = ("**Admin:** /deploy /delete-vps /list-all\n"
                     "**User:** /list\n"
                     "**General:** /ping /help")
    await i.response.send_message(embed=e, ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

bot.run(TOKEN)

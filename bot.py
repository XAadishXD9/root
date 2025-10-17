import random
import subprocess
import os
import discord
from discord.ext import commands, tasks
import asyncio
from discord import app_commands
import psutil
from datetime import datetime
import re
import time

# Configuration
TOKEN = ''  # REPLACE WITH YOUR BOT'S TOKEN
RAM_LIMIT = '2g'
SERVER_LIMIT = 12
LOGS_CHANNEL_ID = 1422528537952518195    # CHANGE TO YOUR LOGS CHANNEL ID
ADMIN_ROLE_ID = 1422528388756799489     # CHANGE TO YOUR ADMIN ROLE ID

database_file = 'database.txt'

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)
EMBED_COLOR = 0x9B59B6

OS_OPTIONS = {
    "ubuntu": {"image": "ubuntu-vps", "name": "Ubuntu 22.04", "emoji": "🐧", "description": "Stable and widely-used"},
    "debian": {"image": "debian-vps", "name": "Debian 12", "emoji": "🦕", "description": "Stable and reliable"},
    "alpine": {"image": "alpine-vps", "name": "Alpine Linux", "emoji": "⛰️", "description": "Lightweight and fast"},
}

LOADING_ANIMATION = ["🔄", "⚡", "✨", "🌀"]
SUCCESS_ANIMATION = ["✅", "🎉", "✨", "🌟"]
ERROR_ANIMATION = ["❌", "💥", "⚠️", "🚨"]

# --- Utility functions ---
def add_to_database(user, container_name, ssh_command):
    with open(database_file, 'a') as f:
        f.write(f"{user}|{container_name}|{ssh_command}\n")

def remove_from_database(ssh_command):
    if not os.path.exists(database_file):
        return
    with open(database_file, 'r') as f:
        lines = f.readlines()
    with open(database_file, 'w') as f:
        for line in lines:
            if ssh_command not in line:
                f.write(line)

def get_user_servers(user):
    if not os.path.exists(database_file):
        return []
    with open(database_file, 'r') as f:
        return [line.strip() for line in f if line.startswith(user)]

def get_all_servers():
    if not os.path.exists(database_file):
        return []
    with open(database_file, 'r') as f:
        return [line.strip() for line in f]

async def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator or any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)

async def capture_ssh_session_line(process):
    while True:
        output = await process.stdout.readline()
        if not output:
            break
        output = output.decode('utf-8').strip()
        if "ssh session:" in output:
            return output.split("ssh session:")[1].strip()
    return None

# --- Bot setup ---
@bot.event
async def on_ready():
    print(f'✅ Bot is online as {bot.user}')
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Command sync error: {e}")

# --- /deploy (same as before, shortened here for brevity) ---
# You keep your existing deploy command here

# --- /list command ---
@bot.tree.command(name="list", description="📜 List your cloud instances")
async def list_servers(interaction: discord.Interaction):
    user = str(interaction.user)
    servers = get_user_servers(user)
    if not servers:
        await interaction.response.send_message("📭 No instances found!", ephemeral=True)
        return
    embed = discord.Embed(title=f"📋 Your Instances ({len(servers)})", color=EMBED_COLOR)
    for line in servers:
        parts = line.split('|')
        if len(parts) < 3: continue
        container_id = parts[1]
        embed.add_field(name=f"🖥️ {container_id[:12]}", value=f"`{parts[2]}`", inline=False)
    await interaction.response.send_message(embed=embed)

# --- /list-all command ---
@bot.tree.command(name="list-all", description="📊 List all deployed containers")
async def list_all(interaction: discord.Interaction):
    if not await is_admin(interaction):
        await interaction.response.send_message("🚫 Admin only.", ephemeral=True)
        return
    servers = get_all_servers()
    if not servers:
        await interaction.response.send_message("📭 No active instances.")
        return
    embed = discord.Embed(title="📊 All Active Instances", color=EMBED_COLOR)
    for s in servers:
        parts = s.split('|')
        if len(parts) < 3: continue
        embed.add_field(name=parts[1][:12], value=f"Owner: {parts[0]}", inline=False)
    await interaction.response.send_message(embed=embed)

# --- /regen-ssh command ---
@bot.tree.command(name="regen-ssh", description="🔄 Regenerate SSH session for your container")
@app_commands.describe(container_id="Your instance ID (first 4+ characters)")
async def regen_ssh(interaction: discord.Interaction, container_id: str):
    user = str(interaction.user)
    if not os.path.exists(database_file):
        await interaction.response.send_message("📭 You have no instances.", ephemeral=True)
        return
    with open(database_file, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 3 and user == parts[0] and container_id in parts[1]:
                container_info = parts[1]
                old_ssh = parts[2]
                break
        else:
            await interaction.response.send_message("❌ Instance not found.", ephemeral=True)
            return
    exec_cmd = await asyncio.create_subprocess_exec(
        "docker", "exec", container_info, "tmate", "-F",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    ssh_line = await capture_ssh_session_line(exec_cmd)
    if ssh_line:
        remove_from_database(old_ssh)
        add_to_database(user, container_info, ssh_line)
        await interaction.response.send_message(f"🗝️ New SSH: `{ssh_line}`", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ SSH regeneration failed.", ephemeral=True)

# --- /remove command ---
@bot.tree.command(name="remove", description="❌ Delete your instance")
@app_commands.describe(container_id="Your instance ID (first 4+ characters)")
async def remove_instance(interaction: discord.Interaction, container_id: str):
    user = str(interaction.user)
    with open(database_file, 'r') as f:
        lines = f.readlines()
    found = False
    for line in lines:
        if line.startswith(user) and container_id in line:
            parts = line.split('|')
            container = parts[1]
            ssh = parts[2]
            subprocess.run(["docker", "rm", "-f", container])
            remove_from_database(ssh)
            found = True
            break
    if found:
        await interaction.response.send_message(f"🗑️ Instance `{container_id}` deleted!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Instance not found.", ephemeral=True)

# --- NEW /manage command ---
@bot.tree.command(name="manage", description="🧩 Manage your instance with control buttons")
@app_commands.describe(container_id="Your instance ID (first 4+ characters)")
async def manage(interaction: discord.Interaction, container_id: str):
    user = str(interaction.user)
    if not os.path.exists(database_file):
        await interaction.response.send_message("📭 You have no instances.", ephemeral=True)
        return
    with open(database_file, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 3 and user == parts[0] and container_id in parts[1]:
                container_info = parts[1]
                ssh_command = parts[2]
                break
        else:
            await interaction.response.send_message("❌ Instance not found.", ephemeral=True)
            return
    try:
        status = subprocess.check_output(
            ["docker", "inspect", "--format='{{.State.Status}}'", container_info],
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip().strip("'")
    except:
        status = "unknown"

    embed = discord.Embed(title=f"🧩 Manage `{container_info[:12]}`", description=f"Status: **{status}**", color=EMBED_COLOR)

    class ManageView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="🟢 Start", style=discord.ButtonStyle.green)
        async def start(self, i: discord.Interaction, _):
            subprocess.run(["docker", "start", container_info])
            await i.response.send_message(f"🟢 `{container_info[:12]}` started!", ephemeral=True)

        @discord.ui.button(label="🛑 Stop", style=discord.ButtonStyle.red)
        async def stop(self, i: discord.Interaction, _):
            subprocess.run(["docker", "stop", container_info])
            await i.response.send_message(f"🛑 `{container_info[:12]}` stopped!", ephemeral=True)

        @discord.ui.button(label="🔄 Restart", style=discord.ButtonStyle.blurple)
        async def restart(self, i: discord.Interaction, _):
            subprocess.run(["docker", "restart", container_info])
            await i.response.send_message(f"🔄 `{container_info[:12]}` restarted!", ephemeral=True)

        @discord.ui.button(label="🗝️ Regen SSH", style=discord.ButtonStyle.gray)
        async def regen(self, i: discord.Interaction, _):
            subprocess.run(["docker", "exec", container_info, "pkill", "tmate"], stderr=subprocess.DEVNULL)
            exec_cmd = await asyncio.create_subprocess_exec(
                "docker", "exec", container_info, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE
            )
            ssh_line = await capture_ssh_session_line(exec_cmd)
            if ssh_line:
                remove_from_database(ssh_command)
                add_to_database(user, container_info, ssh_line)
                await i.response.send_message(f"🗝️ New SSH: `{ssh_line}`", ephemeral=True)
            else:
                await i.response.send_message("⚠️ Failed to regenerate SSH.", ephemeral=True)

        @discord.ui.button(label="❌ Delete", style=discord.ButtonStyle.danger)
        async def delete(self, i: discord.Interaction, _):
            subprocess.run(["docker", "rm", "-f", container_info])
            remove_from_database(ssh_command)
            await i.response.send_message(f"🗑️ `{container_info[:12]}` deleted!", ephemeral=True)

    await interaction.response.send_message(embed=embed, view=ManageView(), ephemeral=True)

# --- /ping ---
@bot.tree.command(name="ping", description="🏓 Check latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! {latency}ms")

# --- /help ---
@bot.tree.command(name="help", description="ℹ️ Help menu")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="✨ Cloud Bot Commands", color=EMBED_COLOR)
    embed.add_field(name="👤 User Commands",
                    value="`/list`, `/list-all`, `/manage <id>`, `/regen-ssh <id>`, `/remove <id>`, `/ping`, `/help`",
                    inline=False)
    embed.add_field(name="🛡️ Admin Commands",
                    value="`/deploy user:@User os:<os>`, `/delete-user-container <id>`",
                    inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Run bot ---
bot.run(TOKEN)

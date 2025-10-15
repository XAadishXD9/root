import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import subprocess
import random
import string
import os
from datetime import datetime

# ========================
# CONFIG
# ========================
TOKEN = ""  # <-- your bot token
ADMIN_IDS = [1405778722732376176]  # <-- your Discord ID
database_file = "database.txt"
PUBLIC_IP = "138.68.79.95"

# ========================
# BOT SETUP
# ========================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='/', intents=intents)

# ========================
# HELPERS
# ========================
def is_admin(user_id):
    return user_id in ADMIN_IDS

def generate_random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def add_to_database(user, container_name, ssh_command, ram, cpu, creator, os_type="Ubuntu 22.04"):
    with open(database_file, 'a') as f:
        f.write(f"{user}|{container_name}|{ssh_command}|{ram}|{cpu}|{creator}|{os_type}\n")

def get_user_containers(user_name):
    if not os.path.exists(database_file):
        return []
    with open(database_file, "r") as f:
        return [line.strip().split("|") for line in f if user_name in line.split("|")[0]]

async def capture_ssh_session_line(process):
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded = line.decode('utf-8').strip()
        if "ssh session:" in decoded:
            return decoded.split("ssh session:")[1].strip()
    return None

def get_docker_image_for_os(os_type):
    os_map = {"ubuntu": "ubuntu:22.04", "debian": "debian:12"}
    return os_map.get(os_type, "ubuntu:22.04")

def os_type_to_display_name(os_type):
    os_map = {"ubuntu": "Ubuntu 22.04", "debian": "Debian 12"}
    return os_map.get(os_type, "Unknown OS")

# ========================
# ADMIN COMMANDS
# ========================
@bot.tree.command(name="deploy", description="🚀 Admin: Deploy a new VPS instance for a user")
@app_commands.describe(
    user="Select the user to assign the VPS to",
    os="Operating system (ubuntu or debian)",
    ram="RAM in GB (0 = no limit)",
    cpu="CPU cores (0 = no limit)"
)
async def deploy_command(interaction: discord.Interaction, user: discord.User, os: str, ram: int, cpu: int):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    await interaction.response.defer()

    ram = max(0, ram)
    cpu = max(0, cpu)

    container_name = f"VPS_{user.name}_{generate_random_string()}"
    image = get_docker_image_for_os(os)

    try:
        subprocess.call(["docker", "pull", image])
        docker_cmd = [
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL",
            "--hostname", "eaglenode", "--name", container_name, image
        ]
        if ram > 0:
            docker_cmd.insert(6, f"--memory={ram}G")
        if cpu > 0:
            docker_cmd.insert(7, f"--cpus={cpu}")

        container_id = subprocess.check_output(docker_cmd).decode().strip()

        await interaction.followup.send("⏳ Setting up your VPS, please wait...", ephemeral=True)

        install_cmd = (
            "apt update -y && apt install git sudo neofetch docker.io unzip "
            "tmate dropbear docker-compose -y && dropbear -p 22"
        )
        subprocess.call(["docker", "exec", "-i", container_name, "bash", "-c", install_cmd])

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        ssh_line = await capture_ssh_session_line(exec_cmd)

        if ssh_line:
            add_to_database(str(user), container_name, ssh_line, ram, cpu, str(interaction.user), os_type_to_display_name(os))
            embed = discord.Embed(title="✅ VPS Created Successfully!", color=0x2400ff)
            embed.add_field(name="OS", value=os_type_to_display_name(os))
            embed.add_field(name="RAM", value=f"{ram if ram > 0 else '∞'} GB")
            embed.add_field(name="CPU", value=f"{cpu if cpu > 0 else '∞'} cores")
            embed.add_field(name="SSH Command", value=f"```{ssh_line}```", inline=False)
            embed.add_field(name="Container Name", value=container_name)
            await user.send(embed=embed)
            await interaction.followup.send(f"✅ VPS created and details sent to {user.mention}", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to generate SSH session.", ephemeral=True)

    except subprocess.CalledProcessError as e:
        await interaction.followup.send(f"❌ Docker error: {e}", ephemeral=True)

# ========================
# USER COMMANDS
# ========================
@bot.tree.command(name="list", description="🌐 Show your VPS instances")
async def list_user_vps(interaction: discord.Interaction):
    vps_list = get_user_containers(str(interaction.user))
    if not vps_list:
        await interaction.response.send_message("📂 You don’t have any VPS instances.", ephemeral=True)
        return
    embed = discord.Embed(title="🌐 Your VPS Instances", color=0x2400ff)
    for user, cname, ssh, ram, cpu, creator, os_type in vps_list:
        embed.add_field(
            name=cname,
            value=f"OS: {os_type}\nRAM: {('∞' if ram == '0' else ram+'GB')} | CPU: {('∞' if cpu == '0' else cpu+' cores')}\nSSH: `{ssh}`",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========================
# BASIC COMMANDS
# ========================
@bot.tree.command(name="ping", description="🏓 Check bot latency")
async def ping_command(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")

@bot.tree.command(name="help", description="📘 Show available commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🪐 EAGLE NODE | Help Menu", color=0x2400ff)
    embed.add_field(name="🚀 /deploy", value="Admin — Deploy VPS", inline=False)
    embed.add_field(name="🗑️ /delete-user-container", value="Admin — Delete VPS", inline=False)
    embed.add_field(name="🌍 /list-all", value="Show your VPS list (admins see all)", inline=False)
    embed.add_field(name="🌐 /list", value="Show your VPS list", inline=False)
    embed.add_field(name="♻️ /regen-ssh", value="Regenerate SSH link", inline=False)
    embed.add_field(name="🗑️ /remove", value="Delete your VPS", inline=False)
    embed.add_field(name="🏓 /ping", value="Check bot latency", inline=False)
    embed.set_footer(text="💫 Powered by EAGLE NODE | Secure VPS Hosting")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========================
# NEW COMMAND: /plans
# ========================
@bot.tree.command(name="plans", description="💎 View available VPS hosting plans")
async def plans_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💎 EAGLE NODE | VPS Hosting Plans",
        description="Choose your plan and start hosting instantly!",
        color=0x2400ff
    )

    embed.set_image(url="https://cdn.discordapp.com/attachments/1406277976739287202/1415163011601272953/standard.gif?ex=68ebbc02&is=68ea6a82&hm=e08f619cd6048415608d9c8868148a5cb60a3019788fb30d4eea2715b115c230&")

    embed.add_field(
        name="<:ateex_server_host:1423672049125036133> VPS 1",
        value=(
            "<:PriceTag_USD:1423671938764636222> **Invites:** 10 invites\n"
            "<:RAM:1423672181824425994> **RAM:** 8 GB DDR4\n"
            "<:ateex_ssd:1423672067080978504> **Storage:** 20 GB SSD\n"
            "<:Intel_Xeon_CPU:1423672094943740006> **CPU:** 2 Cores\n"
            "<:ateex_up:1423672257296994305> **Uptime:** 24/7\n"
            "<:debian:1423672199222530069> **OS:** Debian\n"
            "<:panel:1423673508801679412> **Panel:** Pterodactyl Supported"
        ),
        inline=False
    )

    embed.add_field(
        name="<:ateex_server_host:1423672049125036133> VPS 2",
        value=(
            "<:PriceTag_USD:1423671938764636222> **Invites:** 20 invites\n"
            "<:RAM:1423672181824425994> **RAM:** 16 GB DDR4\n"
            "<:ateex_ssd:1423672067080978504> **Storage:** 40 GB SSD\n"
            "<:Intel_Xeon_CPU:1423672094943740006> **CPU:** 4 Cores\n"
            "<:ateex_up:1423672257296994305> **Uptime:** 24/7\n"
            "<:debian:1423672199222530069> **OS:** Debian\n"
            "<:panel:1423673508801679412> **Panel:** Pterodactyl Supported"
        ),
        inline=False
    )

    embed.set_footer(text="💫 Powered by EAGLE NODE | Secure VPS Hosting")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# ========================
# BOT STATUS
# ========================
@bot.event
async def on_ready():
    print(f"🚀 Bot online as {bot.user}")
    await bot.tree.sync()

    async def update_status():
        while True:
            instance_count = len(open(database_file).readlines()) if os.path.exists(database_file) else 0
            status = f"Watching 💫 EAGLE NODE {instance_count} VPS"
            await bot.change_presence(activity=discord.Game(name=status))
            await asyncio.sleep(2)

    bot.loop.create_task(update_status())

# ========================
# RUN BOT
# ========================
bot.run(TOKEN)

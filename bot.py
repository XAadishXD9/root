import discord
from discord.ext import commands
from discord import app_commands
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

    # Safe default limits (avoid negative or nonsense values)
    ram = max(0, ram)
    cpu = max(0, cpu)

    container_name = f"VPS_{user.name}_{generate_random_string()}"
    image = get_docker_image_for_os(os)

    try:
        subprocess.call(["docker", "pull", image])

        # Build docker command dynamically
        docker_cmd = [
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL",
            "--hostname", "eaglenode", "--name", container_name, image
        ]

        # Add resource limits only if not "infinite mode"
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

@bot.tree.command(name="delete-user-container", description="🗑️ Admin: Delete a user’s VPS container by ID or name")
@app_commands.describe(container_id="Enter the Docker container ID or name")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        subprocess.check_call(["docker", "stop", container_id])
        subprocess.check_call(["docker", "rm", container_id])
        if os.path.exists(database_file):
            with open(database_file, "r") as f:
                lines = f.readlines()
            with open(database_file, "w") as f:
                for line in lines:
                    if container_id not in line:
                        f.write(line)
        await interaction.followup.send(f"✅ Deleted `{container_id}` and removed from database.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.followup.send(f"❌ Failed to delete `{container_id}` — check container name.", ephemeral=True)

@bot.tree.command(name="list-all", description="🌍 Show VPS instances (only yours unless admin)")
async def list_all_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    username = str(interaction.user)

    if not os.path.exists(database_file):
        await interaction.response.send_message("📂 No VPS records found.", ephemeral=True)
        return

    with open(database_file, "r") as f:
        vps_lines = [line.strip().split("|") for line in f.readlines()]

    # Admins can view all VPS
    if is_admin(user_id):
        embed = discord.Embed(title="🌍 All VPS Instances (Admin View)", color=0x2400ff)
        for user, cname, ssh, ram, cpu, creator, os_type in vps_lines:
            embed.add_field(
                name=cname,
                value=(
                    f"👤 User: {user}\n"
                    f"🧑‍💼 Creator: {creator}\n"
                    f"💽 OS: {os_type}\n"
                    f"🧠 RAM: {('∞' if ram == '0' else ram+'GB')} | ⚙️ CPU: {('∞' if cpu == '0' else cpu+' cores')}\n"
                    f"🔐 SSH: `{ssh}`"
                ),
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Regular users can only view their own VPS
    user_vps = [v for v in vps_lines if v[0] == username]
    if not user_vps:
        await interaction.response.send_message("📂 You don’t have any VPS instances.", ephemeral=True)
        return

    embed = discord.Embed(title="🌐 Your VPS Instances", color=0x2400ff)
    for user, cname, ssh, ram, cpu, creator, os_type in user_vps:
        embed.add_field(
            name=cname,
            value=(
                f"💽 OS: {os_type}\n"
                f"🧠 RAM: {('∞' if ram == '0' else ram+'GB')} | ⚙️ CPU: {('∞' if cpu == '0' else cpu+' cores')}\n"
                f"🔐 SSH: `{ssh}`"
            ),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

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

@bot.tree.command(name="regen-ssh", description="♻️ Regenerate SSH session for your VPS")
@app_commands.describe(container_id="Enter your container ID or name")
async def regen_ssh(interaction: discord.Interaction, container_id: str):
    vps_list = get_user_containers(str(interaction.user))
    if not any(container_id in v for v in vps_list) and not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don't own this container.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        exec_cmd = await asyncio.create_subprocess_exec("docker", "exec", container_id, "tmate", "-F", stdout=asyncio.subprocess.PIPE)
        ssh_line = await capture_ssh_session_line(exec_cmd)
        if ssh_line:
            await interaction.followup.send(f"♻️ New SSH Session:\n```{ssh_line}```", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to regenerate SSH session.", ephemeral=True)
    except:
        await interaction.followup.send("❌ Error while regenerating SSH session.", ephemeral=True)

@bot.tree.command(name="remove", description="🗑️ Delete your VPS")
@app_commands.describe(container_id="Enter your container ID or name")
async def remove_vps(interaction: discord.Interaction, container_id: str):
    vps_list = get_user_containers(str(interaction.user))
    if not any(container_id in v for v in vps_list) and not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don't own this container.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        subprocess.check_call(["docker", "stop", container_id])
        subprocess.check_call(["docker", "rm", container_id])
        with open(database_file, "r") as f:
            lines = f.readlines()
        with open(database_file, "w") as f:
            for line in lines:
                if container_id not in line:
                    f.write(line)
        await interaction.followup.send(f"✅ VPS `{container_id}` removed successfully.", ephemeral=True)
    except:
        await interaction.followup.send("❌ Error removing VPS.", ephemeral=True)

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
            await asyncio.sleep(30)

    bot.loop.create_task(update_status())

# ========================
# RUN BOT
# ========================
bot.run(TOKEN)

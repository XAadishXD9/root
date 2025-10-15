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
TOKEN = ""  # <-- your bot token here
ADMIN_IDS = [1405778722732376176]  # <-- your Discord user ID(s)
database_file = "database.txt"

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
    os_map = {
        "ubuntu": "ubuntu:22.04",
        "debian": "debian:12"
    }
    return os_map.get(os_type.lower(), "ubuntu:22.04")

def os_type_to_display_name(os_type):
    os_map = {
        "ubuntu": "Ubuntu 22.04",
        "debian": "Debian 12"
    }
    return os_map.get(os_type.lower(), "Unknown OS")

# ========================
# ADMIN COMMANDS
# ========================
@bot.tree.command(name="deploy", description="🚀 Admin: Deploy a new VPS for a user (Ubuntu/Debian only)")
@app_commands.describe(
    user="User to assign VPS",
    os="Operating system (ubuntu or debian)",
    ram="RAM in GB (0 = unlimited)",
    cpu="CPU cores (0 = unlimited)"
)
async def deploy_command(interaction: discord.Interaction, user: discord.User, os: str, ram: int = 2, cpu: int = 1):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    os = os.lower()
    if os not in ["ubuntu", "debian"]:
        await interaction.response.send_message("❌ Invalid OS. Use `ubuntu` or `debian` only.", ephemeral=True)
        return

    await interaction.response.defer()
    ram = max(0, ram)
    cpu = max(0, cpu)

    container_name = f"VPS_{user.name}_{generate_random_string()}"
    image = get_docker_image_for_os(os)

    try:
        subprocess.call(["docker", "pull", image])

        docker_cmd = [
            "docker", "run", "-itd",
            "--privileged", "--cap-add=ALL",
            "--hostname", "eaglenode"
        ]

        if ram > 0:
            docker_cmd.extend(["--memory", f"{ram}G"])
        if cpu > 0:
            docker_cmd.extend(["--cpus", str(cpu)])

        docker_cmd.extend(["--name", container_name, image])
        subprocess.check_output(docker_cmd)

        await interaction.followup.send("⏳ Setting up your VPS, please wait...", ephemeral=True)

        install_script = """
            apt-get update -y && \
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            ca-certificates tmate neofetch screen wget curl htop nano vim openssh-server sudo ufw git docker.io systemd systemd-sysv && \
            update-ca-certificates && \
            apt-get clean && rm -rf /var/lib/apt/lists/* && \
            systemctl enable ssh || true && \
            service ssh start || systemctl start ssh
        """

        subprocess.call(["docker", "exec", "-i", container_name, "bash", "-c", install_script])

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        ssh_line = await capture_ssh_session_line(exec_cmd)

        if ssh_line:
            add_to_database(str(user), container_name, ssh_line, ram, cpu, str(interaction.user), os_type_to_display_name(os))
            embed = discord.Embed(title="✅ VPS Created Successfully!", color=0x2400ff)
            embed.add_field(name="💽 OS", value=os_type_to_display_name(os))
            embed.add_field(name="🧠 RAM", value=f"{ram if ram > 0 else '∞'} GB")
            embed.add_field(name="⚙️ CPU", value=f"{cpu if cpu > 0 else '∞'} cores")
            embed.add_field(name="🔐 SSH Command", value=f"```{ssh_line}```", inline=False)
            embed.add_field(name="📦 Container Name", value=container_name)
            await user.send(embed=embed)

            await interaction.followup.send(
                f"✅ {os_type_to_display_name(os)} VPS created for {user.mention}! Check your DMs for details.",
                ephemeral=False
            )
        else:
            await interaction.followup.send("❌ Failed to generate SSH session.", ephemeral=True)

    except subprocess.CalledProcessError as e:
        await interaction.followup.send(f"❌ Docker error: {e}", ephemeral=True)

@bot.tree.command(name="list-all", description="🌍 Show all VPS instances (admin only, with status)")
async def list_all_command(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    if not os.path.exists(database_file):
        await interaction.response.send_message("📂 No VPS records found.", ephemeral=True)
        return

    with open(database_file, "r") as f:
        vps_lines = [line.strip().split("|") for line in f.readlines()]

    embed = discord.Embed(title="🌍 All VPS Instances", color=0x2400ff)

    for user, cname, ssh, ram, cpu, creator, os_type in vps_lines:
        try:
            status_output = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Running}}", cname]
            ).decode().strip()
            status = "🟢 Running" if status_output == "true" else "🔴 Stopped"
        except subprocess.CalledProcessError:
            status = "⚪ Unknown"

        embed.add_field(
            name=f"{cname} ({status})",
            value=(
                f"👤 **User:** {user}\n"
                f"💽 **OS:** {os_type}\n"
                f"🧠 **RAM:** {ram} GB | ⚙️ **CPU:** {cpu} cores\n"
                f"🔐 **SSH:** `{ssh}`\n"
                f"🧑‍💼 **Creator:** {creator}"
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="delete-user-container", description="🗑️ Admin: Delete any user’s VPS")
@app_commands.describe(container_id="Container name or ID")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return
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
        await interaction.response.send_message(f"✅ Deleted `{container_id}` successfully.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.response.send_message(f"❌ Failed to delete `{container_id}`.", ephemeral=True)

# ========================
# USER COMMANDS
# ========================
@bot.tree.command(name="list", description="📜 List your VPS instances (with status)")
async def list_command(interaction: discord.Interaction):
    username = str(interaction.user)
    vps_list = get_user_containers(username)
    if not vps_list:
        await interaction.response.send_message("📂 You don’t have any VPS instances.", ephemeral=True)
        return

    embed = discord.Embed(title="🌐 Your VPS Instances", color=0x2400ff)
    for user, cname, ssh, ram, cpu, creator, os_type in vps_list:
        try:
            status_output = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Running}}", cname]
            ).decode().strip()
            status = "🟢 Running" if status_output == "true" else "🔴 Stopped"
        except subprocess.CalledProcessError:
            status = "⚪ Unknown"

        embed.add_field(
            name=cname,
            value=(
                f"💽 OS: {os_type}\n"
                f"🧠 RAM: {ram} GB | ⚙️ CPU: {cpu} cores\n"
                f"🔐 SSH: `{ssh}`\n"
                f"⚡ **Status:** {status}"
            ),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove", description="🗑️ Delete your VPS")
@app_commands.describe(container_id="Container ID or name")
async def remove_vps(interaction: discord.Interaction, container_id: str):
    username = str(interaction.user)
    vps_list = get_user_containers(username)
    if not any(container_id in v for v in vps_list) and not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don’t own this VPS.", ephemeral=True)
        return

    try:
        subprocess.check_call(["docker", "stop", container_id])
        subprocess.check_call(["docker", "rm", container_id])
        with open(database_file, "r") as f:
            lines = f.readlines()
        with open(database_file, "w") as f:
            for line in lines:
                if container_id not in line:
                    f.write(line)
        await interaction.response.send_message(f"✅ VPS `{container_id}` removed successfully.", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Error removing VPS.", ephemeral=True)

# ========================
# BASIC
# ========================
@bot.tree.command(name="ping", description="🏓 Check bot latency")
async def ping_command(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")

@bot.event
async def on_ready():
    print(f"🚀 Logged in as {bot.user}")
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Game(name="EAGLE NODE VPS"))
    print("🎮 Status set to: Playing EAGLE NODE VPS")

bot.run(TOKEN)

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
    os_map = {"ubuntu": "ubuntu:22.04", "debian": "debian:12"}
    return os_map.get(os_type.lower(), "ubuntu:22.04")

def os_type_to_display_name(os_type):
    os_map = {"ubuntu": "Ubuntu 22.04", "debian": "Debian 12"}
    return os_map.get(os_type.lower(), "Unknown OS")

# ========================
# ADMIN COMMANDS
# ========================
@bot.tree.command(name="deploy", description="🚀 Admin: Deploy a new VPS instance for a user")
@app_commands.describe(
    user="Select the user to assign the VPS to",
    os="Operating system (ubuntu or debian)",
    ram="RAM in GB (0 = unlimited)",
    cpu="CPU cores (0 = unlimited)"
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
            "docker", "run", "-itd",
            "--privileged", "--cap-add=ALL",
            "--hostname", "eaglenode"
        ]

        if ram > 0:
            docker_cmd.extend(["--memory", f"{ram}G"])
        if cpu > 0:
            docker_cmd.extend(["--cpus", str(cpu)])

        docker_cmd.extend(["--name", container_name, image])

        container_id = subprocess.check_output(docker_cmd).decode().strip()

        await interaction.followup.send("⏳ Setting up your VPS, please wait...", ephemeral=True)

        # ===== FAST INSTALL SECTION =====
        subprocess.call(["docker", "exec", "-i", container_name, "bash", "-c", """
            apt-get update -y && \
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            tmate neofetch screen wget curl htop nano vim openssh-server sudo ufw git docker.io systemd systemd-sysv && \
            apt-get clean && rm -rf /var/lib/apt/lists/* && \
            systemctl enable ssh || true && \
            service ssh start || systemctl start ssh
        """])

        # Start tmate session and capture SSH info
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
            await interaction.followup.send(f"✅ VPS created and details sent to {user.mention}", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to generate SSH session.", ephemeral=True)

    except subprocess.CalledProcessError as e:
        await interaction.followup.send(f"❌ Docker error: {e}", ephemeral=True)

@bot.tree.command(name="delete-user-container", description="🗑️ Admin: Delete a user’s VPS container")
@app_commands.describe(container_id="Enter the container ID or name")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    await interaction.response.defer()
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
        await interaction.followup.send(f"❌ Failed to delete `{container_id}`.", ephemeral=True)

@bot.tree.command(name="list-all", description="🌍 Show all VPS instances (admin view)")
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
        embed.add_field(
            name=cname,
            value=(
                f"👤 User: {user}\n💽 OS: {os_type}\n🧠 RAM: {ram}GB | ⚙️ CPU: {cpu} cores\n"
                f"🔐 SSH: `{ssh}`\n🧑‍💼 Creator: {creator}"
            ),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========================
# USER COMMANDS
# ========================
@bot.tree.command(name="list", description="📜 List your VPS instances")
async def list_command(interaction: discord.Interaction):
    username = str(interaction.user)
    vps_list = get_user_containers(username)
    if not vps_list:
        await interaction.response.send_message("📂 You don’t have any VPS instances.", ephemeral=True)
        return

    embed = discord.Embed(title="🌐 Your VPS Instances", color=0x2400ff)
    for user, cname, ssh, ram, cpu, creator, os_type in vps_list:
        embed.add_field(
            name=cname,
            value=f"💽 OS: {os_type}\n🧠 RAM: {ram}GB | ⚙️ CPU: {cpu} cores\n🔐 SSH: `{ssh}`",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove", description="🗑️ Delete your VPS")
@app_commands.describe(container_id="Enter your container ID or name")
async def remove_vps(interaction: discord.Interaction, container_id: str):
    username = str(interaction.user)
    vps_list = get_user_containers(username)
    if not any(container_id in v for v in vps_list) and not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don’t own this VPS.", ephemeral=True)
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

@bot.tree.command(name="manage", description="🧰 Manage your VPS with control buttons")
@app_commands.describe(container_id="Enter your VPS container ID or name")
async def manage_command(interaction: discord.Interaction, container_id: str):
    username = str(interaction.user)
    vps_list = get_user_containers(username)

    if not any(container_id in v for v in vps_list) and not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ You don’t own this VPS.", ephemeral=True)
        return

    with open(database_file, "r") as f:
        data = [line.strip().split("|") for line in f if container_id in line]

    if not data:
        await interaction.response.send_message("❌ Container not found.", ephemeral=True)
        return

    user, cname, ssh, ram, cpu, creator, os_type = data[0]

    try:
        status_output = subprocess.check_output(["docker", "inspect", "-f", "{{.State.Running}}", container_id]).decode().strip()
        status = "🟢 RUNNING" if status_output == "true" else "🔴 STOPPED"
    except:
        status = "⚪ UNKNOWN"

    embed = discord.Embed(title=f"🖥️ VPS Management – {container_id}", color=0x2bff00)
    embed.add_field(name="📶 Status", value=status, inline=True)
    embed.add_field(name="🧠 RAM", value=f"{ram} GB", inline=True)
    embed.add_field(name="⚙️ CPU", value=f"{cpu} Cores", inline=True)
    embed.add_field(name="💽 OS", value=os_type, inline=True)
    embed.add_field(name="🎮 Controls", value="Use the buttons below to manage your VPS.", inline=False)
    embed.set_footer(text=f"EAGLE NODE VPS Manager • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    class VPSControlView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="🔁 Reinstall", style=discord.ButtonStyle.danger)
        async def reinstall_button(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            await interaction_button.response.send_message(f"⏳ Reinstalling `{container_id}`...", ephemeral=True)
            subprocess.call(["docker", "restart", container_id])
            await asyncio.sleep(2)
            await interaction_button.followup.send(f"✅ VPS `{container_id}` reinstalled successfully.", ephemeral=True)

        @discord.ui.button(label="▶️ Start", style=discord.ButtonStyle.success)
        async def start_button(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            subprocess.call(["docker", "start", container_id])
            await interaction_button.response.send_message(f"✅ VPS `{container_id}` started.", ephemeral=True)

        @discord.ui.button(label="⏸️ Stop", style=discord.ButtonStyle.secondary)
        async def stop_button(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            subprocess.call(["docker", "stop", container_id])
            await interaction_button.response.send_message(f"🛑 VPS `{container_id}` stopped.", ephemeral=True)

        @discord.ui.button(label="🔑 SSH (New)", style=discord.ButtonStyle.primary)
        async def ssh_button(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            await interaction_button.response.defer(ephemeral=True)
            try:
                exec_cmd = await asyncio.create_subprocess_exec(
                    "docker", "exec", container_id, "tmate", "-F",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                new_ssh_line = await capture_ssh_session_line(exec_cmd)
                if new_ssh_line:
                    await interaction_button.followup.send(
                        f"🔗 **New SSH Session Created!**\n```{new_ssh_line}```", ephemeral=True
                    )
                else:
                    await interaction_button.followup.send("❌ Failed to create a new SSH session.", ephemeral=True)
            except Exception as e:
                await interaction_button.followup.send(f"⚠️ Error creating SSH session:\n`{e}`", ephemeral=True)

    await interaction.response.send_message(embed=embed, view=VPSControlView(), ephemeral=False)

# ========================
# BASIC COMMANDS
# ========================
@bot.tree.command(name="ping", description="🏓 Check bot latency")
async def ping_command(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")

@bot.event
async def on_ready():
    print(f"🚀 Logged in as {bot.user}")
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Game(name="🦅 EAGLE NODE VPS Manager"))

# ========================
# RUN BOT
# ========================
bot.run(TOKEN)

import discord
from discord import app_commands
from discord.ext import commands
import subprocess
import asyncio
import random
import string

# ==========================
# CONFIGURATION
# ==========================
TOKEN = "YOUR_DISCORD_BOT_TOKEN"   # replace with your bot token
ADMIN_IDS = [1405778722732376176]           # replace with your Discord admin ID(s)

# ==========================
# INITIAL SETUP
# ==========================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ==========================
# HELPERS
# ==========================
def is_admin(user_id):
    return user_id in ADMIN_IDS


def generate_random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def os_type_to_display_name(os_type: str) -> str:
    return os_type.capitalize()


def get_docker_image_for_os(os_type: str) -> str:
    os_type = os_type.lower()
    if os_type == "ubuntu":
        return "ubuntu:22.04"
    elif os_type == "debian":
        return "debian:12"
    else:
        return "debian:latest"


async def capture_ssh_session_line(exec_cmd):
    """Read SSH line from tmate output"""
    while True:
        line = await exec_cmd.stdout.readline()
        if not line:
            break
        decoded = line.decode().strip()
        if "ssh" in decoded:
            return decoded
    return None


# Placeholder DB (replace with real database logic)
VPS_DB = {}  # key = username, value = dict with vps info


def add_to_database(user, container, ssh, ram, cpu, creator, os_type):
    VPS_DB[user] = {
        "container": container,
        "ssh": ssh,
        "ram": ram,
        "cpu": cpu,
        "creator": creator,
        "os": os_type,
        "status": "Running ✅"
    }
    print(f"[DB] VPS added for {user}: {VPS_DB[user]}")


# ==========================
# ADMIN COMMANDS
# ==========================
@bot.tree.command(name="deploy", description="🚀 Admin: Deploy a new VPS instance for a user")
@app_commands.describe(
    user="Select the user to assign the VPS to",
    os="Operating system (ubuntu or debian)",
    ram="RAM in GB (e.g., 4, 8, 16, 32, or 'infinite')",
    cpu="CPU cores (e.g., 1, 2, 4, 5, or 'infinite')"
)
async def deploy_command(interaction: discord.Interaction, user: discord.User, os: str, ram: str = "2", cpu: str = "1"):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
        return

    await interaction.response.defer()

    def parse_limit(value):
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ["infinite", "∞", "unlimited", "none", "0"]:
                return 0
        try:
            return int(value)
        except ValueError:
            return 0

    ram_val = parse_limit(ram)
    cpu_val = parse_limit(cpu)
    container_name = f"VPS_{user.name}_{generate_random_string(6)}"
    image = get_docker_image_for_os(os)

    try:
        subprocess.check_call(["docker", "pull", image])

        docker_cmd = [
            "docker", "run", "-itd", "--privileged", "--cap-add=ALL",
            "--hostname", container_name,
            "--name", container_name,
        ]

        if ram_val > 0:
            docker_cmd.append(f"--memory={ram_val}g")
        if cpu_val > 0:
            docker_cmd.append(f"--cpus={cpu_val}")

        docker_cmd.append(image)
        container_id = subprocess.check_output(docker_cmd).decode().strip()

        await interaction.followup.send("⏳ Setting up your VPS, please wait...", ephemeral=True)

        install_cmd = (
            "apt update -y && apt install -y git sudo neofetch docker.io unzip "
            "tmate dropbear docker-compose && dropbear -p 22 || true"
        )
        subprocess.call(["docker", "exec", "-i", container_name, "bash", "-c", install_cmd])

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        ssh_line = await capture_ssh_session_line(exec_cmd)

        if ssh_line:
            add_to_database(
                str(user),
                container_name,
                ssh_line,
                "∞" if ram_val == 0 else str(ram_val),
                "∞" if cpu_val == 0 else str(cpu_val),
                str(interaction.user),
                os_type_to_display_name(os)
            )

            embed = discord.Embed(title="✅ VPS Created Successfully!", color=0x2400ff)
            embed.add_field(name="OS", value=os_type_to_display_name(os))
            embed.add_field(name="RAM", value=f"{'∞' if ram_val == 0 else ram_val} GB")
            embed.add_field(name="CPU", value=f"{'∞' if cpu_val == 0 else cpu_val} cores")
            embed.add_field(name="SSH Command", value=f"```{ssh_line}```", inline=False)
            embed.add_field(name="Container Name", value=container_name)
            await user.send(embed=embed)
            await interaction.followup.send(f"✅ VPS created and details sent to {user.mention}", ephemeral=True)
        else:
            subprocess.call(["docker", "stop", container_name])
            subprocess.call(["docker", "rm", container_name])
            await interaction.followup.send("❌ Failed to create tmate session. Container removed.", ephemeral=True)

    except subprocess.CalledProcessError as e:
        await interaction.followup.send(f"❌ Docker error: `{e}`", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"❌ Unexpected error: `{exc}`", ephemeral=True)


@bot.tree.command(name="plans", description="💾 Show available VPS plans")
async def plans_command(interaction: discord.Interaction):
    plans = [
        {"name": "Basic", "ram": 4, "cpu": 1},
        {"name": "Standard", "ram": 8, "cpu": 2},
        {"name": "Pro", "ram": 16, "cpu": 4},
        {"name": "Ultra", "ram": 32, "cpu": 5},
        {"name": "Infinite", "ram": "∞", "cpu": "∞"},
    ]
    embed = discord.Embed(title="💾 VPS Plans", color=0x00ff88)
    for plan in plans:
        embed.add_field(name=plan["name"], value=f"RAM: {plan['ram']} GB | CPU: {plan['cpu']} cores", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==========================
# USER COMMANDS
# ==========================
@bot.tree.command(name="myvps", description="💻 View your VPS details")
async def myvps_command(interaction: discord.Interaction):
    user = str(interaction.user)
    if user not in VPS_DB:
        await interaction.response.send_message("❌ You don't have any VPS yet.", ephemeral=True)
        return

    vps = VPS_DB[user]
    embed = discord.Embed(title="💻 Your VPS Details", color=0x00ff99)
    embed.add_field(name="OS", value=vps["os"])
    embed.add_field(name="RAM", value=f"{vps['ram']} GB")
    embed.add_field(name="CPU", value=f"{vps['cpu']} cores")
    embed.add_field(name="Status", value=vps["status"], inline=False)
    embed.add_field(name="SSH Command", value=f"```{vps['ssh']}```", inline=False)
    embed.add_field(name="Container", value=vps["container"], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="status", description="📊 Check your VPS status")
async def status_command(interaction: discord.Interaction):
    user = str(interaction.user)
    if user not in VPS_DB:
        await interaction.response.send_message("❌ No VPS found.", ephemeral=True)
        return
    container_name = VPS_DB[user]["container"]
    try:
        status = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Status}}", container_name]
        ).decode().strip()
        VPS_DB[user]["status"] = f"{status.capitalize()} ✅"
        await interaction.response.send_message(f"📊 `{container_name}` is **{status}**.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.response.send_message("❌ VPS not found or deleted.", ephemeral=True)


@bot.tree.command(name="stopvps", description="🛑 Stop your VPS")
async def stopvps_command(interaction: discord.Interaction):
    user = str(interaction.user)
    if user not in VPS_DB:
        await interaction.response.send_message("❌ You don't have a VPS.", ephemeral=True)
        return
    container_name = VPS_DB[user]["container"]
    try:
        subprocess.check_call(["docker", "stop", container_name])
        VPS_DB[user]["status"] = "Stopped 🛑"
        await interaction.response.send_message(f"🛑 VPS `{container_name}` stopped successfully.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.response.send_message("❌ VPS not found or already stopped.", ephemeral=True)


@bot.tree.command(name="startvps", description="▶️ Start your VPS")
async def startvps_command(interaction: discord.Interaction):
    user = str(interaction.user)
    if user not in VPS_DB:
        await interaction.response.send_message("❌ You don't have a VPS.", ephemeral=True)
        return
    container_name = VPS_DB[user]["container"]
    try:
        subprocess.check_call(["docker", "start", container_name])
        VPS_DB[user]["status"] = "Running ✅"
        await interaction.response.send_message(f"▶️ VPS `{container_name}` started successfully.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.response.send_message("❌ VPS not found or already running.", ephemeral=True)


@bot.tree.command(name="deletevps", description="⚠️ Delete your VPS permanently")
async def deletevps_command(interaction: discord.Interaction):
    user = str(interaction.user)
    if user not in VPS_DB:
        await interaction.response.send_message("❌ You don't have a VPS.", ephemeral=True)
        return
    container_name = VPS_DB[user]["container"]
    try:
        subprocess.call(["docker", "stop", container_name])
        subprocess.call(["docker", "rm", container_name])
        del VPS_DB[user]
        await interaction.response.send_message(f"🗑️ VPS `{container_name}` deleted successfully.", ephemeral=True)
    except subprocess.CalledProcessError:
        await interaction.response.send_message("❌ VPS not found or already deleted.", ephemeral=True)


# ==========================
# EVENTS
# ==========================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔁 Synced {len(synced)} commands.")
    except Exception as e:
        print(f"❌ Sync failed: {e}")


# ==========================
# RUN BOT
# ==========================
bot.run(TOKEN)

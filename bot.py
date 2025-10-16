# bot.py
import asyncio
import random
import subprocess
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import psutil
import re
import time
import shlex
import logging

# ----------------------------
# Configuration - EDIT THESE
# ----------------------------
TOKEN = ""  # <-- Put your bot token here
LOGS_CHANNEL_ID = 1420803132144750703  # <-- Replace with your logs channel ID (int)
ADMIN_ROLE_ID = 1416372125953949758  # <-- Replace with your admin role ID (int)
DATABASE_FILE = "database.txt"
EMBED_COLOR = 0x9B59B6
WATERMARK = "EagleNode"
WELCOME_MESSAGE = "Welcome to EagleNode"
AUTODELETE_HOURS = 4  # auto-delete after 4 hours inactivity
PACKAGE_INSTALL_TIMEOUT = 600  # seconds for apt-get install
# OS images mapping (images you have locally)
OS_IMAGES = {
    "ubuntu": "ubuntu-vps",
    "debian": "debian-vps",
    "kali": "kali-vps",
    # other images may exist but package install will be skipped if not apt-based
}

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eaglenode")

# ----------------------------
# Intents & Bot
# ----------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="/", intents=intents)
start_time = datetime.utcnow()

# ----------------------------
# Helpers: database (text file)
# format per line:
# owner|container_id|ssh_command|last_seen_iso|os|memory|cpu|disk|username
# ----------------------------
def add_to_database_row(owner: str, container_id: str, ssh_command: str, os_name: str, memory: str, cpu: str, disk: str, username: str):
    now = datetime.utcnow().isoformat()
    with open(DATABASE_FILE, "a") as f:
        f.write(f"{owner}|{container_id}|{ssh_command}|{now}|{os_name}|{memory}|{cpu}|{disk}|{username}\n")

def remove_from_database_by_ssh(ssh_command: str):
    if not os.path.exists(DATABASE_FILE):
        return
    with open(DATABASE_FILE, "r") as f:
        lines = f.readlines()
    with open(DATABASE_FILE, "w") as f:
        for line in lines:
            if ssh_command not in line:
                f.write(line)

def remove_from_database_by_id(container_id: str):
    if not os.path.exists(DATABASE_FILE):
        return
    with open(DATABASE_FILE, "r") as f:
        lines = f.readlines()
    with open(DATABASE_FILE, "w") as f:
        for line in lines:
            parts = line.strip().split("|")
            if len(parts) >= 2 and not parts[1].startswith(container_id):
                f.write(line)

def update_last_seen(container_id: str):
    if not os.path.exists(DATABASE_FILE):
        return
    out_lines = []
    with open(DATABASE_FILE, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 2 and parts[1].startswith(container_id):
                parts[3] = datetime.utcnow().isoformat()
                out_lines.append("|".join(parts) + "\n")
            else:
                out_lines.append(line)
    with open(DATABASE_FILE, "w") as f:
        f.writelines(out_lines)

def get_user_servers(owner: str):
    if not os.path.exists(DATABASE_FILE):
        return []
    servers = []
    with open(DATABASE_FILE, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts and parts[0] == owner:
                servers.append(parts)
    return servers

def get_all_servers():
    if not os.path.exists(DATABASE_FILE):
        return []
    rows = []
    with open(DATABASE_FILE, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts and len(parts) >= 9:
                rows.append(parts)
    return rows

def find_server_by_prefix(container_prefix: str):
    if not os.path.exists(DATABASE_FILE):
        return None
    with open(DATABASE_FILE, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 2 and parts[1].startswith(container_prefix):
                return parts
    return None

# ----------------------------
# Docker command runner
# ----------------------------
async def run_docker_command(container_id: str, command: list, timeout: int = 300):
    """Run command inside a container. command is a list, e.g. ['bash','-c','some']"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "timeout"
        output = (stdout + stderr).decode("utf-8", errors="ignore")
        return (proc.returncode == 0), output
    except Exception as e:
        return False, str(e)

async def capture_ssh_session_line(process):
    """Read stdout lines until we find a tmate SSH session line (best-effort)."""
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        try:
            s = line.decode("utf-8", errors="ignore").strip()
        except:
            continue
        if "ssh session" in s.lower() or "ssh://" in s or "ssh " in s:
            return s
    return None

# ----------------------------
# Utility: container stats & host resources
# ----------------------------
def get_system_resources():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        mem_total = mem.total / (1024 ** 3)
        mem_used = mem.used / (1024 ** 3)
        disk = psutil.disk_usage('/')
        disk_total = disk.total / (1024 ** 3)
        disk_used = disk.used / (1024 ** 3)
        return {
            'cpu': cpu_percent,
            'memory': {'total': round(mem_total, 2), 'used': round(mem_used, 2), 'percent': mem.percent},
            'disk': {'total': round(disk_total, 2), 'used': round(disk_used, 2), 'percent': disk.percent}
        }
    except Exception:
        return {'cpu': 0, 'memory': {'total':0,'used':0,'percent':0}, 'disk': {'total':0,'used':0,'percent':0}}

def get_container_stats():
    try:
        stats_raw = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{.ID}}|{{.CPUPerc}}|{{.MemUsage}}"],
            text=True
        ).strip().splitlines()
    except Exception:
        return {}
    stats = {}
    for line in stats_raw:
        parts = line.split("|")
        if len(parts) >= 3:
            cid = parts[0]
            stats[cid] = {'cpu': parts[1].strip(), 'mem': parts[2].strip()}
    return stats

# ----------------------------
# Permissions helpers
# ----------------------------
async def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    return any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)

async def is_admin_role_only(interaction: discord.Interaction) -> bool:
    return any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)

# ----------------------------
# Ready + status
# ----------------------------
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="EAGLE NODE VPS"))
    print("🎮 Status set to: Playing EAGLE NODE VPS")
    print(f"✨ Bot is ready. Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("🔁 Commands synced.")
    except Exception as e:
        print("❌ Sync error:", e)
    auto_cleanup.start()
    # you can also start other background tasks here

# ----------------------------
# Background: auto-delete inactive VPSs
# ----------------------------
@tasks.loop(minutes=10)
async def auto_cleanup():
    now = datetime.utcnow()
    if not os.path.exists(DATABASE_FILE):
        return
    rows = get_all_servers()
    for parts in rows:
        try:
            owner = parts[0]
            container_id = parts[1]
            last_seen = datetime.fromisoformat(parts[3])
            if now - last_seen > timedelta(hours=AUTODELETE_HOURS):
                # try to stop & remove container
                try:
                    subprocess.run(["docker", "stop", container_id], check=False)
                    subprocess.run(["docker", "rm", container_id], check=False)
                except Exception as e:
                    logger.warning(f"Auto cleanup failed docker remove {container_id}: {e}")
                remove_from_database_by_id(container_id)
                # notify logs channel
                channel = bot.get_channel(LOGS_CHANNEL_ID)
                if channel:
                    await channel.send(f"⏳ Auto-removed inactive VPS `{container_id[:12]}` (owner: `{owner}`)")
        except Exception:
            continue

# ----------------------------
# /deploy command - Admin only
# ----------------------------
@bot.tree.command(name="deploy", description="🚀 [ADMIN] Deploy a new VPS for a user")
@app_commands.describe(user="User to deploy for", os="OS (ubuntu|debian|kali)", ram="Memory GB", cpu="CPU cores")
async def deploy(interaction: discord.Interaction, user: discord.User, os: str, ram: int, cpu: int):
    # admin check
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Permission denied. Admins only.", ephemeral=True)
        return

    os = os.lower()
    if os not in OS_IMAGES:
        await interaction.response.send_message(f"❌ Unsupported OS. Supported: {', '.join(OS_IMAGES.keys())}", ephemeral=True)
        return

    image = OS_IMAGES[os]
    memory = str(ram)
    cpu_count = str(cpu)
    disk = "4"  # default disk in GB (could be parameterized)
    username = "user"  # default username
    ssh_password = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
    root_password = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=12))
    vps_id = "".join(random.choices("abcdef0123456789", k=8))

    # initial response
    embed = discord.Embed(title=f"🚀 Deploying {os.capitalize()} for {user.display_name}", description="Creating container...", color=EMBED_COLOR)
    await interaction.response.send_message(embed=embed)
    status_msg = await interaction.original_response()

    try:
        # create container
        # We use privileged + detached; adjust flags to your environment
        create_cmd = ["docker", "run", "-itd", "--privileged", "--name", f"eaglenode-{vps_id}", image]
        create_out = subprocess.check_output(create_cmd).decode('utf-8').strip()
        container_id = create_out
        # log
        await send_to_logs(f"🔧 {interaction.user} deployed {image} for {user} (ID: {container_id[:12]})")

        # Install packages for apt-based OS
        def is_apt_based(os_name):
            return os_name in ("ubuntu", "debian", "kali")

        if is_apt_based(os):
            try:
                try:
                    await status_msg.edit(embed=discord.Embed(title="📦 Installing packages...", description="Running apt-get update", color=EMBED_COLOR))
                except:
                    pass

                success, out = await run_docker_command(container_id, ["bash", "-c", "apt-get update"], timeout=120)
                if not success:
                    raise Exception("apt-get update failed: " + out[:400])

                packages = [
                    "tmate", "neofetch", "screen", "wget", "curl", "htop", "nano", "vim",
                    "openssh-server", "sudo", "ufw", "git", "systemd", "systemd-sysv"
                ]
                # install
                pkg_cmd = ["bash", "-c", "DEBIAN_FRONTEND=noninteractive apt-get install -y " + " ".join(shlex.quote(p) for p in packages)]
                success, out = await run_docker_command(container_id, pkg_cmd, timeout=PACKAGE_INSTALL_TIMEOUT)
                if not success:
                    raise Exception("Package installation failed: " + out[:800])
            except Exception as e:
                # rollback - remove container and inform
                try:
                    subprocess.run(["docker", "kill", container_id], stderr=subprocess.DEVNULL)
                    subprocess.run(["docker", "rm", container_id], stderr=subprocess.DEVNULL)
                except:
                    pass
                await status_msg.edit(embed=discord.Embed(title="❌ Deployment Failed", description=str(e), color=0xFF0000))
                await send_to_logs(f"❌ Deployment failed for {user} by {interaction.user}: {e}")
                return
        else:
            # not apt-based - skip installation (user can provide custom image)
            try:
                await status_msg.edit(embed=discord.Embed(title="⚠️ Skipping package install", description="OS not apt-based; manual setup may be required", color=0xFFA500))
            except:
                pass

        # configure SSH user (best-effort)
        try:
            user_cmds = [
                f"useradd -m -s /bin/bash {username} || true",
                f"echo '{username}:{ssh_password}' | chpasswd || true",
                f"usermod -aG sudo {username} || true",
                "sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config || true",
                "sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config || true",
                "service ssh restart || service sshd restart || true"
            ]
            for c in user_cmds:
                success, out = await run_docker_command(container_id, ["bash", "-c", c], timeout=30)
                if not success:
                    logger.warning(f"SSH setup step failed for {container_id}: {c} -> {out[:200]}")
        except Exception as e:
            logger.warning("SSH config error: %s", e)

        # set hostname, watermark, motd
        try:
            hostname_cmd = f"echo 'eaglenode-{vps_id}' > /etc/hostname && hostname eaglenode-{vps_id}"
            await run_docker_command(container_id, ["bash", "-c", hostname_cmd])
            await run_docker_command(container_id, ["bash", "-c", f"echo '{WATERMARK}' > /etc/machine-info || true"])
            await run_docker_command(container_id, ["bash", "-c", f"echo '{WELCOME_MESSAGE}' > /etc/motd || true"])
            await run_docker_command(container_id, ["bash", "-c", f"chown -R {username}:{username} /home/{username} || true"])
            await run_docker_command(container_id, ["bash", "-c", f"chmod 700 /home/{username} || true"])
        except Exception as e:
            logger.warning("branding error: %s", e)

        # attempt to start tmate and capture ssh session (best-effort)
        ssh_session_line = "N/A"
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_id, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            # read lines until we capture ssh session text or timeout
            try:
                ssh_session_line = await asyncio.wait_for(capture_ssh_session_line(proc), timeout=40)
            except asyncio.TimeoutError:
                ssh_session_line = None
            if not ssh_session_line:
                # fallback try to fetch tmate display messages
                ssh_session_line = "tmate session not available. Connect to container directly."
        except Exception:
            ssh_session_line = "tmate not available"

        # save to DB
        add_to_database_row(str(user), container_id, ssh_session_line, os, memory, cpu_count, disk, username)

        # final embed
        embed = discord.Embed(title="🎉 EagleNode VPS Created Successfully!", color=discord.Color.green())
        embed.add_field(name="🆔 VPS ID", value=vps_id)
        embed.add_field(name="💾 Memory", value=f"{memory} GB")
        embed.add_field(name="⚡ CPU", value=f"{cpu_count} cores")
        embed.add_field(name="💿 Disk", value=f"{disk} GB")
        embed.add_field(name="👤 Username", value=username)
        embed.add_field(name="🔑 Password", value=f"||{ssh_password}||", inline=False)
        embed.add_field(name="🔌 SSH Session", value=f"```{ssh_session_line}```", inline=False)
        embed.set_footer(text=WATERMARK)

        # DM the owner
        try:
            await user.send(embed=embed)
            await status_msg.edit(content=f"✅ VPS ready! Check your DM, {user.mention}.")
        except discord.Forbidden:
            await status_msg.edit(content="✅ VPS created, but I couldn't DM the user. Please enable DMs from server members.")

    except subprocess.CalledProcessError as e:
        await status_msg.edit(content=f"❌ Deployment failed: {e}")
        logger.exception("CalledProcessError during deploy")
    except Exception as e:
        await status_msg.edit(content=f"❌ Deployment failed: {e}")
        logger.exception("Exception during deploy")

# ----------------------------
# /delete-user-container (admin)
# ----------------------------
@bot.tree.command(name="delete-user-container", description="❌ [ADMIN] Force delete a container by ID")
@app_commands.describe(container_id="ID (prefix ok)")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Permission denied. Admins only.", ephemeral=True)
        return
    await interaction.response.send_message(f"⚠️ Attempting to delete `{container_id}`...", ephemeral=True)
    try:
        # find real container from db
        parts = find_server_by_prefix(container_id)
        if not parts:
            await interaction.followup.send("❌ Could not find container in database.", ephemeral=True)
            return
        owner = parts[0]
        real_id = parts[1]
        # stop & rm
        subprocess.run(["docker", "stop", real_id], check=False)
        subprocess.run(["docker", "rm", real_id], check=False)
        remove_from_database_by_id(real_id)
        await interaction.followup.send(f"✅ Deleted `{real_id[:12]}` (owner: `{owner}`).", ephemeral=True)
        await send_to_logs(f"💥 {interaction.user} force-deleted container `{real_id[:12]}` owned by `{owner}`")
    except Exception as e:
        await interaction.followup.send(f"❌ Error deleting: {e}", ephemeral=True)

# ----------------------------
# /list (user)
# ----------------------------
@bot.tree.command(name="list", description="📜 List your VPS instances")
async def list_servers(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    owner = str(interaction.user)
    servers = get_user_servers(owner)
    if not servers:
        await interaction.followup.send("📭 You have no active instances.", ephemeral=True)
        return
    embed = discord.Embed(title=f"📋 Your Cloud Instances ({len(servers)})", color=EMBED_COLOR)
    for parts in servers:
        container_id = parts[1]
        os_name = parts[4]
        memory = parts[5]
        cpu = parts[6]
        username = parts[8] if len(parts) > 8 else "user"
        # inspect status
        try:
            out = subprocess.check_output(["docker", "inspect", "--format={{.State.Status}}", container_id], stderr=subprocess.DEVNULL).decode().strip().strip("'")
            status_emoji = "🟢" if out == "running" else "🔴"
            status_text = f"{status_emoji} {out}"
        except Exception:
            status_text = "🔴 Unknown"
        embed.add_field(name=f"🖥️ `{container_id[:12]}`", value=f"▫️ OS: {os_name}\n▫️ Status: {status_text}\n▫️ RAM: {memory}GB | CPU: {cpu} cores", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

# ----------------------------
# /list-all (admin)
# ----------------------------
@bot.tree.command(name="list-all", description="📋 List all VPS instances (admin)")
async def list_all(interaction: discord.Interaction):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Permission denied. Admins only.", ephemeral=True)
        return
    await interaction.response.defer()
    rows = get_all_servers()
    host_stats = get_system_resources()
    container_stats = get_container_stats()
    embed = discord.Embed(title=f"📊 All Instances ({len(rows)})", color=EMBED_COLOR)
    embed.add_field(name="Host Resources", value=f"CPU: {host_stats['cpu']}%\nMemory: {host_stats['memory']['used']}GB/{host_stats['memory']['total']}GB ({host_stats['memory']['percent']}%)\nDisk: {host_stats['disk']['used']}GB/{host_stats['disk']['total']}GB ({host_stats['disk']['percent']}%)", inline=False)
    for parts in rows:
        owner = parts[0]
        cid = parts[1]
        os_name = parts[4]
        mem = parts[5]
        cpu = parts[6]
        stats = container_stats.get(cid, {'cpu': '0.00%', 'mem': '0B / 0B'})
        try:
            out = subprocess.check_output(["docker", "inspect", "--format={{.State.Status}}", cid], stderr=subprocess.DEVNULL).decode().strip().strip("'")
            status_emoji = "🟢" if out == "running" else "🔴"
            status_text = f"{status_emoji} {out}"
        except Exception:
            status_text = "🔴 Unknown"
        embed.add_field(name=f"🖥️ `{cid[:12]}`", value=f"Owner: `{owner}`\nOS: {os_name}\nStatus: {status_text}\nCPU: {stats['cpu']}\nRAM: {stats['mem']}", inline=False)
    await interaction.followup.send(embed=embed)

# ----------------------------
# /manage command - opens an interactive view
# ----------------------------
class ManageView(discord.ui.View):
    def __init__(self, container_id: str, owner_str: str):
        super().__init__(timeout=120)
        self.container_id = container_id
        self.owner_str = owner_str

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Start", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            subprocess.run(["docker", "start", self.container_id], check=False)
            update_last_seen(self.container_id)
            await interaction.response.edit_message(content=f"✅ Started `{self.container_id[:12]}`", view=None)
            await send_to_logs(f"🟢 {interaction.user} started {self.container_id[:12]}")
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Start failed: {e}", view=None)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            subprocess.run(["docker", "stop", self.container_id], check=False)
            await interaction.response.edit_message(content=f"🛑 Stopped `{self.container_id[:12]}`", view=None)
            await send_to_logs(f"🛑 {interaction.user} stopped {self.container_id[:12]}")
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Stop failed: {e}", view=None)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.blurple)
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            subprocess.run(["docker", "restart", self.container_id], check=False)
            update_last_seen(self.container_id)
            await interaction.response.edit_message(content=f"🔄 Restarted `{self.container_id[:12]}`", view=None)
            await send_to_logs(f"🔄 {interaction.user} restarted {self.container_id[:12]}")
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Restart failed: {e}", view=None)

    @discord.ui.button(label="Regen SSH", style=discord.ButtonStyle.gray)
    async def regen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # kill existing tmates and start a new one, then capture ssh
        try:
            # pkill tmate
            await run_docker_command(self.container_id, ["bash", "-c", "pkill tmate || true"], timeout=10)
            proc = await asyncio.create_subprocess_exec("docker", "exec", self.container_id, "tmate", "-F", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            ssh_line = None
            try:
                ssh_line = await asyncio.wait_for(capture_ssh_session_line(proc), timeout=40)
            except asyncio.TimeoutError:
                ssh_line = None
            if not ssh_line:
                ssh_line = "tmate session unavailable"
            # update db
            remove_from_database_by_id(self.container_id)
            add_to_database_row(self.owner_str, self.container_id, ssh_line, "unknown-os", "0", "0", "0", "user")
            update_last_seen(self.container_id)
            await interaction.response.edit_message(content=f"🔑 New SSH: ```{ssh_line}```", view=None)
            await send_to_logs(f"🔄 {interaction.user} regenerated SSH for {self.container_id[:12]}")
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Failed to regen SSH: {e}", view=None)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.red)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            subprocess.run(["docker", "stop", self.container_id], check=False)
            subprocess.run(["docker", "rm", self.container_id], check=False)
            remove_from_database_by_id(self.container_id)
            await interaction.response.edit_message(content=f"🗑️ Deleted `{self.container_id[:12]}`", view=None)
            await send_to_logs(f"🗑️ {interaction.user} deleted {self.container_id[:12]}")
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Delete failed: {e}", view=None)

@bot.tree.command(name="manage", description="⚙️ Manage your VPS (open a control panel)")
@app_commands.describe(container_id="Your container ID (prefix allowed)")
async def manage(interaction: discord.Interaction, container_id: str):
    await interaction.response.defer()
    parts = find_server_by_prefix(container_id)
    if not parts:
        await interaction.followup.send("🔍 Container not found (prefix ok).", ephemeral=True)
        return
    owner = parts[0]
    if owner != str(interaction.user) and not await is_admin_role_only(interaction):
        await interaction.followup.send("🚫 You don't own this container.", ephemeral=True)
        return
    real_id = parts[1]
    view = ManageView(real_id, owner)
    await interaction.followup.send(f"Control panel for `{real_id[:12]}` — choose an action:", view=view, ephemeral=True)

# ----------------------------
# /ping
# ----------------------------
@bot.tree.command(name="ping", description="🏓 Check bot latency and uptime")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    up = datetime.utcnow() - start_time
    embed = discord.Embed(title="🏓 Pong!", color=EMBED_COLOR)
    embed.add_field(name="Latency", value=f"{latency}ms")
    embed.add_field(name="Uptime", value=str(up).split(".")[0])
    await interaction.response.send_message(embed=embed)

# ----------------------------
# Utility: send to logs channel
# ----------------------------
async def send_to_logs(message: str):
    try:
        ch = bot.get_channel(LOGS_CHANNEL_ID)
        if ch:
            ts = datetime.now().strftime("%H:%M:%S")
            await ch.send(f"`[{ts}]` {message}")
    except Exception as e:
        logger.warning("Failed send_to_logs: %s", e)

# ----------------------------
# Run bot
# ----------------------------
if __name__ == "__main__":
    if TOKEN == "" or ADMIN_ROLE_ID == 1416372125953949758:
        print("⚠️ Please set TOKEN, LOGS_CHANNEL_ID and ADMIN_ROLE_ID at the top of the file before running.")
    bot.run(TOKEN)

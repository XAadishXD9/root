import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, button, Button
import subprocess, asyncio, datetime

# ====== BOT CONFIG ======
TOKEN = "YOUR_BOT_TOKEN"  # <-- replace this
ADMIN_ROLE_ID = 123456789012345678  # <-- replace this with your admin role ID
EMBED_COLOR = 0x5865F2

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ====== DATABASE MOCK ======
DB_CONTAINERS = []

# ====== UTILITIES ======
async def is_admin_role_only(interaction):
    return any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

def get_container_by_id(container_id):
    for c in DB_CONTAINERS:
        if c["container_id"].startswith(container_id):
            return c
    return None

async def run_docker_command(container_id, cmd, timeout=300):
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        success = process.returncode == 0
        return success, stdout.decode() if success else stderr.decode()
    except asyncio.TimeoutError:
        return False, "Command timed out."

# ====== DEPLOY COMMAND ======
@bot.tree.command(name="deploy", description="🚀 [ADMIN] Deploy a VPS for a user")
@app_commands.describe(
    user="User to deploy VPS for",
    os="Operating system (ubuntu, debian, alpine, fedora, arch, kali)",
    ram="RAM limit (e.g. 4g, 8g, 12g, 24g)",
    cpu="CPU cores (e.g. 2, 4, 6, 8)"
)
async def deploy(interaction: discord.Interaction, user: discord.User, os: str, ram: str, cpu: str):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Only admins can deploy VPS.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    os = os.lower()
    valid_oses = ["ubuntu", "debian", "alpine", "fedora", "arch", "kali"]
    if os not in valid_oses:
        await interaction.followup.send(f"❌ Invalid OS. Choose from: {', '.join(valid_oses)}", ephemeral=True)
        return

    try:
        container_id = subprocess.check_output([
            "docker", "run", "-itd", "--privileged",
            f"--memory={ram}",
            f"--cpus={cpu}",
            os
        ]).decode().strip()

        # Install essential packages (Debian-based)
        if os in ["ubuntu", "debian", "kali"]:
            packages = [
                "tmate", "neofetch", "screen", "wget", "curl", "htop", "nano", "vim",
                "openssh-server", "sudo", "ufw", "git", "docker.io", "systemd", "systemd-sysv"
            ]
            await run_docker_command(container_id, ["apt-get", "update", "-y"], timeout=400)
            success, out = await run_docker_command(container_id, ["apt-get", "install", "-y"] + packages, timeout=600)
            if not success:
                raise Exception(f"Package installation failed: {out}")

        # Create SSH session
        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        ssh_link = None
        while True:
            line = await exec_cmd.stdout.readline()
            if not line:
                break
            decoded = line.decode().strip()
            if "ssh " in decoded:
                ssh_link = decoded
                break

        if not ssh_link:
            raise Exception("SSH session not generated")

        DB_CONTAINERS.append({
            "container_id": container_id,
            "user_id": str(user.id),
            "os": os,
            "ram": ram,
            "cpu": cpu,
            "ssh": ssh_link,
            "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        })

        embed = discord.Embed(
            title="✅ VPS Deployed Successfully!",
            description=f"**User:** {user.mention}\n**OS:** {os.upper()}\n**RAM:** {ram}\n**CPU:** {cpu}\n\n🔑 **SSH:**\n```{ssh_link}```",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed)
        try:
            await user.send(embed=embed)
        except:
            pass

    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(title="💥 Deployment Error", description=f"```{e}```", color=0xFF0000))

# ====== DELETE USER VPS ======
@bot.tree.command(name="delete-user-container", description="🗑 [ADMIN] Delete a user's VPS container")
@app_commands.describe(container_id="Container ID to delete")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    container = get_container_by_id(container_id)
    if not container:
        await interaction.response.send_message("❌ Container not found.", ephemeral=True)
        return
    try:
        subprocess.run(["docker", "stop", container["container_id"]])
        subprocess.run(["docker", "rm", container["container_id"]])
        DB_CONTAINERS.remove(container)
        await interaction.response.send_message(f"🗑 VPS `{container_id[:12]}` deleted successfully.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error deleting VPS: {e}", ephemeral=True)

# ====== LIST (USER) ======
@bot.tree.command(name="list", description="📋 Show your VPS containers")
async def list_user(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    items = [c for c in DB_CONTAINERS if c["user_id"] == user_id]
    if not items:
        await interaction.response.send_message("📋 You have no active VPS instances.", ephemeral=True)
        return

    embed = discord.Embed(title=f"📋 VPS List for {interaction.user.name}", color=EMBED_COLOR)
    for c in items:
        embed.add_field(
            name=f"{c['os'].upper()} | {c['container_id'][:12]}",
            value=f"💾 {c['ram']} • ⚙️ {c['cpu']}\n🔗 `{c['ssh']}`",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ====== LIST ALL (ADMIN) ======
@bot.tree.command(name="list-all", description="📋 [ADMIN] List all VPS containers")
async def list_all(interaction: discord.Interaction):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    if not DB_CONTAINERS:
        await interaction.response.send_message("📋 No containers found.")
        return

    embed = discord.Embed(title="📋 All VPS Containers", color=0x00FFFF)
    for c in DB_CONTAINERS:
        embed.add_field(
            name=f"{c['os'].upper()} | {c['container_id'][:12]}",
            value=f"👤 <@{c['user_id']}> | 💾 {c['ram']} • ⚙️ {c['cpu']}\n🔗 `{c['ssh']}`",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# ====== MANAGE (INTERACTIVE PANEL) ======
class ManageView(View):
    def __init__(self, container_id, user_id, admin_mode=False):
        super().__init__(timeout=None)
        self.container_id = container_id
        self.user_id = user_id
        self.admin_mode = admin_mode

    async def _check_permissions(self, interaction):
        if self.admin_mode:
            return await is_admin_role_only(interaction)
        return str(interaction.user.id) == self.user_id or await is_admin_role_only(interaction)

    @button(label="Reinstall", style=discord.ButtonStyle.danger, emoji="🔁")
    async def reinstall(self, interaction, button):
        if not await self._check_permissions(interaction):
            await interaction.response.send_message("🚫 Permission denied.", ephemeral=True)
            return
        subprocess.run(["docker", "restart", self.container_id])
        await interaction.response.send_message(f"✅ VPS `{self.container_id[:12]}` restarted.", ephemeral=True)

    @button(label="Start", style=discord.ButtonStyle.success, emoji="▶️")
    async def start(self, interaction, button):
        if not await self._check_permissions(interaction):
            await interaction.response.send_message("🚫 Permission denied.", ephemeral=True)
            return
        subprocess.run(["docker", "start", self.container_id])
        await interaction.response.send_message(f"🟢 VPS `{self.container_id[:12]}` started.", ephemeral=True)

    @button(label="Stop", style=discord.ButtonStyle.secondary, emoji="⏸")
    async def stop(self, interaction, button):
        if not await self._check_permissions(interaction):
            await interaction.response.send_message("🚫 Permission denied.", ephemeral=True)
            return
        subprocess.run(["docker", "stop", self.container_id])
        await interaction.response.send_message(f"🛑 VPS `{self.container_id[:12]}` stopped.", ephemeral=True)

    @button(label="SSH", style=discord.ButtonStyle.primary, emoji="🔑")
    async def ssh(self, interaction, button):
        if not await self._check_permissions(interaction):
            await interaction.response.send_message("🚫 Permission denied.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            exec_cmd = await asyncio.create_subprocess_exec(
                "docker", "exec", self.container_id, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            ssh_link = None
            while True:
                line = await exec_cmd.stdout.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                if "ssh " in decoded:
                    ssh_link = decoded
                    break
            if ssh_link:
                await interaction.followup.send(embed=discord.Embed(
                    title="🔑 New SSH Session Created",
                    description=f"Use this SSH link:\n```{ssh_link}```",
                    color=0x00FF00
                ), ephemeral=True)
            else:
                await interaction.followup.send(embed=discord.Embed(
                    title="⚠️ SSH Error",
                    description="Failed to create new SSH session.",
                    color=0xFF0000
                ), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=discord.Embed(
                title="❌ Error",
                description=f"```{e}```",
                color=0xFF0000
            ), ephemeral=True)

@bot.tree.command(name="manage", description="⚙️ Manage your VPS interactively")
@app_commands.describe(container_id="Container ID to manage")
async def manage(interaction: discord.Interaction, container_id: str):
    container = get_container_by_id(container_id)
    if not container:
        await interaction.response.send_message("❌ Container not found.", ephemeral=True)
        return
    admin_mode = await is_admin_role_only(interaction)
    if container["user_id"] != str(interaction.user.id) and not admin_mode:
        await interaction.response.send_message("🚫 You can only manage your own VPS!", ephemeral=True)
        return

    try:
        status = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Status}}", container["container_id"]]
        ).decode().strip().upper()
    except subprocess.CalledProcessError:
        status = "UNKNOWN"

    embed = discord.Embed(
        title=f"🖥 VPS Manager - {container['container_id'][:12]}",
        description=f"Managing container: `{container['container_id']}`",
        color=EMBED_COLOR
    )
    embed.add_field(
        name="📊 VPS Info",
        value=f"**OS:** {container['os'].upper()}\n**RAM:** {container['ram']}\n**CPU:** {container['cpu']}\n**Status:** {status}\n**SSH:** `{container['ssh']}`",
        inline=False
    )
    embed.add_field(name="🎮 Controls", value="Use the buttons below to manage your VPS.", inline=False)
    embed.set_footer(text=f"Last update • {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    await interaction.response.send_message(embed=embed, view=ManageView(container['container_id'], container['user_id'], admin_mode))

# ====== PING ======
@bot.tree.command(name="ping", description="🏓 Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(embed=discord.Embed(
        title="🏓 Pong!",
        description=f"Latency: `{latency}ms`",
        color=0x00FF00
    ))

# ====== HELP ======
@bot.tree.command(name="help", description="📘 Show all bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📘 VPS Bot Help", color=EMBED_COLOR)
    embed.add_field(name="/deploy", value="Deploy a VPS (Admin only)", inline=False)
    embed.add_field(name="/delete-user-container", value="Delete a VPS (Admin only)", inline=False)
    embed.add_field(name="/list", value="List your VPS", inline=False)
    embed.add_field(name="/list-all", value="List all VPS (Admin only)", inline=False)
    embed.add_field(name="/manage", value="Manage a VPS interactively", inline=False)
    embed.add_field(name="/ping", value="Check bot latency", inline=False)
    embed.add_field(name="/help", value="Show help", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ====== BOT READY ======
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    print("🌐 Slash commands synced.")

bot.run(TOKEN)

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, button, Button
import subprocess, asyncio, datetime

# ========= CONFIG =========
TOKEN = ""             # <- replace with your real Discord bot token
ADMIN_ROLE_ID = 1422528388756799489   # <- replace with your Admin role ID
EMBED_COLOR = 0x5865F2

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ========= IN-MEMORY DATABASE =========
DB_CONTAINERS = []

# ========= UTILITIES =========
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
        ok = process.returncode == 0
        return ok, stdout.decode() if ok else stderr.decode()
    except asyncio.TimeoutError:
        return False, "Command timed out."

# ========= /DEPLOY =========
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

    # --- auto-append memory unit if missing
    if not ram.lower().endswith(("g", "m")):
        ram = f"{ram}g"

    try:
        # create container
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-itd", "--privileged",
            f"--memory={ram}", f"--cpus={cpu}", os,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(stderr.decode().strip() or "docker run failed")
        container_id = stdout.decode().strip()

        # install packages (Debian-based)
        if os in ["ubuntu", "debian", "kali"]:
            pkgs = [
                "tmate","neofetch","screen","wget","curl","htop","nano","vim",
                "openssh-server","sudo","ufw","git","docker.io","systemd","systemd-sysv"
            ]
            await run_docker_command(container_id, ["apt-get","update","-y"])
            ok, out = await run_docker_command(container_id, ["apt-get","install","-y"]+pkgs, timeout=600)
            if not ok:
                raise Exception(out)

        # start tmate and grab ssh line
        exec_cmd = await asyncio.create_subprocess_exec(
            "docker","exec",container_id,"tmate","-F",
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE
        )
        ssh_link=None
        while True:
            line=await exec_cmd.stdout.readline()
            if not line: break
            txt=line.decode().strip()
            if "ssh " in txt:
                ssh_link=txt; break
        if not ssh_link:
            raise Exception("SSH link not created")

        DB_CONTAINERS.append({
            "container_id": container_id,
            "user_id": str(user.id),
            "os": os, "ram": ram, "cpu": cpu,
            "ssh": ssh_link,
            "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        })

        embed = discord.Embed(
            title="✅ VPS Deployed",
            description=f"**User:** {user.mention}\n**OS:** {os.upper()}\n**RAM:** {ram}\n**CPU:** {cpu}\n\n🔑 **SSH:**\n```{ssh_link}```",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed)
        try: await user.send(embed=embed)
        except: pass

    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(
            title="💥 Deployment Error", description=f"```{e}```", color=0xFF0000
        ), ephemeral=True)

# ========= /DELETE-USER-CONTAINER =========
@bot.tree.command(name="delete-user-container", description="🗑 [ADMIN] Delete a user's VPS")
@app_commands.describe(container_id="Container ID to delete")
async def delete_user_container(interaction: discord.Interaction, container_id: str):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True)
        return
    c = get_container_by_id(container_id)
    if not c:
        await interaction.response.send_message("❌ Container not found.", ephemeral=True)
        return
    subprocess.run(["docker","stop",c["container_id"]])
    subprocess.run(["docker","rm",c["container_id"]])
    DB_CONTAINERS.remove(c)
    await interaction.response.send_message(f"🗑 VPS `{container_id[:12]}` deleted.")

# ========= /LIST & /LIST-ALL =========
@bot.tree.command(name="list", description="📋 Show your VPS list")
async def list_user(interaction: discord.Interaction):
    uid=str(interaction.user.id)
    items=[c for c in DB_CONTAINERS if c["user_id"]==uid]
    if not items:
        await interaction.response.send_message("📋 You have no active VPS.", ephemeral=True); return
    emb=discord.Embed(title=f"📋 VPS for {interaction.user.name}",color=EMBED_COLOR)
    for c in items:
        emb.add_field(name=f"{c['os'].upper()} | {c['container_id'][:12]}",
                      value=f"💾 {c['ram']} • ⚙️ {c['cpu']}\n🔗 `{c['ssh']}`",inline=False)
    await interaction.response.send_message(embed=emb,ephemeral=True)

@bot.tree.command(name="list-all", description="📋 [ADMIN] List all VPS")
async def list_all(interaction: discord.Interaction):
    if not await is_admin_role_only(interaction):
        await interaction.response.send_message("🚫 Admins only.", ephemeral=True); return
    if not DB_CONTAINERS:
        await interaction.response.send_message("📋 No containers found."); return
    emb=discord.Embed(title="📋 All VPS",color=0x00FFFF)
    for c in DB_CONTAINERS:
        emb.add_field(name=f"{c['os'].upper()} | {c['container_id'][:12]}",
                      value=f"👤 <@{c['user_id']}> • 💾 {c['ram']} • ⚙️ {c['cpu']}\n🔗 `{c['ssh']}`",inline=False)
    await interaction.response.send_message(embed=emb)

# ========= /MANAGE =========
class ManageView(View):
    def __init__(self, cid, uid, admin=False):
        super().__init__(timeout=None); self.cid=cid; self.uid=uid; self.admin=admin
    async def _ok(self, i): return self.admin or str(i.user.id)==self.uid or await is_admin_role_only(i)

    @button(label="Reinstall",style=discord.ButtonStyle.danger,emoji="🔁")
    async def reinstall(self,i,_): 
        if not await self._ok(i): return await i.response.send_message("🚫 Denied",ephemeral=True)
        subprocess.run(["docker","restart",self.cid]); await i.response.send_message(f"✅ VPS `{self.cid[:12]}` restarted.",ephemeral=True)
    @button(label="Start",style=discord.ButtonStyle.success,emoji="▶️")
    async def start(self,i,_):
        if not await self._ok(i): return await i.response.send_message("🚫 Denied",ephemeral=True)
        subprocess.run(["docker","start",self.cid]); await i.response.send_message(f"🟢 VPS `{self.cid[:12]}` started.",ephemeral=True)
    @button(label="Stop",style=discord.ButtonStyle.secondary,emoji="⏸")
    async def stop(self,i,_):
        if not await self._ok(i): return await i.response.send_message("🚫 Denied",ephemeral=True)
        subprocess.run(["docker","stop",self.cid]); await i.response.send_message(f"🛑 VPS `{self.cid[:12]}` stopped.",ephemeral=True)
    @button(label="SSH",style=discord.ButtonStyle.primary,emoji="🔑")
    async def ssh(self,i,_):
        if not await self._ok(i): return await i.response.send_message("🚫 Denied",ephemeral=True)
        await i.response.defer(thinking=True)
        try:
            p=await asyncio.create_subprocess_exec("docker","exec",self.cid,"tmate","-F",
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            ssh=None
            while True:
                line=await p.stdout.readline()
                if not line: break
                t=line.decode().strip()
                if "ssh " in t: ssh=t; break
            if ssh: await i.followup.send(embed=discord.Embed(title="🔑 New SSH",description=f"```{ssh}```",color=0x00FF00),ephemeral=True)
            else: await i.followup.send("⚠️ SSH creation failed",ephemeral=True)
        except Exception as e: await i.followup.send(f"❌ {e}",ephemeral=True)

@bot.tree.command(name="manage", description="⚙️ Manage a VPS")
@app_commands.describe(container_id="Container ID")
async def manage(interaction: discord.Interaction, container_id: str):
    c=get_container_by_id(container_id)
    if not c:
        await interaction.response.send_message("❌ Not found",ephemeral=True); return
    admin=await is_admin_role_only(interaction)
    if c["user_id"]!=str(interaction.user.id) and not admin:
        await interaction.response.send_message("🚫 You can only manage your own VPS.",ephemeral=True); return
    try:
        status=subprocess.check_output(["docker","inspect","-f","{{.State.Status}}",c["container_id"]]).decode().strip().upper()
    except: status="UNKNOWN"
    e=discord.Embed(title=f"🖥 VPS {c['container_id'][:12]}",color=EMBED_COLOR)
    e.add_field(name="📊 Info",value=f"**OS:** {c['os']}  •  **RAM:** {c['ram']}  •  **CPU:** {c['cpu']}\n**Status:** {status}\n**SSH:** `{c['ssh']}`",inline=False)
    e.add_field(name="🎮 Controls",value="Use the buttons below.",inline=False)
    await interaction.response.send_message(embed=e,view=ManageView(c["container_id"],c["user_id"],admin))

# ========= /PING & /HELP =========
@bot.tree.command(name="ping", description="🏓 Check bot latency")
async def ping(i: discord.Interaction):
    await i.response.send_message(embed=discord.Embed(title="🏓 Pong!",description=f"{round(bot.latency*1000)} ms",color=0x00FF00))

@bot.tree.command(name="help", description="📘 Show all commands")
async def help_cmd(i: discord.Interaction):
    e=discord.Embed(title="📘 VPS Bot Commands",color=EMBED_COLOR)
    e.description=("**Admin:** /deploy / delete-user-container / list-all\n"
                   "**User:** /list / manage\n"
                   "**General:** /ping / help")
    await i.response.send_message(embed=e,ephemeral=True)

# ========= BOT READY =========
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

bot.run(TOKEN)

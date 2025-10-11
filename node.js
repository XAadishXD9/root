// ===== EAGLENODE24x7 Discord + Minecraft Bot =====
const { Client, GatewayIntentBits, SlashCommandBuilder, Routes, REST } = require("discord.js");
const mineflayer = require("mineflayer");

const TOKEN = "YOUR_DISCORD_BOT_TOKEN"; // 🔒 Replace with your Discord bot token
const CLIENT_ID = "YOUR_CLIENT_ID"; // Discord Application ID
const GUILD_ID = "YOUR_GUILD_ID"; // Discord Server ID (right-click your server → Copy ID)

let mcBot = null; // Bot for control commands
let chatLogger = null; // Bot for chat logging

// === Create Discord client ===
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages]
});

// === Slash command definitions ===
const commands = [
  new SlashCommandBuilder()
    .setName("botcommand")
    .setDescription("Control your Minecraft bot EAGLENODE24x7")
    .addStringOption(opt =>
      opt.setName("action")
        .setDescription("Choose an action")
        .setRequired(true)
        .addChoices(
          { name: "join", value: "join" },
          { name: "leave", value: "leave" },
          { name: "say", value: "say" },
          { name: "creative", value: "creative" },
          { name: "survival", value: "survival" }
        )
    )
    .addStringOption(opt =>
      opt.setName("message")
        .setDescription("Message to send (only for 'say')")
    ),

  new SlashCommandBuilder()
    .setName("logserverchat")
    .setDescription("Connect to a Minecraft server and log chat to this channel")
    .addStringOption(opt =>
      opt.setName("ip")
        .setDescription("Server IP (e.g. eaglenode24x7.aternos.me)")
        .setRequired(true)
    )
    .addIntegerOption(opt =>
      opt.setName("port")
        .setDescription("Server port (default 25565)")
        .setRequired(true)
    )
].map(cmd => cmd.toJSON());

// === Register commands ===
const rest = new REST({ version: "10" }).setToken(TOKEN);
(async () => {
  try {
    console.log("🔧 Registering slash commands...");
    await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
    console.log("✅ Commands registered!");
  } catch (err) {
    console.error("❌ Command registration failed:", err);
  }
})();

// === Spawn main Minecraft bot ===
function spawnBot() {
  mcBot = mineflayer.createBot({
    host: "YOUR_SERVER_IP", // e.g. eaglenode24x7.aternos.me
    port: 25565,
    username: "EAGLENODE24x7"
  });

  mcBot.on("login", () => console.log("✅ EAGLENODE24x7 joined Minecraft server"));
  mcBot.on("end", () => console.log("⚠️ Bot disconnected"));
  mcBot.on("error", err => console.log("❌ Error:", err.message));
}

// === Command handler ===
client.on("interactionCreate", async (interaction) => {
  if (!interaction.isCommand()) return;

  // /botcommand
  if (interaction.commandName === "botcommand") {
    const action = interaction.options.getString("action");
    const message = interaction.options.getString("message");

    switch (action) {
      case "join":
        if (mcBot) return interaction.reply("⚠️ Bot already online!");
        spawnBot();
        return interaction.reply("✅ EAGLENODE24x7 joining Minecraft server...");
      case "leave":
        if (!mcBot) return interaction.reply("❌ Bot not online!");
        mcBot.quit("Left by command");
        mcBot = null;
        return interaction.reply("👋 Bot left the server.");
      case "say":
        if (!mcBot) return interaction.reply("❌ Bot not connected!");
        mcBot.chat(message || "");
        return interaction.reply(`💬 Bot said: "${message}"`);
      case "creative":
        if (!mcBot) return interaction.reply("❌ Bot not connected!");
        mcBot.chat("/gamemode creative EAGLENODE24x7");
        return interaction.reply("🎨 Bot changed to Creative mode.");
      case "survival":
        if (!mcBot) return interaction.reply("❌ Bot not connected!");
        mcBot.chat("/gamemode survival EAGLENODE24x7");
        return interaction.reply("🟢 Bot changed to Survival mode.");
    }
  }

  // /logserverchat
  if (interaction.commandName === "logserverchat") {
    const ip = interaction.options.getString("ip");
    const port = interaction.options.getInteger("port");
    const channel = interaction.channel;

    await interaction.reply(`📡 Connecting to **${ip}:${port}** to log chat...`);

    if (chatLogger) {
      try { chatLogger.quit(); } catch {}
      chatLogger = null;
    }

    chatLogger = mineflayer.createBot({
      host: ip,
      port: port,
      username: "EAGLENODE24x7"
    });

    chatLogger.on("login", () => channel.send(`✅ Connected to **${ip}:${port}**`));
    chatLogger.on("chat", (username, message) => {
      if (username !== chatLogger.username) {
        channel.send(`💬 **${username}:** ${message}`);
      }
    });
    chatLogger.on("end", () => {
      channel.send("⚠️ Disconnected — retrying in 10 seconds...");
      setTimeout(() => {
        try { chatLogger.connect(); } catch (err) {
          channel.send("❌ Reconnect failed: " + err.message);
        }
      }, 10000);
    });
    chatLogger.on("error", err => channel.send("❌ Error: " + err.message));
  }
});

client.login(TOKEN);

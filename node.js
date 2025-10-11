// EAGLENODE24x7 Discord → Minecraft logger
// Uses Discord.js v14 and Mineflayer
// Checks if IP:port are online before connecting

import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder } from "discord.js";
import mineflayer from "mineflayer";
import net from "net";
import dotenv from "dotenv";
dotenv.config();

// ---- Discord setup ----
const client = new Client({ intents: [GatewayIntentBits.Guilds] });
const TOKEN = process.env.TOKEN;
const CLIENT_ID = process.env.CLIENT_ID;
const GUILD_ID = process.env.GUILD_ID;

// ---- Slash command registration ----
const commands = [
  new SlashCommandBuilder()
    .setName("logserverchat")
    .setDescription("Connect the bot to a Minecraft server and log its chat.")
    .addStringOption(opt =>
      opt.setName("ip")
        .setDescription("Minecraft server IP")
        .setRequired(true))
    .addIntegerOption(opt =>
      opt.setName("port")
        .setDescription("Server port")
        .setRequired(true))
].map(cmd => cmd.toJSON());

const rest = new REST({ version: "10" }).setToken(TOKEN);
await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
console.log("✅ /logserverchat command registered!");

// ---- Utility: check if IP:port is reachable ----
function checkServer(ip, port, timeout = 4000) {
  return new Promise(resolve => {
    const socket = new net.Socket();
    const onError = () => {
      socket.destroy();
      resolve(false);
    };
    socket.setTimeout(timeout);
    socket.once("error", onError);
    socket.once("timeout", onError);
    socket.connect(port, ip, () => {
      socket.end();
      resolve(true);
    });
  });
}

// ---- Discord command handler ----
client.on("interactionCreate", async interaction => {
  if (!interaction.isChatInputCommand()) return;
  if (interaction.commandName === "logserverchat") {
    const ip = interaction.options.getString("ip");
    const port = interaction.options.getInteger("port");

    await interaction.reply(`🔍 Checking server **${ip}:${port}** ...`);

    const online = await checkServer(ip, port);
    if (!online) {
      await interaction.followUp("🔴 Server offline or invalid — please check IP and port.");
      return;
    }

    await interaction.followUp("🟢 Server online — connecting now...");

    const mcBot = mineflayer.createBot({
      host: ip,
      port: port,
      username: "EAGLENODE24x7"
    });

    mcBot.once("login", () => {
      interaction.followUp("✅ Connected to Minecraft server!");
    });

    mcBot.on("chat", (username, message) => {
      interaction.channel.send(`💬 **${username}:** ${message}`);
    });

    mcBot.on("end", () => {
      interaction.channel.send("⚠️ Minecraft bot disconnected.");
    });

    mcBot.on("error", err => {
      interaction.channel.send(`❌ Minecraft bot error: ${err.message}`);
    });
  }
});

client.once("ready", () => console.log(`🤖 Logged in as ${client.user.tag}`));
client.login(TOKEN);

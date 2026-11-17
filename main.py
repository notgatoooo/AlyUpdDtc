import asyncio, hashlib, json, os, random
from pathlib import Path
from typing import Any
import aiohttp, discord
from discord import app_commands, ui
from discord.ext import tasks

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE") # input your shit here.
URLS = ("https://cdn.overdrivehub.xyz/module.lua", "https://cdn.overdrivehub.xyz/bootstrapper.lua")
LINES = ("yay, we're saved!", "be happy a new updated!!", "holy shit!!!", "REEEEEEE-", "i'am so fucking happy", "how to get free overdrive h?", "h-hi guys i-i'm new~", "stupid dog", "if u got this pfp and stupid dog u know ball")

DATA_DIR = Path("./data")
CACHE_FILE, CONFIG_FILE = DATA_DIR / "cache.json", DATA_DIR / "configs.json"


def load_json(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError): return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def update_view(line: str, role_id: int | None) -> ui.LayoutView:
    view = ui.LayoutView(timeout=None)
    if role_id is not None: view.add_item(ui.TextDisplay(f"<@&{role_id}>"))
    view.add_item(ui.Container(
        ui.MediaGallery(discord.MediaGalleryItem(media="https://raw.githubusercontent.com/notgatoooo/Random/refs/heads/main/Update.png", description="Update")),
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ui.TextDisplay("## Update Detected!"),
        ui.TextDisplay(f"-# {line}"),
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ui.TextDisplay("An update to the Alyxius *(Overdrive Hub)* files has been detected, this may mean an update is coming. <a:d_:1515056414718951564>"),
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ui.ActionRow(ui.Button(style=discord.ButtonStyle.link, label="Get Script", url="https://overdrivehub.xyz/")),
        ui.ActionRow(ui.Button(style=discord.ButtonStyle.link, label="Bot Source", url="https://github.com/notgatoooo/AlyUpdDtc")),
    ))
    return view


class MonitorBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.http_session: aiohttp.ClientSession | None = None
        self.cache: dict[str, dict[str, str]] = load_json(CACHE_FILE)
        self.configs: dict[str, dict[str, int | None]] = load_json(CONFIG_FILE)

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        await self.tree.sync()
        self.check_pages.start()

    async def close(self) -> None:
        self.check_pages.cancel()
        if self.http_session and not self.http_session.closed: await self.http_session.close()
        await super().close()

    async def on_ready(self) -> None:
        print(f"Ready as {self.user} | {len(self.configs)} server(s) configured")

    async def fetch_url(self, url: str) -> tuple[bool, bool]:
        assert self.http_session is not None
        prev, headers = self.cache.get(url, {}), {"User-Agent": "Mozilla/5.0"}
        if prev.get("etag"): headers["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"): headers["If-Modified-Since"] = prev["last_modified"]

        try:
            async with self.http_session.get(url, headers=headers) as resp:
                if resp.status == 304: return False, False
                resp.raise_for_status()
                body, etag, last_mod = await resp.read(), resp.headers.get("ETag", ""), resp.headers.get("Last-Modified", "")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            print(f"err: {url}: {err}")
            return False, False

        digest, old_digest = hashlib.sha256(body).hexdigest(), prev.get("sha256")
        if digest == old_digest and etag == prev.get("etag", "") and last_mod == prev.get("last_modified", ""): return False, False

        self.cache[url] = {"sha256": digest, "etag": etag, "last_modified": last_mod}
        return (old_digest is not None and digest != old_digest), True

    async def send_alert(self, guild_id: str, cfg: dict[str, int | None], line: str) -> None:
        channel_id, role_id = cfg.get("channel_id"), cfg.get("role_id")
        if not channel_id: return

        if role_id is not None and str(role_id) != guild_id:
            ping_role_id, allowed = role_id, discord.AllowedMentions(everyone=False, users=False, roles=[discord.Object(id=role_id)])
        else:
            ping_role_id, allowed = None, discord.AllowedMentions.none()

        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if isinstance(channel, discord.abc.Messageable):
                await channel.send(view=update_view(line, ping_role_id), allowed_mentions=allowed)
        except discord.DiscordException as err:
            print(f"err: guild {guild_id}: {err}")

    @tasks.loop(seconds=60)
    async def check_pages(self) -> None:
        results = await asyncio.gather(*(self.fetch_url(u) for u in URLS))
        if any(dirty for _, dirty in results): save_json(CACHE_FILE, self.cache)
        if any(changed for changed, _ in results) and self.configs:
            line = random.choice(LINES)
            await asyncio.gather(*(self.send_alert(gid, cfg, line) for gid, cfg in list(self.configs.items())))

    @check_pages.before_loop
    async def before_check_pages(self) -> None:
        await self.wait_until_ready()


bot = MonitorBot()


@bot.tree.command(name="config", description="configurations basically lel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(channel="the channel where update alerts will be sent", role="optional role to ping (ignore for no ping)")
async def config_cmd(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None) -> None:
    if interaction.guild is None: return
    if role is not None and role.is_default():
        await interaction.response.send_message("yo.", ephemeral=True)
        return

    bot.configs[str(interaction.guild.id)] = {"channel_id": channel.id, "role_id": role.id if role else None}
    save_json(CONFIG_FILE, bot.configs)

    perms = channel.permissions_for(interaction.guild.me)
    missing = [n for n, ok in (("View Channel", perms.view_channel), ("Send Messages", perms.send_messages)) if not ok]
    warn = f"\n\HEY!!!, missing `{', '.join(missing)}` in {channel.mention}." if missing else ""
    await interaction.response.send_message(f"Saved config for **{interaction.guild.name}**:\n• Channel: {channel.mention}\n• Role ping: {role.mention if role else 'None (no ping)'}{warn}", ephemeral=True)

if __name__ == "__main__":
    print("gato does not make gay things.")
    bot.run(TOKEN)

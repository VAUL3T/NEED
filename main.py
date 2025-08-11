# bot.py
import discord
from discord.ext import commands
from discord.ext.commands import MissingPermissions
import json
import os
import time
from collections import defaultdict
import aiofiles
import asyncio
import io
from io import BytesIO
from discord import app_commands
from discord.ui import View, button

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)

# ✅ EDIT: Put your whitelisted guild(s) and default data file here
WHITELISTED_GUILDS = [1345476135487672350]
DATA_FILE = "1345476135487672350.json"
BACKUP_FILE = "user_backups.json"

@bot.event
async def on_ready():
    for guild_id in WHITELISTED_GUILDS:
        try:
            bot.tree.copy_global_to(guild=discord.Object(id=guild_id))
            await bot.tree.sync(guild=discord.Object(id=guild_id))
        except Exception as e:
            print(f"Failed to sync commands for guild {guild_id}: {e}")
    print(f"Bot is ready and commands synced for {len(WHITELISTED_GUILDS)} guild(s).")

# Load persistent data
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            auto_react_data = json.load(f)
    except Exception:
        auto_react_data = {}
else:
    auto_react_data = {}

# Async save
async def save_data():
    # Ensure directory exists where necessary
    async with aiofiles.open(DATA_FILE, "w") as f:
        await f.write(json.dumps(auto_react_data, indent=2))

ADMIN_DATA_FILE = "bot.json"
if os.path.exists(ADMIN_DATA_FILE):
    with open(ADMIN_DATA_FILE, "r") as f:
        admin_data = json.load(f)
else:
    admin_data = {"admins": [445468274659033088]}
    with open(ADMIN_DATA_FILE, "w") as f:
        json.dump(admin_data, f)

async def save_admins():
    async with aiofiles.open(ADMIN_DATA_FILE, "w") as f:
        await f.write(json.dumps(admin_data, indent=2))

# Reusable embed builder
def make_embed(description: str, color=discord.Color.blurple(), title: str = None):
    e = discord.Embed(description=description, color=color)
    if title:
        e.title = title
    return e

# In-memory short-term spam tracking: user_id -> list[timestamps]
message_history = defaultdict(list)  # user_id -> list of timestamps (float)

# Global check: only allow commands from whitelisted guilds
@bot.check
async def globally_whitelist_guilds(ctx):
    return ctx.guild and ctx.guild.id in WHITELISTED_GUILDS

@bot.tree.command(name="echo", description="Need echos you")
@app_commands.checks.has_permissions(manage_messages=True)
async def echo(interaction: discord.Interaction, text: str):
    if interaction.guild_id not in WHITELISTED_GUILDS:
        await interaction.response.send_message(embed=make_embed("<:warning:1401590117499408434> This command is not allowed in this guild.", discord.Color.orange()))
        return
    
    if interaction.user.id not in admin_data["admins"]:
        await interaction.response.send_message(embed=make_embed("<:warning:1401590117499408434> This command requires an **extra whitelist**", discord.Color.orange()))
        return

    await interaction.channel.send(text)
    await interaction.response.send_message("👍", ephemeral=True)
    
@bot.command()
async def admin(ctx, member: discord.Member = None):
    if member is None:
        await ctx.send(embed=make_embed("Syntax: $admin @user", discord.Color.orange()))
        return
    
    if ctx.author.id not in admin_data["admins"]:
        await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> {ctx.author.mention} You must be an **admin** to run this command", discord.Color.orange()))
        return

    user_id = member.id
    username = member.name

    if user_id in admin_data["admins"]:
        admin_data["admins"].remove(user_id)
        await save_admins()
        await ctx.send(embed=make_embed(f"<:error:1401589697477742742> {ctx.author.mention} **{username}** is no longer an admin", discord.Color.red()))
    else:
        admin_data["admins"].append(user_id)
        await save_admins()
        await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> {ctx.author.mention} **{username}** is now an admin", discord.Color.green()))

class ConfirmView(View):
    def __init__(self, author):
        super().__init__(timeout=30)
        self.author = author
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "<:warning:1401590117499408434> This confirmation is not for you.",
                ephemeral=True
            )
            return False
        return True

    @button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

    @button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()

@commands.has_permissions(manage_guild=True, administrator=True)
@bot.command()
async def backup(ctx, target=None, action=None, member: discord.Member = None):
    if target is None:
        embed = discord.Embed(
            title="Command: backup",
            description=(
                "Syntax : `$backup users`\n"
                "Syntax : `$backup users file`\n"
                "Syntax : `$backup users load <@user>`\n"
                "Syntax : `$backup server`\n"
                "Syntax : `$backup server file`\n"
                "Syntax : `$backup server load`"
            ),
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)
        return

    if target.lower() == "users":
        if action is None or action.lower() == "backup":
            members = [m for m in ctx.guild.members if not m.bot]
            data = {str(m.id): [r.id for r in m.roles if r != ctx.guild.default_role] for m in members}
            size_kb = len(json.dumps(data).encode("utf-8")) / 1024
            size_mb = round(size_kb / 1024, 2)

            view = ConfirmView(ctx.author)
            await ctx.send(embed=make_embed(
                f"<:warning:1401590117499408434> Are you sure you want to backup all users? Approximate file size is **{size_mb}MB** ?",
                discord.Color.orange()
            ), view=view)
            await view.wait()
            if not view.value:
                return

            if size_mb > 500:
                await ctx.send(embed=make_embed("<a:clock:1401933869804032061> This may take a while . . .", discord.Color.orange()))

            with open("user_backups.json", "w") as f:
                json.dump(data, f, indent=4)

            user_count = len(data)
            await ctx.send(embed=make_embed(
                f"<:files:1403754002989973566> Backup created successfully with size **{size_mb}MB** with **{user_count} Users**",
                discord.Color.green()
            ))
        elif action.lower() == "file":
            if not os.path.exists("user_backups.json"):
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> No backup file found.", discord.Color.orange()))
                return
            try:
                await ctx.author.send(file=discord.File("user_backups.json"))
                await ctx.send(embed=make_embed("<:Ok:1401589649088057425> File sent via **DMs**", discord.Color.green()))
            except discord.Forbidden:
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> I couldn't send you the file via DMs. Please check your privacy settings.", discord.Color.orange()))
        elif action.lower() == "load":
            if member is None:
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> Missing required argument: `member`", discord.Color.orange()))
                return
            if not os.path.exists("user_backups.json"):
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> No backup file found.", discord.Color.orange()))
                return
            with open("user_backups.json", "r") as f:
                data = json.load(f)
            if str(member.id) not in data:
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> User not found in backup.", discord.Color.orange()))
                return

            view = ConfirmView(ctx.author)
            await ctx.send(embed=make_embed(
                "<:warning:1401590117499408434> Do you want to **restore the user**?",
                discord.Color.orange()
            ), view=view)
            await view.wait()
            if not view.value:
                return

            roles = [ctx.guild.get_role(rid) for rid in data[str(member.id)] if ctx.guild.get_role(rid)]
            failed = sum(1 for rid in data[str(member.id)] if ctx.guild.get_role(rid) is None)
            await member.add_roles(*roles, reason="User restored")
            await ctx.send(embed=make_embed(
                f"<:Ok:1401589649088057425> User restored **{failed} Roles failed | {len(roles)} Roles given**",
                discord.Color.green()
            ))
        else:
            await ctx.send(embed=make_embed("<:warning:1401590117499408434> Unknown action for users backup.", discord.Color.orange()))
    elif target.lower() == "server":
        if action is None or action.lower() == "backup":
            guild = ctx.guild
            categories = []
            for cat in guild.categories:
                cat_data = {"name": cat.name, "channels": []}
                for ch in sorted(cat.channels, key=lambda c: c.position):
                    ch_data = {
                        "name": ch.name,
                        "type": str(ch.type),
                        "position": ch.position,
                        "slowmode_delay": getattr(ch, "slowmode_delay", 0),
                        "nsfw": getattr(ch, "nsfw", False),
                        "bitrate": getattr(ch, "bitrate", None),
                        "user_limit": getattr(ch, "user_limit", None)
                    }
                    cat_data["channels"].append(ch_data)
                categories.append(cat_data)

            uncategorized = []
            for ch in sorted([c for c in guild.channels if c.category is None], key=lambda c: c.position):
                ch_data = {
                    "name": ch.name,
                    "type": str(ch.type),
                    "position": ch.position,
                    "slowmode_delay": getattr(ch, "slowmode_delay", 0),
                    "nsfw": getattr(ch, "nsfw", False),
                    "bitrate": getattr(ch, "bitrate", None),
                    "user_limit": getattr(ch, "user_limit", None)
                }
                uncategorized.append(ch_data)

            data = {"categories": categories, "uncategorized": uncategorized}
            size_kb = len(json.dumps(data).encode("utf-8")) / 1024
            size_mb = round(size_kb / 1024, 2)

            view = ConfirmView(ctx.author)
            await ctx.send(embed=make_embed(
                f"<:warning:1401590117499408434> Are you sure you want to backup the server? Approximate file size is **{size_mb}MB** ?",
                discord.Color.orange()
            ), view=view)
            await view.wait()
            if not view.value:
                return

            if size_mb > 500:
                await ctx.send(embed=make_embed("<a:clock:1401933869804032061> This may take a while . . .", discord.Color.orange()))

            with open("server_backup.json", "w") as f:
                json.dump(data, f, indent=4)

            total_channels = sum(len(c["channels"]) for c in categories) + len(uncategorized)
            await ctx.send(embed=make_embed(
                f"<:files:1403754002989973566> Backup created successfully with size **{size_mb}MB** with **{total_channels} Channels**",
                discord.Color.green()
            ))
        elif action and action.lower() == "file":
            if not os.path.exists("server_backup.json"):
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> No backup file found.", discord.Color.orange()))
                return
            try:
                await ctx.author.send(file=discord.File("server_backup.json"))
                await ctx.send(embed=make_embed("<:Ok:1401589649088057425> File sent via **DMs**", discord.Color.green()))
            except discord.Forbidden:
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> I couldn't send you the file via DMs. Please check your privacy settings.", discord.Color.orange()))
        elif action and action.lower() == "load":
            if not os.path.exists("server_backup.json"):
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> No backup file found.", discord.Color.orange()))
                return
            with open("server_backup.json", "r") as f:
                data = json.load(f)

            view = ConfirmView(ctx.author)
            await ctx.send(embed=make_embed(
                "<:warning:1401590117499408434> Do you want to **restore the server**?",
                discord.Color.orange()
            ), view=view)
            await view.wait()
            if not view.value:
                return

            for ch in ctx.guild.channels:
                await ch.delete()

            for cat_data in data["categories"]:
                category = await ctx.guild.create_category(cat_data["name"])
                for ch_data in cat_data["channels"]:
                    if ch_data["type"] == "text":
                        await ctx.guild.create_text_channel(
                            ch_data["name"],
                            category=category,
                            slowmode_delay=ch_data["slowmode_delay"],
                            nsfw=ch_data["nsfw"],
                            position=ch_data["position"]
                        )
                    elif ch_data["type"] == "voice":
                        await ctx.guild.create_voice_channel(
                            ch_data["name"],
                            category=category,
                            bitrate=ch_data["bitrate"],
                            user_limit=ch_data["user_limit"],
                            position=ch_data["position"]
                        )
            for ch_data in data["uncategorized"]:
                if ch_data["type"] == "text":
                    await ctx.guild.create_text_channel(
                        ch_data["name"],
                        slowmode_delay=ch_data["slowmode_delay"],
                        nsfw=ch_data["nsfw"],
                        position=ch_data["position"]
                    )
                elif ch_data["type"] == "voice":
                    await ctx.guild.create_voice_channel(
                        ch_data["name"],
                        bitrate=ch_data["bitrate"],
                        user_limit=ch_data["user_limit"],
                        position=ch_data["position"]
                    )

            await ctx.send(embed=make_embed("<:Ok:1401589649088057425> Server restored", discord.Color.green()))
        else:
            await ctx.send(embed=make_embed("<:warning:1401590117499408434> Unknown action for server backup.", discord.Color.orange()))
    else:
        await ctx.send(embed=make_embed("<:warning:1401590117499408434> Unknown target. Use `users` or `server`.", discord.Color.orange()))
# ===================== AUTOREACT =====================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def autoreact(ctx, *args):
    guild_id = str(ctx.guild.id)
    config = auto_react_data.setdefault(guild_id, {})

    # list
    if len(args) == 1 and args[0].lower() == "list":
        items = []
        for uid, emoji in config.items():
            # only numeric keys correspond to autoreact user entries (others are config keys)
            if uid.isdigit():
                try:
                    user = await bot.fetch_user(int(uid))
                    items.append(f"{user.name}#{user.discriminator} → {emoji}")
                except Exception:
                    items.append(f"{uid} → {emoji}")
        desc = "\n".join(items) or "*No autoreacts set.*"
        return await ctx.send(embed=make_embed(desc, discord.Color.dark_grey(), title="AutoReacts"))

    # remove all
    if len(args) == 2 and args[0].lower() == "remove" and args[1].lower() == "all":
        config_keys = {k for k in config.keys()}
        for k in config_keys:
            if k.isdigit():
                config.pop(k, None)
        await save_data()
        return await ctx.send(embed=make_embed("<:Ok:1401589649088057425> Removed all auto reacts.", discord.Color.green()))

    if len(args) < 2:
        embed = discord.Embed(
            title="Command: autoreact",
            description="Syntax : `$autoreact (emoji) (user)`\n`$autoreact list`  or `$autoreact remove all`",
            color=discord.Color.blurple()
        )
        return await ctx.send(embed=embed)

    emoji = args[0]
    try:
        member = await commands.MemberConverter().convert(ctx, args[1])
    except commands.BadArgument:
        return await ctx.send(embed=make_embed("<:error:1401589697477742742> Invalid user.", discord.Color.red()))

    user_id = str(member.id)

    if user_id in config:
        # remove mapping
        del config[user_id]
        embed = make_embed(f"<:error:1401589697477742742> Stopped auto reacting with {emoji} to {member.mention}", discord.Color.red())
    else:
        config[user_id] = emoji
        embed = make_embed(f"<:Ok:1401589649088057425> Auto reacting with {emoji} to {member.mention}", discord.Color.green())

    await save_data()
    await ctx.send(embed=embed)

# ===================== ANTIRAID =====================

@bot.command()
@commands.has_permissions(manage_guild=True)
async def antiraid(ctx, mode: str = None, state: str = None, *, options: str = None):
    guild_id = str(ctx.guild.id)

    # Ensure storage exists
    if guild_id not in auto_react_data:
        auto_react_data[guild_id] = {}
    if "antiraid" not in auto_react_data[guild_id]:
        auto_react_data[guild_id]["antiraid"] = {
            "spam": {"enabled": False, "action": None},
            "external_app": {
                "enabled": False,
                "action": None,
                "channels": [],
                "previous_perms": {}  # NEW: store old perms for rollback
            }
        }

    # Syntax help embed (unchanged)
    if not mode:
        embed = discord.Embed(
            title="Command: antiraid",
            description="Syntax : `$antiraid spam on|off [do:<mute|kick|ban>]`\n"
                        "Syntax : `$antiraid external_app on|off [do:<mute|kick|ban>] [channels:<id|all>]`",
            color=discord.Color.blurple()
        )
        return await ctx.send(embed=embed)

    # Error embed
    error_embed = discord.Embed(
        description="<:error:1401589697477742742> Invalid syntax / channel / id / prefix / \n<:warning:1401590117499408434>",
        color=discord.Color.red()
    )

    # ---------------- SPAM MODE ----------------
    if mode.lower() == "spam":
        if state not in ["on", "off"]:
            return await ctx.send(embed=error_embed)

        if state.lower() == "off":
            auto_react_data[guild_id]["antiraid"]["spam"] = {"enabled": False, "action": None}
            await save_data()
            return await ctx.send(embed=discord.Embed(
                description="<:Ok:1401589649088057425> Anti-raid spam disabled.",
                color=discord.Color.green()
            ))

        if not options or not options.startswith("do:"):
            return await ctx.send(embed=error_embed)

        action = options[3:].lower()
        if action not in ["ban", "kick", "mute"]:
            return await ctx.send(embed=error_embed)

        auto_react_data[guild_id]["antiraid"]["spam"] = {"enabled": True, "action": action}
        await save_data()
        return await ctx.send(embed=discord.Embed(
            description=f"<:Ok:1401589649088057425> Anti-raid spam enabled — action: **{action}**",
            color=discord.Color.green()
        ))

    # ---------------- EXTERNAL APP MODE ----------------
    elif mode.lower() == "external_app":
        if state not in ["on", "off"]:
            return await ctx.send(embed=error_embed)

        target_role = ctx.guild.default_role

        if state.lower() == "off":
            # Rollback to previous permissions
            previous_perms = auto_react_data[guild_id]["antiraid"]["external_app"].get("previous_perms", {})
            for ch_id, old_value in previous_perms.items():
                ch = ctx.guild.get_channel(int(ch_id))
                if not ch:
                    continue
                try:
                    current_overwrites = ch.overwrites_for(target_role)
                    current_overwrites.update(use_external_apps=old_value)
                    await ch.set_permissions(target_role, overwrite=current_overwrites)
                except discord.Forbidden:
                    pass

            auto_react_data[guild_id]["antiraid"]["external_app"] = {
                "enabled": False,
                "action": None,
                "channels": [],
                "previous_perms": {}
            }
            await save_data()

            return await ctx.send(embed=discord.Embed(
                description="<:Ok:1401589649088057425> External app blocking disabled and permissions restored.",
                color=discord.Color.green()
            ))

        # Parse parameters
        if not options:
            return await ctx.send(embed=error_embed)

        parts = options.split()
        action = None
        channels_param = None
        for p in parts:
            if p.startswith("do:"):
                action = p[3:].lower()
            elif p.startswith("channels:"):
                channels_param = p[9:]

        if action not in ["ban", "kick", "mute"] or not channels_param:
            return await ctx.send(embed=error_embed)

        channels_list = []
        previous_perms = {}

        # Apply safe permission changes
        if channels_param.lower() == "all":
            for ch in ctx.guild.channels:
                try:
                    current_overwrites = ch.overwrites_for(target_role)
                    previous_perms[str(ch.id)] = current_overwrites.use_external_apps
                    current_overwrites.update(use_external_apps=False)
                    await ch.set_permissions(target_role, overwrite=current_overwrites)
                except discord.Forbidden:
                    pass
            channels_list = ["all"]
        else:
            try:
                channel_id = int(channels_param)
                ch = ctx.guild.get_channel(channel_id)
                if not ch:
                    return await ctx.send(embed=error_embed)

                current_overwrites = ch.overwrites_for(target_role)
                previous_perms[str(ch.id)] = current_overwrites.use_external_apps
                current_overwrites.update(use_external_apps=False)
                await ch.set_permissions(target_role, overwrite=current_overwrites)

                channels_list = [channel_id]
            except ValueError:
                return await ctx.send(embed=error_embed)

        auto_react_data[guild_id]["antiraid"]["external_app"] = {
            "enabled": True,
            "action": action,
            "channels": channels_list,
            "previous_perms": previous_perms
        }
        await save_data()

        return await ctx.send(embed=discord.Embed(
            description=f"<:Ok:1401589649088057425> External app blocking enabled in `{channels_param}` — action: **{action}**",
            color=discord.Color.green()
        ))

    # ---------------- UNKNOWN MODE ----------------
    else:
        return await ctx.send(embed=error_embed)

# ===================== FORCENICK =====================
@bot.command(name="forcenick")
@commands.has_permissions(manage_nicknames=True, manage_guild=True)
async def forcenickname(ctx, *args):
    if len(args) == 0:
        embed = discord.Embed(
            title="Command: forcenickname",
            description="Syntax : `$forcenick @user <nickname>`\n\n `$forcenick list [page]` or `$forcenick @user off`",
            color=discord.Color.blurple()
        )
        return await ctx.send(embed=embed)

    # Check if user wants list
    if args[0].lower() == "list":
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        guild_id = str(ctx.guild.id)
        config = auto_react_data.get(guild_id, {})
        forcenicks = config.get("forcenicknames", {})

        items = list(forcenicks.items())
        total = len(items)
        per_page = 5
        pages = max((total - 1) // per_page + 1, 1)

        if page < 1 or page > pages:
            return await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> Page `{page}` is out of range. Total pages: `{pages}`.", discord.Color.red()))

        start = (page - 1) * per_page
        end = start + per_page
        entries = items[start:end]

        desc = ""
        for i, (user_id, nick) in enumerate(entries, start=1 + start):
            user = ctx.guild.get_member(int(user_id))
            if user:
                name = user.name
            else:
                try:
                    user_obj = await bot.fetch_user(int(user_id))
                    name = user_obj.name
                except:
                    name = f"Unknown User ({user_id})"
            desc += f"{i}. {name} → `{nick}`\n"

        embed = discord.Embed(
            title="Forced Names",
            description=desc or "*No forced nicknames set.*",
            color=discord.Color.dark_grey()
        )
        embed.set_footer(text=f"Page {page}/{pages} ({total} Member{'s' if total != 1 else ''})")
        return await ctx.send(embed=embed)

    # --- normal forcenick logic below ---
    try:
        member = await commands.MemberConverter().convert(ctx, args[0])
    except commands.BadArgument:
        embed = discord.Embed(
            title="Command: forcenickname",
            description="Syntax : `$forcenick @user <nickname>`\n\n `$forcenick list` or `$forcenick @user off`",
            color=discord.Color.blurple()
        )
        return await ctx.send(embed=embed)

    nickname = " ".join(args[1:])
    if nickname == "":
        return await ctx.send(embed=make_embed("Please supply a nickname or `off`.", discord.Color.orange()))

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    config = auto_react_data.setdefault(guild_id, {})
    forcenicks = config.setdefault("forcenicknames", {})

    if nickname.lower() == "off":
        if user_id in forcenicks:
            del forcenicks[user_id]
            await save_data()
            return await ctx.send(embed=make_embed(f"<:error:1401589697477742742> No longer forcing nickname for {member.mention}", discord.Color.orange()))
        else:
            return await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> No forced nickname was set for {member.mention}", discord.Color.orange()))

    if len(nickname) > 32:
        return await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> Nickname too long. Max 32 characters.", discord.Color.red()))

    forcenicks[user_id] = nickname
    await save_data()

    try:
        if member.nick != nickname:
            await member.edit(nick=nickname, reason="Force nick is set for this user")
    except discord.Forbidden:
        return await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> I don't have permission to change nickname of {member.mention}", discord.Color.red()))
    except Exception:
        # ignore other API errors but persist setting
        pass

    await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Now **forcing nickname** for **{member.mention}** to `{nickname}`", discord.Color.green()))

# ===================== AUTOREMOVE =====================

@bot.command()
@commands.has_permissions(manage_messages=True, manage_guild=True)
async def autoremove(ctx, *args):
    guild_id = str(ctx.guild.id)
    config = auto_react_data.setdefault(guild_id, {})

    if len(args) == 0:
        embed = discord.Embed(
            description="Syntax:\n`$autoremove messages @user [off]`\n`$autoremove reactions [emoji] @user [off]` or `$autoremove reactions @user [off]`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return

    mode = args[0].lower()
    emoji = None
    member = None
    off_flag = False

    if mode == "messages":
        if len(args) < 2:
            await ctx.send(embed=make_embed("Syntax:\n`$autoremove messages @user [off]`", discord.Color.orange()))
            return
        try:
            member = await commands.MemberConverter().convert(ctx, args[1])
        except commands.BadArgument:
            await ctx.send(embed=make_embed("<:error:1401589697477742742> Invalid user.", discord.Color.red()))
            return
        if len(args) > 2 and args[2].lower() == "off":
            off_flag = True

        if "autoremove_messages" not in config:
            config["autoremove_messages"] = {}

        user_id = str(member.id)
        if off_flag:
            if user_id in config["autoremove_messages"]:
                del config["autoremove_messages"][user_id]
                await save_data()
                await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Stopped autoremove messages for {member.mention}", discord.Color.green()))
            else:
                await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> No autoremove messages set for {member.mention}", discord.Color.orange()))
        else:
            config["autoremove_messages"][user_id] = True
            await save_data()
            await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Now autoremoving messages from {member.mention}", discord.Color.green()))

    elif mode == "reactions":
        # Check if args[1] is emoji or user
        if len(args) < 2:
            await ctx.send(embed=make_embed("Syntax:\n`$autoremove reactions [emoji] @user [off]` or `$autoremove reactions @user [off]`", discord.Color.orange()))
            return
        try:
            member = await commands.MemberConverter().convert(ctx, args[1])
            emoji = None
            idx = 1
        except commands.BadArgument:
            if len(args) < 3:
                await ctx.send(embed=make_embed("Syntax:\n`$autoremove reactions [emoji] @user [off]`", discord.Color.orange()))
                return
            emoji = args[1]
            try:
                member = await commands.MemberConverter().convert(ctx, args[2])
            except commands.BadArgument:
                await ctx.send(embed=make_embed("<:error:1401589697477742742> Invalid user.", discord.Color.red()))
                return
            idx = 2

        off_flag = False
        if len(args) > idx + 1 and args[idx + 1].lower() == "off":
            off_flag = True

        if "autoremove_reactions" not in config:
            config["autoremove_reactions"] = {}

        user_id = str(member.id)

        if off_flag:
            if emoji is None:
                removed_any = False
                keys_to_remove = []
                for key in list(config["autoremove_reactions"].keys()):
                    if ":" in key:
                        u, e = key.split(":", 1)
                        if u == user_id:
                            keys_to_remove.append(key)
                            removed_any = True
                for key in keys_to_remove:
                    del config["autoremove_reactions"][key]
                if removed_any:
                    await save_data()
                    await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Stopped autoremove reactions for all emojis from {member.mention}", discord.Color.green()))
                else:
                    await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> No autoremove reactions set for {member.mention}", discord.Color.orange()))
            else:
                key = f"{user_id}:{emoji}"
                if key in config["autoremove_reactions"]:
                    del config["autoremove_reactions"][key]
                    await save_data()
                    await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Stopped autoremove reactions {emoji} from {member.mention}", discord.Color.green()))
                else:
                    await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> No autoremove reaction {emoji} set for {member.mention}", discord.Color.orange()))
        else:
            if emoji is None:
                await ctx.send(embed=make_embed("<:warning:1401590117499408434> Please specify an emoji for reactions or use `off` to stop.", discord.Color.orange()))
                return
            key = f"{user_id}:{emoji}"
            config["autoremove_reactions"][key] = True
            await save_data()
            await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Now autoremoving reaction {emoji} from {member.mention}", discord.Color.green()))

    else:
        await ctx.send(embed=make_embed("Syntax:\n`$autoremove messages @user [off]`\n`$autoremove reactions [emoji] @user [off]` or `$autoremove reactions @user [off]`", discord.Color.orange()))

# ===================== ON MESSAGE + SPAM =====================
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    now = time.time()
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)

    config = auto_react_data.get(guild_id, {})
    emoji_react = config.get(user_id)
    if emoji_react:
        try:
            await message.add_reaction(emoji_react)
        except Exception:
            pass

    # maintain recent timestamps (sliding window)
    timestamps = message_history[user_id]
    timestamps = [t for t in timestamps if now - t <= 5]
    timestamps.append(now)
    message_history[user_id] = timestamps

    # Anti-raid spam handling
    if config.get("antiraid_spam_enabled") and len(timestamps) >= 5:
        action = config.get("antiraid_spam_action")
        reason = f"User triggered anti-raid"
        try:
            if action == "mute":
                role = discord.utils.get(message.guild.roles, name="Muted")
                if not role:
                    role = await message.guild.create_role(name="Muted")
                    for channel in message.guild.channels:
                        try:
                            await channel.set_permissions(role, send_messages=False, add_reactions=False)
                        except Exception:
                            # ignore permission issues per-channel
                            pass
                try:
                    await message.author.add_roles(role, reason=reason)
                except Exception:
                    pass

            elif action == "kick" and message.guild.me.guild_permissions.kick_members:
                try:
                    await message.author.kick(reason=reason)
                except Exception:
                    pass

            elif action == "ban" and message.guild.me.guild_permissions.ban_members:
                try:
                    await message.guild.ban(message.author, reason=reason)
                except Exception:
                    pass
        except Exception:
            pass

        # Reset their history to avoid repeated triggers in immediate succession
        message_history[user_id] = []

    # autoremove messages
    if config.get("autoremove_messages", {}).get(user_id):
        try:
            await message.delete()
        except Exception:
            pass

    await bot.process_commands(message)

# ===================== ON RAW REACTION ADD =====================
@bot.event
async def on_raw_reaction_add(payload):
    # ignore bot and DMs
    if payload.user_id == bot.user.id:
        return
    if payload.guild_id is None:
        return
    guild_id = str(payload.guild_id)
    config = auto_react_data.get(guild_id, {})
    if not config:
        return

    user_id = str(payload.user_id)
    autoremove_reactions = config.get("autoremove_reactions", {})

    emoji_str = str(payload.emoji)
    key = f"{user_id}:{emoji_str}"

    if key in autoremove_reactions:
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            # payload.member is available for intents.members; fallback to fetch_user
            user = payload.member or await bot.fetch_user(payload.user_id)
            await message.remove_reaction(payload.emoji, user)
        except Exception:
            pass

# ===================== LOG COMMAND (kept as requested) =====================
@bot.command()
@commands.has_permissions(manage_guild=True)
@commands.cooldown(1, 10, commands.BucketType.user)
async def log(ctx, target: str = None):
    guild_id = str(ctx.guild.id)

    config = auto_react_data.setdefault(guild_id, {})

    if target is None:
        embed = discord.Embed(
            title="Command: log",
            description="Syntax: `$log #channel` `$log <webhook_url>`",
            color=discord.Color.blurple()
        )
        return await ctx.send(embed=embed)

    if target.startswith("http"):  # Webhook URL
        config["log_webhook"] = target
        config.pop("log_channel", None)
        await save_data()
        embed = make_embed(f"<:Ok:1401589649088057425> Logging set to Webhook.", discord.Color.green())
        return await ctx.send(embed=embed)

    if ctx.message.channel_mentions:
        channel = ctx.message.channel_mentions[0]
        config["log_channel"] = channel.id
        config.pop("log_webhook", None)
        await save_data()
        embed = make_embed(f"<:Ok:1401589649088057425> Logging set to {channel.mention}", discord.Color.green())
        return await ctx.send(embed=embed)

    await ctx.send(embed=make_embed("<:error:1401589697477742742> Invalid target. Use a #channel or webhook URL.", discord.Color.red()))

# ===================== ROLE COMMAND =====================
@bot.command(name="role")
@commands.has_permissions(manage_roles=True, manage_guild=True)
async def role_command(ctx, *args):
    # special restriction in original - keep it
    if ctx.guild.id != 1345476135487672350:
        return

    if len(args) == 0:
        await ctx.send(embed=make_embed("Syntax:\n`$role @<role> block from:@<user>`\n`$role unblock @<role> from:@<user>`\n`$role block list`", discord.Color.orange()))
        return

    if args[0].lower() == "block" and len(args) >= 2 and args[1].lower() == "list":
        blocks = auto_react_data.get(str(ctx.guild.id), {}).get("role_blocks", {})
        entries = []
        for role_id, user_ids in blocks.items():
            for user_id in user_ids:
                role = ctx.guild.get_role(int(role_id))
                user = ctx.guild.get_member(int(user_id))
                if role and user:
                    entries.append(f"{role.mention} ⟶ {user.name}")

        page = 1
        if len(args) == 3 and args[2].isdigit():
            page = int(args[2])
        total_pages = max(1, (len(entries) + 4) // 5)
        start = (page - 1) * 5
        end = start + 5

        embed = discord.Embed(
            title="Blocked Roles",
            description="\n".join(f"{i+1}. {entry}" for i, entry in enumerate(entries[start:end], start=start)),
            color=discord.Color.greyple()
        )
        embed.set_footer(text=f"Page {page}/{total_pages} ({len(entries)} Blocks)")
        await ctx.send(embed=embed)
        return

    # Toggle: $role @user @role
    if len(args) == 2:
        try:
            member = await commands.MemberConverter().convert(ctx, args[0])
            role = await commands.RoleConverter().convert(ctx, args[1])
        except (commands.MemberNotFound, commands.RoleNotFound, commands.BadArgument):
            await ctx.send(embed=make_embed("<:error:1401589697477742742> Invalid user or role.", discord.Color.red()))
            return

        if role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Manual role toggle by {ctx.author}")
                await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> removed {role.mention} from {member.mention}", discord.Color.green()))
            except discord.Forbidden:
                await ctx.send(embed=make_embed("<:error:1401589697477742742> Missing permission to remove role.", discord.Color.red()))
        else:
            try:
                await member.add_roles(role, reason=f"Manual role toggle by {ctx.author}")
                await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> gave {member.mention} {role.mention}", discord.Color.green()))
            except discord.Forbidden:
                await ctx.send(embed=make_embed("<:error:1401589697477742742> Missing permission to give role.", discord.Color.red()))
        return

    # Syntax: $role @role block from:@user
    if len(args) >= 3:
        try:
            role = await commands.RoleConverter().convert(ctx, args[0])
        except commands.RoleNotFound:
            await ctx.send(embed=make_embed("<:error:1401589697477742742> Could not find role.", discord.Color.red()))
            return

        action = args[1].lower()
        target_arg = " ".join(args[2:]).replace("from:", "").strip()
        try:
            member = await commands.MemberConverter().convert(ctx, target_arg)
        except commands.MemberNotFound:
            await ctx.send(embed=make_embed("<:error:1401589697477742742> Could not find user.", discord.Color.red()))
            return

        guild_id = str(ctx.guild.id)
        role_id = str(role.id)
        user_id = str(member.id)

        data = auto_react_data.setdefault(guild_id, {})
        role_blocks = data.setdefault("role_blocks", {})

        if action == "block":
            if role_id not in role_blocks:
                role_blocks[role_id] = []
            if user_id not in role_blocks[role_id]:
                role_blocks[role_id].append(user_id)
            await save_data()
            await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Now blocking role {role.mention} from {member.mention}", discord.Color.green()))
        elif action == "unblock":
            if role_id in role_blocks and user_id in role_blocks[role_id]:
                role_blocks[role_id].remove(user_id)
                if not role_blocks[role_id]:
                    del role_blocks[role_id]
                await save_data()
                await ctx.send(embed=make_embed(f"<:Ok:1401589649088057425> Removed block of {role.mention} from {member.mention}", discord.Color.green()))
            else:
                await ctx.send(embed=make_embed(f"<:warning:1401590117499408434> No block found for {member.mention} and {role.mention}", discord.Color.orange()))
        else:
            await ctx.send(embed=make_embed("Syntax:\n`$role @<role> block from:@<user>`\n`$role unblock @<role> from:@<user>`\n`$role block list`", discord.Color.orange()))
    else:
        await ctx.send(embed=make_embed("Syntax:\n`$role @<role> block from:@<user>`\n`$role unblock @<role> from:@<user>`\n`$role block list`", discord.Color.orange()))

# ===================== ON MEMBER UPDATE (enforce forcenick & role blocks) =====================
@bot.event
async def on_member_update(before, after):
    # Forcenickname Enforcement
    guild_id = str(after.guild.id)
    config = auto_react_data.get(guild_id, {})

    forced_nicks = config.get("forcenicknames", {})
    if str(after.id) in forced_nicks:
        desired_nick = forced_nicks[str(after.id)]
        if after.nick != desired_nick:
            try:
                await after.edit(nick=desired_nick, reason="Force nick enforcement set for user")
            except discord.Forbidden:
                print(f"[ForceNick] Missing permissions to enforce nickname for {after.id}")
            except discord.HTTPException as e:
                print(f"[ForceNick] API error for {after.id}: {e}")

    # Role Block Enforcement
    role_blocks = config.get("role_blocks", {})
    for role in after.roles:
        if str(role.id) in role_blocks and str(after.id) in role_blocks[str(role.id)]:
            try:
                await after.remove_roles(role, reason="Role block enforcement set for user")
            except discord.Forbidden:
                print(f"[RoleBlock] Missing permissions to remove role {role.id} from {after.id}")
            except discord.HTTPException as e:
                print(f"[RoleBlock] API error for {after.id}: {e}")

# ===================== COMMAND LOGGING LISTENER (keeps original functionality minimal) =====================
@bot.listen("on_command_completion")
async def log_command(ctx):
    # keep minimal — original behavior was sending an embed via webhook or channel
    if not ctx.guild or ctx.command is None:
        return

    guild_id = str(ctx.guild.id)
    config = auto_react_data.get(guild_id, {})

    log_embed = discord.Embed(
        description=f"Moderator : {ctx.author.id}\nCommand : {ctx.message.content}\nTime : {discord.utils.format_dt(discord.utils.utcnow(), 'F')}",
        color=discord.Color.dark_grey()
    )

    if "log_webhook" in config:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(config["log_webhook"], session=session)
            try:
                await webhook.send(embed=log_embed, username="Mod Log", silent=True)
            except Exception as e:
                print("Webhook Logging failed:", e)
    elif "log_channel" in config:
        channel = bot.get_channel(config["log_channel"])
        if channel:
            try:
                await channel.send(embed=log_embed, silent=True)
            except Exception as e:
                print("Channel Logging failed:", e)

# ===================== ERROR HANDLER =====================
@bot.event
async def on_command_error(ctx, error):
    # Most of your original messages matched MissingPermissions and similar
    if isinstance(error, commands.MissingPermissions):
        perms = [perm.replace('_', '_') for perm in error.missing_permissions]
        embed = make_embed(f"<:warning:1401590117499408434> You’re missing permission: {', '.join(perms)}", discord.Color.orange())
        await ctx.send(embed=embed)

    elif isinstance(error, commands.BotMissingPermissions):
        perms = [perm.replace('_', '_') for perm in error.missing_permissions]
        embed = make_embed(f"<:warning:1401590117499408434> I’m missing permission: {', '.join(perms)}", discord.Color.orange())
        await ctx.send(embed=embed)

    elif isinstance(error, commands.MissingRequiredArgument):
        embed = make_embed(f"<:warning:1401590117499408434> Missing required argument: `{error.param.name}`", discord.Color.orange())
        await ctx.send(embed=embed)

    elif isinstance(error, commands.CommandNotFound):
        embed = make_embed(f"<:warning:1401590117499408434> Unknown command.", discord.Color.orange())
        await ctx.send(embed=embed)

    elif isinstance(error, commands.CommandOnCooldown):
        embed = make_embed(f"<a:clock:1401933869804032061> You’re on cooldown. Try again in `{error.retry_after:.1f}`s.", discord.Color.orange())
        await ctx.send(embed=embed)

    else:
        # re-raise so you can see unhandled exceptions in logs
        raise error

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        perms = [perm.replace('_', '_') for perm in error.missing_permissions]
        embed = make_embed(f"<:warning:1401590117499408434> You’re missing permission: {', '.join(perms)}", discord.Color.orange())
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    elif isinstance(error, app_commands.CommandOnCooldown):
        embed = make_embed(f"<a:clock:1401933869804032061> You’re on cooldown. Try again in `{error.retry_after:.1f}`s.", discord.Color.orange())
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
    else:
        raise error
# ===================== MUTE / UNMUTE and PURGE commands (useful extras) =====================
@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason: str = None):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        try:
            role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                try:
                    await channel.set_permissions(role, send_messages=False, add_reactions=False)
                except Exception:
                    pass
        except Exception:
            return await ctx.send(embed=make_embed("Failed to create Muted role. Missing permissions?", discord.Color.red()))
    try:
        await member.add_roles(role, reason=reason)
        await ctx.send(embed=make_embed(f"{member.mention} has been muted.", discord.Color.orange()))
    except discord.Forbidden:
        await ctx.send(embed=make_embed("Missing permission to add roles.", discord.Color.red()))

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        return await ctx.send(embed=make_embed("No Muted role exists.", discord.Color.orange()))
    try:
        await member.remove_roles(role, reason=f"Unmuted by {ctx.author}")
        await ctx.send(embed=make_embed(f"{member.mention} has been unmuted.", discord.Color.green()))
    except discord.Forbidden:
        await ctx.send(embed=make_embed("Missing permission to remove roles.", discord.Color.red()))

@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, limit: int):
    if limit <= 0:
        return await ctx.send(embed=make_embed("Limit must be a positive integer.", discord.Color.orange()))
    # purge N messages, plus the command message itself
    try:
        deleted = await ctx.channel.purge(limit=limit+1)
        await ctx.send(embed=make_embed(f"Deleted {max(0, len(deleted)-1)} messages.", discord.Color.green()), delete_after=5)
    except discord.Forbidden:
        await ctx.send(embed=make_embed("Missing permission to manage messages.", discord.Color.red()))
    except Exception as e:
        await ctx.send(embed=make_embed(f"Failed to purge messages: {e}", discord.Color.red()))

# ===================== BOT START =====================
if __name__ == "__main__":
    TOKEN = "YOUR_TOKEN_HERE"  # <-- replace
    bot.run(TOKEN)

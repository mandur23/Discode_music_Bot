import os
import sys
from encodings.aliases import aliases

from aiohttp.web_routedef import delete
from dotenv import load_dotenv
import discord
from discord.ext import commands
import yt_dlp
from async_timeout import timeout
from functools import partial
import asyncio
from discord.ui import Button, View
import json
from discord.ui import Button, View, Select
from fuzzywuzzy import process
import random

# 봇 토큰을 넣은 파일 작성후 주소에 대입.
load_dotenv(dotenv_path=r'C:\Users\kimminsu\PycharmProjects\tendo_Aris\.venv\TOKEN.env')
token = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

class FuzzyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remove_command('help')  # 기본 help 명령어 제거

    def get_commands(self):
        return list(self.all_commands.values())

    async def get_context(self, message, *, cls=commands.Context):
        ctx = await super().get_context(message, cls=cls)

        if ctx.command is None:
            command_name = ctx.invoked_with
            commands = self.get_commands()
            matches = process.extractBests(command_name, [cmd.name for cmd in commands], score_cutoff=80, limit=1)
            if matches:
                ctx.command = self.all_commands.get(matches[0][0])
            else:
                # 비슷한 명령어가 없을 경우
                similar_commands = process.extractBests(command_name, [cmd.name for cmd in commands], score_cutoff=60)
                if similar_commands:
                    suggestions = ', '.join([match[0] for match in similar_commands])
                    await message.channel.send(f"어머나, '{command_name}' 명령어를 찾을 수 없어요: 비슷한 명령어: {suggestions}")

        return ctx

    async def on_ready(self):
        print(f'아리스가 준비 완료했어요! {self.user}로 로그인했답니다~')

# 봇 객체 생성
bot = FuzzyBot(command_prefix='!', intents=intents)

# 유튜브 음원 다운로드
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

# 음성 추출 기능
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -timeout 5000000 -user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"'
}

# 설치된 FFmpeg 실행 파일의 경로 (적절히 변경 필요)
ffmpeg_path = r'C:\Users\kimminsu\Downloads\ffmpeg-2024-10-02-git-358fdf3083-full_build\bin\ffmpeg.exe'  

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.cog = ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None
        self.volume = .2
        self.current = None
        self.loop = False
        self.queue_loop = False
        self.current_message = None
        self.button_message = None  # 버튼 메시지를 저장할 변수 추가

        self.idle_timeout = 300  # 5분 (300초)
        self.last_activity = asyncio.Event()  # 마지막 활동을 기록할 이벤트
        self.inactive_time = 0  # 비활동 시간을 기록할 변수 추가

        self.random_play = False  # 랜덤 재생 모드 변수 초기화

        self.bot.loop.create_task(self.player_loop())
        self.bot.loop.create_task(self.register_voice_state_listener())  # 음성 상태 업데이트 리스너 등록
        self.bot.loop.create_task(self.check_idle_timeout())  # 아이들 타임아웃 체크 추가

    async def check_idle_timeout(self):
        while True:
            await asyncio.sleep(1)  # 1초마다 체크
            if not self.last_activity.is_set():
                self.inactive_time += 1  # 비활동 시간 증가
                print(f"비활동 시간: {self.inactive_time}초")  # 비활동 시간 출력
                if self.inactive_time >= self.idle_timeout:
                    await self.stop()  # 활동이 없으면 음악 정지
                    self.restart_program()  # 프로그램 재시작
            else:
                self.inactive_time = 0  # 활동이 있으면 비활동 시간 초기화

    def restart_program(self):
        """현재 프로그램을 재시작합니다."""
        os.execv(sys.executable, ['python'] + sys.argv)

    async def register_voice_state_listener(self):
        @self.bot.listen('on_voice_state_update')
        async def on_voice_state_update(member, before, after):
            self.last_activity.set()  # 사용자가 음성 채널에 있을 때 활동 기록
            if before.channel is not None and after.channel is None:  # 사용자가 음성 채널에서 나갔을 때
                if member == self.guild.me:  # 봇이 나갈 경우
                    return

                # 음성 채널에 남아 있는 사용자 수 확인
                if len(before.channel.members) > 1:  # 다른 사용자가 남아 있는 경우
                    return

                await self.guild.voice_client.pause()  # 음원 일시 정지
                await asyncio.sleep(10)  # 10초 대기
                await self.stop()  # 음성 채널에서 나가기
                # 개인 메시지 전송 및 삭제
                message = await member.send("아리스가 음성 채널에서 나가요. 다음에 또 불러주세요!")  # 개인 메시지 전송
                await asyncio.sleep(3)  # 3초 대기
                await message.delete()  # 메시지 삭제

            # 사용자가 음성 채널에 들어왔을 때
            if after.channel is not None and member != self.guild.me:
                if len(after.channel.members) == 1:  # 사용자가 혼자 있을 경우
                    await self.guild.voice_client.disconnect()  # 봇이 음성 채널에서 나가기
                    await member.send("아리스가 음성 채널에서 나가요. 다음에 또 불러주세요!")  # 개인 메시지 전송

    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()
            self.last_activity.set()  # 활동이 있을 때마다 이벤트 설정

            # 이전 메시지 삭제
            await self.delete_messages()

            # 단일 곡 반복 모드
            if self.loop and self.current:
                source = self.current
            # 전체 반복 모드
            elif self.queue_loop and self.queue.empty() and self.current:
                source = self.current
                await self.queue.put(source)
            else:
                try:
                    async with timeout(300):  # 5분 동안 대기
                        source = await self.queue.get()
                except asyncio.TimeoutError:
                    await self.delete_messages()
                    return await self.stop()  # 타임아웃 시 종료

            if not isinstance(source, dict):
                try:
                    ydl = yt_dlp.YoutubeDL(ytdl_format_options)
                    source = await self.bot.loop.run_in_executor(None, lambda: ydl.extract_info(source, download=False))
                except Exception as e:
                    await self.channel.send(f'어머나, 오류가 발생했어요: {str(e)}')
                    continue

            self.current = source
            self.current_message = await self.channel.send(f'선생님, 지금 재생 중인 노래예요: {source["title"]}\n주소: {source.get("webpage_url", "알 수 없음")}')
            self.button_message, view = await self.create_player_message()  # 버튼 메시지와 뷰 저장

            # 버튼 색상 유지
            await self.update_button_styles(view)

            try:
                self.guild.voice_client.play(
                    discord.FFmpegPCMAudio(source['url'], executable=ffmpeg_path, before_options=ffmpeg_options['before_options'], options=ffmpeg_options['options']),
                    after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set)
                )
                self.guild.voice_client.source = discord.PCMVolumeTransformer(self.guild.voice_client.source)
                self.guild.voice_client.source.volume = self.volume
            except Exception as e:
                await self.channel.send(f"앗, 재생 중에 문제가 생겼어요: {str(e)}")
                print(f"상세 오류 정보: {e.__class__.__name__}: {str(e)}")
                continue

            await self.next.wait()

            # 전체 반복 모드일 때 현재 곡을 대기열 끝에 추가
            if self.queue_loop and not self.loop:
                await self.queue.put(self.current)

            # 다음 곡이 없고 반복 모드가 아닐 때 종료
            if self.queue.empty() and not (self.loop or self.queue_loop):
                await self.delete_messages()
                await self.stop()
                await self.channel.send("선생님, 재생할 곡이 더 이상 없어요. 아리스가 음성 채널에서 나갈게요~", delete_after=10)
                break

    async def delete_messages(self):
        if self.current_message:
            await self.current_message.delete()
            self.current_message = None
        if self.button_message:
            await self.button_message.delete()
            self.button_message = None

    async def stop(self):
        self.queue._queue.clear()
        if self.guild.voice_client:
            await self.guild.voice_client.disconnect()
        self.current = None
        self.loop = False
        self.queue_loop = False
        await self.delete_messages()

    async def create_player_message(self):
        view = View(timeout=None)  # 타임아웃을 None으로 설정하여 버튼이 항상 유효하도록 함

        play_pause = Button(label="재생/일시정지", style=discord.ButtonStyle.primary)
        skip = Button(label="다음 노래로!", style=discord.ButtonStyle.secondary)
        
        loop = Button(label="이 노래 계속 들을래요", style=discord.ButtonStyle.danger)
        queue_loop = Button(label="전체 반복", style=discord.ButtonStyle.danger)
        
        random_play = Button(label="랜덤 재생", style=discord.ButtonStyle.secondary)  # 랜덤 재생 버튼 추가
        
        volume_up = Button(label="더 크게!", style=discord.ButtonStyle.secondary)
        volume_down = Button(label="조금만 작게", style=discord.ButtonStyle.secondary)
        stop_button = Button(label="종료", style=discord.ButtonStyle.danger)

        async def play_pause_callback(interaction):
            if self.guild.voice_client.is_paused():
                self.guild.voice_client.resume()
                await interaction.response.send_message("선생님, 노래를 다시 재생할게요!", ephemeral=True, delete_after=3)
            else:
                self.guild.voice_client.pause()
                await interaction.response.send_message("노래를 잠시 멈췄어요. 계속 들으시려면 다시 눌러주세요, 선생님!", ephemeral=True, delete_after=3)

        async def skip_callback(interaction):
            self.guild.voice_client.stop()
            await interaction.response.send_message("알겠어요, 선생님! 다음 노래로 넘어갈게요!", ephemeral=True, delete_after=3)

        async def loop_callback(interaction):
            if self.random_play:  # 랜덤 재생이 켜져 있을 경우
                await interaction.response.send_message("랜덤 재생이 활성화되어 있어요. 한 곡 반복을 켜기 전에 랜덤 재생을 꺼야 해요.", ephemeral=True)
                return

            self.loop = not self.loop
            loop.style = discord.ButtonStyle.success if self.loop else discord.ButtonStyle.danger  # 버튼 색상 변경
            await interaction.response.edit_message(view=view)  # 메시지 업데이트

        async def queue_loop_callback(interaction):
            self.queue_loop = not self.queue_loop
            queue_loop.style = discord.ButtonStyle.success if self.queue_loop else discord.ButtonStyle.danger  # 버튼 색상 변경
            await interaction.response.edit_message(view=view)  # 메시지 업데이트

        async def random_play_callback(interaction):
            if self.loop:  # 한 곡 반복이 켜져 있을 경우
                await interaction.response.send_message("한 곡 반복이 활성화되어 있어요. 랜덤 재생을 켜기 전에 한 곡 반복을 꺼야 해요.", ephemeral=True)
                return

            self.random_play = not self.random_play  # 랜덤 재생 모드 토글
            status = "켜졌어요" if self.random_play else "꺼졌어요"
            await interaction.response.send_message(f"랜덤 재생 모드가 {status}!", ephemeral=True)

            # 버튼 색상 업데이트
            random_play.style = discord.ButtonStyle.success if self.random_play else discord.ButtonStyle.secondary
            await interaction.message.edit(view=view)  # 버튼 상태 업데이트

            if self.random_play:  # 랜덤 재생이 활성화되면 다음 곡부터 랜덤하게 재생
                await self.play_next()  # 다음 곡 재생 호출

        async def volume_up_callback(interaction):
            if self.volume < 1.0:
                self.volume = min(1.0, self.volume + 0.1)
                self.guild.voice_client.source.volume = self.volume
                await interaction.response.send_message(f"선생님, 볼륨을 {int(self.volume * 100)}%로 올렸어요! 이제 잘 들리나요?", ephemeral=True, delete_after=3)
            else:
                await interaction.response.send_message("앗, 볼륨이 이미 최대예요! 아리스의 귀가 아파요~", ephemeral=True, delete_after=3)

        async def volume_down_callback(interaction):
            if self.volume > 0.0:
                self.volume = max(0.0, self.volume - 0.1)
                self.guild.voice_client.source.volume = self.volume
                await interaction.response.send_message(f"선생님, 볼륨을 {int(self.volume * 100)}%로 낮췄어요! 이정도면 괜찮으신가요?", ephemeral=True, delete_after=3)
            else:
                await interaction.response.send_message("어머, 볼륨이 이미 최소예요! 더 이상 낮추면 아무 소리도 안 들릴 거예요~", ephemeral=True, delete_after=3)

        async def stop_callback(interaction):
            if self.guild.voice_client.is_playing():
                await self.stop()
                await interaction.response.send_message("알겠습니다, 선생님! 아리스가 음악 재생을 종료하고 음성 채널에서 나갔어요~ 다음에 또 불러주세요!", ephemeral=True, delete_after=3)
            else:
                await interaction.response.send_message("현재 재생 중인 음악이 없어요!", ephemeral=True, delete_after=3)

        play_pause.callback = play_pause_callback
        skip.callback = skip_callback
        loop.callback = loop_callback
        queue_loop.callback = queue_loop_callback
        random_play.callback = random_play_callback  # 버튼 클릭 시 호출될 함수 설정
        volume_up.callback = volume_up_callback
        volume_down.callback = volume_down_callback
        stop_button.callback = stop_callback

        view.add_item(play_pause)
        view.add_item(skip)
        view.add_item(loop)
        view.add_item(queue_loop)
        view.add_item(random_play)
        view.add_item(volume_up)
        view.add_item(volume_down)
        view.add_item(stop_button)

        message = await self.channel.send("선생님, 아리스의 특별 음악 컨트롤이에요! 어떤 걸 눌러볼까요?", view=view)
        return message, view

    async def update_button_styles(self, view):
        """버튼 색상을 현재 상태에 맞게 업데이트합니다."""
        for item in view.children:
            if isinstance(item, Button):
                if item.label == "이 노래 계속 들을래요":
                    item.style = discord.ButtonStyle.success if self.loop else discord.ButtonStyle.danger
                elif item.label == "전체 반복":
                    item.style = discord.ButtonStyle.success if self.queue_loop else discord.ButtonStyle.danger
                elif item.label == "랜덤 재생":  # 랜덤 재생 버튼 색상 업데이트 추가
                    item.style = discord.ButtonStyle.success if self.random_play else discord.ButtonStyle.secondary
        await self.button_message.edit(view=view)  # 버튼 상태 업데이트

    def destroy(self, guild):
        return self.bot.loop.create_task(self.cog.cleanup(guild))

    async def play_next(self):
        while True:  # 무한 루프 시작
            if self.queue.empty():
                return
            
            if self.loop:  # 전체 반복 모드일 때
                source = self.current  # 현재 곡을 반복
            elif self.random_play:  # 랜덤 재생 모드일 때
                if self.queue._queue:  # 큐가 비어있지 않은 경우
                    source = random.choice(list(self.queue._queue))  # 랜덤으로 곡 선택
                else:
                    return  # 큐가 비어있으면 종료
            else:
                source = await self.queue.get()  # 일반적으로 다음 곡 선택

            if self.guild.voice_client is None:  # 음성 클라이언트가 None인지 확인
                if self.channel.members:  # 사용자가 음성 채널에 있는지 확인
                    await self.channel.connect()  # 음성 채널에 연결
                else:
                    return  # 음성 채널에 연결할 수 없으면 종료

            # 현재 곡 반복 모드가 활성화된 경우, 현재 곡을 대기열에 추가
            if self.loop and not self.random_play:
                await self.queue.put(source)

            await self.guild.voice_client.play(
                discord.FFmpegPCMAudio(source['url'], executable=ffmpeg_path, before_options=ffmpeg_options['before_options'], options=ffmpeg_options['options']),
                after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set)
            )

            # 랜덤 재생이 활성화된 경우, 다음 곡을 계속해서 재생
            if self.random_play:
                await asyncio.sleep(1)  # 잠시 대기 후 다음 곡 재생

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.playlists = self.load_playlists()

    def load_playlists(self):
        try:
            with open('playlists.json', 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    return {}
                return json.loads(content)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            print("플레이리스트 파일이 손상되었습니다. 새로운 플레이리스트를 시작합니다.",delete_after=10)
            return {}

    def save_playlists(self):
        try:
            with open('playlists.json', 'w', encoding='utf-8') as f:
                json.dump(self.playlists, f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"플레이리스트를 저장하는 중 오류가 발생했습니다: {e}", delete_after=10)

    async def cleanup(self, guild):
        try:
            await guild.voice_client.disconnect()
        except AttributeError:
            pass

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    def get_player(self, ctx):
        if ctx.guild.id in self.players:
            return self.players[ctx.guild.id]
        else:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player
            return player

    async def play(self, ctx, url):
        player = self.get_player(ctx)
        if not player:
            return await ctx.send("선생님, 음성 채널에 먼저 입장해주세요! 아리스가 따라갈게요~",delete_after=10)

        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                return await ctx.send("선생님, 음성 채널에 먼저 입장해주세요! 아리스가 어디로 가야 할지 모르겠어요~",delete_after=10)

        await player.queue.put(url)
        if not player.is_playing:
            await player.play_next()

    async def delete_command_message(self, ctx):
        await asyncio.sleep(3)
        await ctx.message.delete()

    @commands.command(aliases=['종료'])
    async def stop(self, ctx):
        """음악 재생을 종료하고 봇을 음성 채널에서 내보냅니다."""
        player = self.get_player(ctx)
        await player.stop()
        await ctx.send("선생님, 아리스가 음악 재생을 종료하고 음성 채널에서 나갔어요~ 다음에 또 불러주세요!", delete_after=10)
        await self.delete_command_message(ctx)

    @commands.command(aliases=['나가!'])
    async def leave(self, ctx):
        """봇을 음성 채널에서 내보냅니다."""
        await self.stop(ctx)  # stop 명령어를 재사용
        await self.delete_command_message(ctx)

    @commands.command(aliases=['큐', '대기열'])
    async def queue(self, ctx):
        """현재 재생 목록을 표시합니다."""
        player = self.get_player(ctx)
        if player.queue.empty():
            await ctx.send("앗, 선생님! 재생 목록이 비어있어요! 노래를 추가해주시면 아리스가 열심히 불러드릴게요~", delete_after=10)
            await self.delete_command_message(ctx)
            return

        upcoming = list(player.queue._queue)
        fmt = '\n'.join(f'**`{_['title']}`**' for _ in upcoming)
        embed = discord.Embed(title=f'아리스의 재생 목록 - 총 {len(upcoming)}곡이에요!', description=fmt)
        await ctx.send(embed=embed, delete_after=10)
        await self.delete_command_message(ctx)

    @commands.command(aliases=['볼륨'])
    async def volume(self, ctx, volume: int):
        """볼륨을 설정합니다. (0-100)"""
        if ctx.voice_client is None:
            await ctx.send("어라? 아리스가 아직 음성 채널에 없어요. 먼저 들어가 볼게요!", delete_after=10)
            await self.delete_command_message(ctx)
            return

        player = self.get_player(ctx)
        if 0 <= volume <= 100:
            player.volume = volume / 100
            ctx.voice_client.source.volume = player.volume
            await ctx.send(f"볼륨을 {volume}%로 맞췄어요! 이제 잘 들리나요?", delete_after=10)
        else:
            await ctx.send("앗, 볼륨은 0에서 100 사이로 해주세요~ 아리스의 귀가 아파요!", delete_after=10)
        await self.delete_command_message(ctx)

    @commands.command(aliases=['플레이리스트목록', '플래이리스트', 'vmffpdlfltmxm'])
    async def 플레이리스트(self, ctx):
        """선생님의 플레이리스트 목록을 보여드려요."""
        user_id = str(ctx.author.id)
        if user_id not in self.playlists or not self.playlists[user_id]:
            await ctx.send("선생님, 아직 플레이리스트가 없어요. 새로 만들어볼까요?", delete_after=10)
            await self.delete_command_message(ctx)
            return

        view = View()
        select = Select(placeholder="플레이리스트를 선택하세요", options=[discord.SelectOption(label=name, value=name) for name in self.playlists[user_id].keys()])

        async def select_callback(interaction):
            playlist_name = select.values[0]
            playlist = self.playlists[user_id][playlist_name]
            playlist_str = "\n".join(f"{i+1}. {url}" for i, url in enumerate(playlist))

            # 플레이리스트의 곡 목록을 보여주고 추가할지 물어봄
            confirm_view = View()

            async def add_to_queue_callback(add_interaction):
                player = self.get_player(ctx)

                if not ctx.voice_client:
                    if ctx.author.voice:
                        await ctx.author.voice.channel.connect()
                    else:
                        await add_interaction.response.send_message("선생님, 음성 채널에 먼저 입장해주세요! 아리스가 어디로 가야 할지 모르겠어요~", ephemeral=True, delete_after=10)
                        return

                for url in playlist:
                    await player.queue.put(url)

                response_message = await add_interaction.response.send_message(f"선생님의 '{playlist_name}' 플레이리스트의 모든 곡을 대기열에 추가했어요!", ephemeral=True, delete_after=5)
                await asyncio.sleep(3)
                await response_message.delete()

            async def cancel_callback(cancel_interaction):
                await cancel_interaction.response.send_message("곡 추가가 취소되었어요.", ephemeral=True, delete_after=10)

            add_button = Button(label="곡 추가하기", style=discord.ButtonStyle.success)
            cancel_button = Button(label="취소하기", style=discord.ButtonStyle.danger)

            add_button.callback = add_to_queue_callback
            cancel_button.callback = cancel_callback

            confirm_view.add_item(add_button)
            confirm_view.add_item(cancel_button)

            await interaction.response.send_message(f"선생님의 '{playlist_name}' 플레이리스트예요:\n{playlist_str}\n곡을 대기열에 추가할까요?", view=confirm_view, ephemeral=True, delete_after=30)

        select.callback = select_callback
        view.add_item(select)

        await ctx.send("선생님의 플레이리스트 목록이에요:", view=view, delete_after=60)
        await self.delete_command_message(ctx)

    @commands.command(name='플레이리스트추가', aliases=['프래이리스트추가', 'vmffpdlfltmxmcnrk'])
    async def 플레이리스트추가(self, ctx, name: str, *urls):
        """선생님의 플레이리스트에 새 플레이리스트를 추가하거나 기존 플레이리스트에 곡을 추가해요."""
        if not urls:
            await ctx.send("선생님, URL을 하나 이상 입력해주세요!", delete_after=10)
            await self.delete_command_message(ctx)
            return

        user_id = str(ctx.author.id)
        if user_id not in self.playlists:
            self.playlists[user_id] = {}

        if name not in self.playlists[user_id]:
            self.playlists[user_id][name] = []

        self.playlists[user_id][name].extend(urls)
        self.save_playlists()
        await ctx.send(f"선생님의 '{name}' 플레이리스트에 {len(urls)}개의 곡을 추가했어요!", delete_after=10)
        await self.delete_command_message(ctx)

    @commands.command(name='플레이리스트재생', aliases=['플래이리스트재생', 'vmffpdlfltmxmwotod'])
    async def 플레이리스트재생(self, ctx, name: str):
        """선생님이 선택한 플레이리스트를 재생해요."""
        user_id = str(ctx.author.id)
        if user_id not in self.playlists or name not in self.playlists[user_id]:
            await ctx.send(f"선생님, '{name}' 플레이리스트를 찾을 수 없어요.", delete_after=10)
            await self.delete_command_message(ctx)
            return

        player = self.get_player(ctx)
        if not player:
            return await ctx.send("선생님, 음성 채널에 먼저 입장해주세요!", delete_after=10)

        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                return await ctx.send("선생님, 음성 채널에 먼저 입장해주세요!", delete_after=10)

        for url in self.playlists[user_id][name]:
            await player.queue.put(url)

        await ctx.send(f"선생님의 '{name}' 플레이리스트의 모든 곡을 대기열에 추가했어요!", delete_after=10)
        await self.delete_command_message(ctx)
        if not player.is_playing:
            await player.play_next()

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def 삭제(self, ctx, amount: int = 2):
        """지정된 수의 메시지를 삭제합니다."""
        if amount < 1:
            return await ctx.send("어라? 1개 이상의 메시지를 지정해 주셔야 해요. 아리스가 삭제할 수 있게요!", delete_after=10)

        deleted = await ctx.channel.purge(limit=amount + 1)  # 명령어 메시지도 포함해서 삭제
        await ctx.send(f"선생님, {len(deleted)-1}개의 메시지를 깨끗하게 지웠어요! 아리스가 열심히 청소했답니다~", delete_after=5)
        await self.delete_command_message(ctx)

    @삭제.error
    async def 삭제_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("앗, 죄송해요 선생님. 이 명령어는 특별한 권한이 필요해요. 아리스가 도와드리고 싶어도 못 해드려요...", delete_after=10)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("어머, 선생님? 숫자를 올바르게 입력해 주셔야 해요. 아리스가 이해할 수 있게요!", delete_after=10)
        await self.delete_command_message(ctx)

    @commands.command(name='도움말', aliases=['도움', 'help'])
    async def help_command(self, ctx):
        """모든 사용 가능한 명령어와 설명을 보여줍니다."""
        embed = discord.Embed(title="아리스의 명령어 목록", description="사용 가능한 모든 명령어와 설명이에요!", color=0x3498db)

        for command in self.bot.commands:
            if not command.hidden:
                embed.add_field(name=f"!{command.name}", value=command.help or "설명이 없어요.", inline=False)

        # 30초 후 자동으로 삭제되도록 설정
        message = await ctx.send(embed=embed)
        await asyncio.sleep(30)
        await message.delete(delay=2)

    @commands.command(aliases=['큐', '대기열'])
    async def queue(self, ctx):
        """현재 재생 목록을 표시합니다."""
        player = self.get_player(ctx)
        try:
            # 대기열이 비어있는지 확인
            if player.queue.empty():
                await ctx.send("앗, 선생님! 재생 목록이 비어있어요! 노래를 추가해주시면 아리스가 열심히 불러드릴게요~", delete_after=10)
                await self.delete_command_message(ctx)
                return

            # 대기열에서 요소 가져오기
            upcoming = list(player.queue._queue)  # 큐의 모든 요소 리스트로 가져오기

            # 곡 목록 형식화
            fmt_list = []
            for track in upcoming:
                if isinstance(track, dict) and 'title' in track:
                    # track이 딕셔너리일 경우 타이틀 정보 사용
                    fmt_list.append(f'**`{track["title"]}`**')
                elif isinstance(track, str):
                    # track이 문자열일 경우 (아마 URL일 가능성 높음)
                    fmt_list.append(f'**`{track}`**')  # URL을 출력하거나 추가적인 정보 필요시 수정 가능
                else:
                    fmt_list.append("**`알 수 없는 형식의 곡 정보`**")

            fmt = '\n'.join(fmt_list)

            # Embed 길이 제한 검사 및 수정
            if len(fmt) > 2048:
                fmt = fmt[:2000] + "\n... (너무 길어서 일부 내용만 보여드려요)"

            embed = discord.Embed(title=f'아리스의 재생 목록 - 총 {len(upcoming)}곡이에요!', description=fmt)
            await ctx.send(embed=embed, delete_after=10)

        except Exception as e:
            await ctx.send(f"대기열을 표시하는 중 오류가 발생했어요: {e}", delete_after=10)

        try:
            await self.delete_command_message(ctx)
        except Exception as e:
            print(f"delete_command_message 오류: {e}")

    @commands.command(name='재시작', aliases=['restart', 'try'])
    @commands.has_permissions(administrator=True)  # 관리자 권한 필요
    async def restart(self, ctx):
        """프로그램을 재시작합니다."""
        await ctx.send("아리스가 재시작할게요! 잠시만 기다려주세요...", delete_after=5)  # 수정된 부분
        self.restart_program()  # 프로그램 재시작 호출

    def restart_program(self):
        """현재 프로그램을 재시작합니다."""
        os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(name='종료', aliases=['exit'])
    @commands.has_permissions(administrator=True)  # 관리자 권한 필요
    async def stop(self, ctx):
        """봇을 종료합니다."""
        await ctx.send("아리스가 종료될게요! 안녕히 가세요!", delete_after=10)  # 수정된 부분
        await self.bot.close()  # 봇 종료

    @commands.command(name='플레이리스트삭제', aliases=['플래이리스트삭제', 'playrestdelete'])
    async def 플레이리스트삭제(self, ctx):
        """선생님의 플레이리스트 목록을 보여주고 삭제할 수 있어요."""
        user_id = str(ctx.author.id)
        if user_id not in self.playlists or not self.playlists[user_id]:
            await ctx.send("선생님, 아직 플레이리스트가 없어요. 새로 만들어볼까요?", delete_after=10)
            return

        view = View()
        select = Select(placeholder="삭제할 플레이리스트를 선택하세요", options=[discord.SelectOption(label=name, value=name) for name in self.playlists[user_id].keys()])

        async def select_callback(interaction):
            playlist_name = select.values[0]
            confirm_view = View()

            async def delete_callback(delete_interaction):
                del self.playlists[user_id][playlist_name]
                self.save_playlists()
                await delete_interaction.response.send_message(f"선생님의 '{playlist_name}' 플레이리스트가 삭제되었어요!", ephemeral=True, delete_after=5)

            async def cancel_callback(cancel_interaction):
                await cancel_interaction.response.send_message("플레이리스트 삭제가 취소되었어요.", ephemeral=True, delete_after=10)

            delete_button = Button(label="삭제하기", style=discord.ButtonStyle.danger)
            cancel_button = Button(label="취소하기", style=discord.ButtonStyle.secondary)

            delete_button.callback = delete_callback
            cancel_button.callback = cancel_callback

            confirm_view.add_item(delete_button)
            confirm_view.add_item(cancel_button)

            await interaction.response.send_message(f"선생님의 '{playlist_name}' 플레이리스트를 삭제할까요?", view=confirm_view, ephemeral=True, delete_after=30)

        select.callback = select_callback
        view.add_item(select)

        await ctx.send("선생님의 플레이리스트 목록이에요:", view=view, delete_after=60)

    @commands.command(name='플레이리스트노래삭제', aliases=['프래이리스트노래삭제'])
    async def 플레이리스트노래삭제(self, ctx):
        """선생님의 플레이리스트에서 특정 노래를 삭제해요."""
        user_id = str(ctx.author.id)
        if user_id not in self.playlists or not self.playlists[user_id]:
            await ctx.send("선생님, 아직 플레이리스트가 없어요. 새로 만들어볼까요?", delete_after=10)
            return

        # 플레이리스트 선택을 위한 선택지 생성
        playlist_options = [discord.SelectOption(label=name, value=name) for name in self.playlists[user_id].keys()]
        playlist_select = Select(placeholder="삭제할 플레이리스트를 선택하세요", options=playlist_options)

        async def playlist_select_callback(interaction):
            selected_playlist_name = playlist_select.values[0]
            selected_playlist = self.playlists[user_id][selected_playlist_name]

            if not selected_playlist:
                await interaction.response.send_message(f"선생님, '{selected_playlist_name}' 플레이리스트에 노래가 없어요.", ephemeral=True, delete_after=5)
                return

            # 노래 선택을 위한 선택지 생성
            song_options = [discord.SelectOption(label=f"{i + 1}. {url}", value=str(i)) for i, url in enumerate(selected_playlist)]
            song_select = Select(placeholder="삭제할 노래를 선택하세요", options=song_options)

            async def song_select_callback(interaction):
                index = int(song_select.values[0])  # 선택된 값은 인덱스
                removed_song = selected_playlist[index]  # 삭제할 노래 저장

                # 삭제 확인을 위한 버튼 추가
                confirm_view = View()
                confirm_button = Button(label="삭제하기", style=discord.ButtonStyle.danger)
                cancel_button = Button(label="취소하기", style=discord.ButtonStyle.secondary)

                async def confirm_callback(confirm_interaction):
                    selected_playlist.pop(index)  # 선택된 노래 삭제
                    self.save_playlists()
                    await confirm_interaction.response.send_message(f"선생님의 '{selected_playlist_name}' 플레이리스트에서 '{removed_song}' 노래가 삭제되었어요!", ephemeral=True, delete_after=5)

                async def cancel_callback(cancel_interaction):
                    await cancel_interaction.response.send_message("노래 삭제가 취소되었어요.", ephemeral=True, delete_after=5)

                confirm_button.callback = confirm_callback
                cancel_button.callback = cancel_callback

                confirm_view.add_item(confirm_button)
                confirm_view.add_item(cancel_button)

                await interaction.response.send_message(f"정말로 '{removed_song}' 노래를 삭제할까요?", view=confirm_view, ephemeral=True, delete_after=60)

            song_select.callback = song_select_callback
            song_view = View()
            song_view.add_item(song_select)

            await interaction.response.send_message(f"선생님의 '{selected_playlist_name}' 플레이리스트에서 삭제할 노래를 선택하세요:", view=song_view, ephemeral=True, delete_after=60)

        playlist_select.callback = playlist_select_callback
        playlist_view = View()
        playlist_view.add_item(playlist_select)

        await ctx.send("선생님의 플레이리스트 목록이에요:", view=playlist_view, delete_after=60)

async def main():
    async with bot:
        await bot.add_cog(Music(bot))
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())

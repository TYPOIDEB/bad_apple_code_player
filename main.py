import base64
import hashlib
import hmac
import os
import struct
import sys
import time

import cv2
import pygame


VIDEO_NAME = "bad_apple.mp4"
AUDIO_EXTS = (".mp3", ".ogg", ".wav", ".m4a", ".flac")

SEGMENT_SECONDS = 5
TOTP_PERIOD = 30
SETUP_TIME = 60
WINDOW_W, WINDOW_H = 900, 640
FREE_START = 5
CONTROL_H = 44


STRINGS = {
    "ru": {
        "lang_title": "ВЫБЕРИ ЯЗЫК / CHOOSE LANGUAGE",
        "lang_ru": "РУССКИЙ",
        "lang_en": "ENGLISH",
        "lang_hint": "← / → — выбрать, ENTER — подтвердить",
        "setup_title": "ОТСКАНИРУЙ QR В GOOGLE AUTHENTICATOR",
        "setup_manual": "Если QR не берётся — введи ключ вручную:",
        "setup_left": "Осталось {n} сек (SPACE — начать сейчас)",
        "setup_period": "Период TOTP: {n} сек",
        "setup_segment": "Один код открывает {n} секунд видео",
        "setup_free": "Первые {n} сек бесплатно — потом стоп.",
        "setup_total": "Всего нужно кодов: ~{n}",
        "setup_qr_fail": "QR недоступен. Открой Google Authenticator",
        "setup_qr_fail2": "«+» → «Ввести ключ вручную». Имя: VideoUnlock. Тип: По времени",
        "play_enter": "ВВЕДИ КОД ИЗ GOOGLE AUTHENTICATOR",
        "play_hint": "Один верный код = +{seg} сек видео   |   Esc — выход",
        "play_status": "Открыто: {cur:.0f}/{total:.0f} сек  |  Кодов: {codes}",
        "play_totp": "TOTP окно сменится через {n}s",
        "finish_title": "ВИДЕО ПРОСМОТРЕНО ДО КОНЦА",
        "finish_codes": "Введено кодов: {n}",
        "finish_exit": "Esc — выход",
        "console_video": "Видео: {w}x{h}  {fps:.2f} fps  {dur:.1f} сек",
        "console_segments": "Сегментов по {n} сек: ~{cnt}",
        "console_secret": "СЕКРЕТ: {s}",
        "console_audio": "Аудио: {p}",
        "console_no_audio": "Аудио не найдено рядом с видео.",
        "console_start": "Старт воспроизведения. ESC — выход.",
        "console_ok": "[OK] Открыто до {n:.0f} сек",
        "console_fail": "[FAIL] Неверный код",
        "console_no_video": "!!! Файл не найден: {p}",
        "console_bad_video": "Не могу открыть видео.",
    },
    "en": {
        "lang_title": "ВЫБЕРИ ЯЗЫК / CHOOSE LANGUAGE",
        "lang_ru": "РУССКИЙ",
        "lang_en": "ENGLISH",
        "lang_hint": "← / → — select, ENTER — confirm",
        "setup_title": "SCAN QR IN GOOGLE AUTHENTICATOR",
        "setup_manual": "If QR doesn't scan — enter the key manually:",
        "setup_left": "{n} sec left (SPACE — start now)",
        "setup_period": "TOTP period: {n} sec",
        "setup_segment": "One code unlocks {n} seconds of video",
        "setup_free": "First {n} sec are free — then it stops.",
        "setup_total": "Total codes needed: ~{n}",
        "setup_qr_fail": "QR unavailable. Open Google Authenticator",
        "setup_qr_fail2": "+ -> Enter setup key. Name: VideoUnlock. Type: Time-based",
        "play_enter": "ENTER CODE FROM GOOGLE AUTHENTICATOR",
        "play_hint": "One valid code = +{seg} sec of video   |   Esc — quit",
        "play_status": "Unlocked: {cur:.0f}/{total:.0f} sec  |  Codes: {codes}",
        "play_totp": "TOTP window resets in {n}s",
        "finish_title": "VIDEO WATCHED TO THE END",
        "finish_codes": "Codes entered: {n}",
        "finish_exit": "Esc — quit",
        "console_video": "Video: {w}x{h}  {fps:.2f} fps  {dur:.1f} sec",
        "console_segments": "Segments of {n} sec: ~{cnt}",
        "console_secret": "SECRET: {s}",
        "console_audio": "Audio: {p}",
        "console_no_audio": "No audio found next to video.",
        "console_start": "Playback started. ESC — quit.",
        "console_ok": "[OK] Unlocked up to {n:.0f} sec",
        "console_fail": "[FAIL] Wrong code",
        "console_no_video": "!!! File not found: {p}",
        "console_bad_video": "Cannot open video.",
    },
}


class L:
    def __init__(self):
        self.lang = "en"

    def set(self, lang):
        self.lang = lang if lang in STRINGS else "en"

    def __call__(self, key, **kw):
        s = STRINGS[self.lang].get(key, key)
        return s.format(**kw) if kw else s


L10N = L()


def get_base_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
VIDEO_PATH = os.path.join(BASE_DIR, VIDEO_NAME)


def random_secret():
    return base64.b32encode(os.urandom(10)).decode().rstrip("=")


def totp(secret, ts=None, period=TOTP_PERIOD):
    if ts is None:
        ts = time.time()
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    counter = int(ts // period)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    code = struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF
    return code % 1_000_000


def verify_code(secret, code_str):
    try:
        entered = int(code_str)
    except ValueError:
        return False
    now = time.time()
    for off in (-1, 0, 1):
        if entered == totp(secret, now + off * TOTP_PERIOD):
            return True
    return False


def make_qr_surface(uri, size=280):
    encoder = None
    try:
        encoder = cv2.QRCodeEncoder.create()
    except Exception:
        pass
    if encoder is None:
        try:
            encoder = cv2.QRCodeEncoder_create()
        except Exception as e:
            print(f"[QR] cv2.QRCodeEncoder недоступен: {e}")
            return None
    try:
        qr = encoder.encode(uri)
    except Exception as e:
        print(f"[QR] encode failed: {e}")
        return None

    h, w = qr.shape[:2]
    cell = max(2, size // w)
    total = cell * w
    surf = pygame.Surface((total, total))
    surf.fill((255, 255, 255))
    black = (0, 0, 0)
    for y in range(h):
        for x in range(w):
            if qr[y, x] < 128:
                pygame.draw.rect(surf, black, (x * cell, y * cell, cell, cell))
    print(f"[QR] cv2 built: {w}x{h} -> {total}px")
    return surf


class Controls:
    def __init__(self):
        self.play_rect = pygame.Rect(10, WINDOW_H - CONTROL_H + 8, 28, 28)
        slider_w = 160
        slider_x = WINDOW_W - slider_w - 20
        slider_y = WINDOW_H - CONTROL_H // 2 - 6
        self.slider_rect = pygame.Rect(slider_x, slider_y, slider_w, 12)
        self.volume = 1.0
        self.dragging = False
        self.paused = False

    def handle_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.play_rect.collidepoint(ev.pos):
                self.paused = not self.paused
                return True
            if self.slider_rect.inflate(0, 14).collidepoint(ev.pos):
                self.dragging = True
                self._set_volume_from_mouse(ev.pos[0])
                return True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.dragging:
                self.dragging = False
                return True
        elif ev.type == pygame.MOUSEMOTION:
            if self.dragging:
                self._set_volume_from_mouse(ev.pos[0])
                return True
        return False

    def _set_volume_from_mouse(self, mx):
        x1, x2 = self.slider_rect.x, self.slider_rect.right
        frac = max(0.0, min(1.0, (mx - x1) / (x2 - x1)))
        self.volume = frac
        try:
            pygame.mixer.music.set_volume(frac)
        except Exception:
            pass

    def adjust_volume(self, delta):
        self.volume = max(0.0, min(1.0, self.volume + delta))
        try:
            pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass

    def draw(self, screen):
        bar = pygame.Surface((WINDOW_W, CONTROL_H))
        bar.set_alpha(180)
        bar.fill((0, 0, 0))
        screen.blit(bar, (0, WINDOW_H - CONTROL_H))

        pygame.draw.rect(screen, (40, 40, 40), self.play_rect, border_radius=4)
        pygame.draw.rect(screen, (200, 200, 200), self.play_rect, 2, border_radius=4)
        cx = self.play_rect.centerx
        cy = self.play_rect.centery
        if self.paused:
            pts = [(cx - 6, cy - 8), (cx - 6, cy + 8), (cx + 9, cy)]
            pygame.draw.polygon(screen, (100, 255, 100), pts)
        else:
            pygame.draw.rect(screen, (255, 220, 100), (cx - 6, cy - 8, 4, 16))
            pygame.draw.rect(screen, (255, 220, 100), (cx + 2, cy - 8, 4, 16))

        sr = self.slider_rect
        pygame.draw.rect(screen, (40, 40, 40), sr, border_radius=6)
        fill_w = int(sr.width * self.volume)
        if fill_w > 0:
            fill_rect = pygame.Rect(sr.x, sr.y, fill_w, sr.height)
            pygame.draw.rect(screen, (100, 200, 255), fill_rect, border_radius=6)
        knob_x = sr.x + fill_w
        pygame.draw.circle(screen, (255, 255, 255), (knob_x, sr.centery), 8)
        pygame.draw.circle(screen, (100, 200, 255), (knob_x, sr.centery), 8, 2)

        vol_icon_x = sr.x - 24
        vol_icon_y = sr.centery
        pygame.draw.polygon(screen, (200, 200, 200), [
            (vol_icon_x - 4, vol_icon_y - 4),
            (vol_icon_x + 2, vol_icon_y - 4),
            (vol_icon_x + 8, vol_icon_y - 10),
            (vol_icon_x + 8, vol_icon_y + 10),
            (vol_icon_x + 2, vol_icon_y + 4),
            (vol_icon_x - 4, vol_icon_y + 4),
        ])
        if self.volume > 0.05:
            pygame.draw.arc(screen, (200, 200, 200),
                            (vol_icon_x + 4, vol_icon_y - 6, 10, 12), -1.0, 1.0, 2)
        if self.volume > 0.6:
            pygame.draw.arc(screen, (200, 200, 200),
                            (vol_icon_x + 6, vol_icon_y - 9, 14, 18), -1.0, 1.0, 2)

        pct = int(self.volume * 100)
        font = pygame.font.SysFont("consolas,couriernew,monospace", 12)
        pct_surf = font.render(f"{pct}%", True, (180, 180, 180))
        screen.blit(pct_surf, (sr.right + 10, sr.y - 3))


def language_select_screen(screen, clock, fonts):
    font_big, font_small = fonts
    options = ["ru", "en"]
    labels = {"ru": "РУССКИЙ", "en": "ENGLISH"}
    selected = 0

    while True:
        clock.tick(60)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    selected = 1 - selected
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    return options[selected]

        screen.fill((15, 15, 25))
        t1 = font_big.render("ВЫБЕРИ ЯЗЫК / CHOOSE LANGUAGE", True, (100, 255, 100))
        screen.blit(t1, (WINDOW_W // 2 - t1.get_width() // 2, 80))

        btn_w, btn_h = 300, 120
        gap = 40
        total_w = btn_w * 2 + gap
        start_x = (WINDOW_W - total_w) // 2
        y = WINDOW_H // 2 - btn_h // 2

        for i, lang in enumerate(options):
            x = start_x + i * (btn_w + gap)
            is_sel = (i == selected)
            frame_color = (255, 255, 100) if is_sel else (80, 80, 100)
            pygame.draw.rect(screen, frame_color, (x - 4, y - 4, btn_w + 8, btn_h + 8), 4)
            bg = (40, 60, 40) if is_sel else (25, 25, 40)
            pygame.draw.rect(screen, bg, (x, y, btn_w, btn_h))
            color = (255, 255, 100) if is_sel else (200, 200, 200)
            lbl = font_big.render(labels[lang], True, color)
            screen.blit(lbl, (x + btn_w // 2 - lbl.get_width() // 2,
                              y + btn_h // 2 - lbl.get_height() // 2))

        hint = font_small.render("← / → — выбрать, ENTER — подтвердить    |    "
                                 "← / → — select, ENTER — confirm",
                                 True, (150, 150, 150))
        screen.blit(hint, (WINDOW_W // 2 - hint.get_width() // 2, WINDOW_H - 80))
        pygame.display.flip()


def setup_screen(screen, clock, fonts, secret, qr_surf, total_segments):
    font_big, font_med, font_small, font_huge = fonts
    start = time.time()

    while True:
        clock.tick(60)
        elapsed = time.time() - start
        left = max(0, int(SETUP_TIME - elapsed))

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return False
                if ev.key == pygame.K_SPACE:
                    return True

        if elapsed >= SETUP_TIME:
            return True

        screen.fill((15, 15, 25))
        t = font_big.render(L10N("setup_title"), True, (100, 255, 100))
        screen.blit(t, (WINDOW_W // 2 - t.get_width() // 2, 20))

        if qr_surf:
            r = qr_surf.get_rect(center=(WINDOW_W // 2, 190))
            bg = pygame.Surface((r.width + 20, r.height + 20))
            bg.fill((255, 255, 255))
            screen.blit(bg, (r.x - 10, r.y - 10))
            screen.blit(qr_surf, r)
        else:
            warn = font_big.render(L10N("setup_qr_fail"), True, (255, 150, 150))
            screen.blit(warn, (WINDOW_W // 2 - warn.get_width() // 2, 150))
            warn2 = font_med.render(L10N("setup_qr_fail2"), True, (255, 200, 100))
            screen.blit(warn2, (WINDOW_W // 2 - warn2.get_width() // 2, 200))

        lbl = font_small.render(L10N("setup_manual"), True, (150, 150, 150))
        screen.blit(lbl, (WINDOW_W // 2 - lbl.get_width() // 2, 350))
        sec = font_huge.render(secret, True, (255, 220, 100))
        screen.blit(sec, (WINDOW_W // 2 - sec.get_width() // 2, 375))

        info = [
            L10N("setup_left", n=left),
            L10N("setup_period", n=TOTP_PERIOD),
            L10N("setup_segment", n=SEGMENT_SECONDS),
            L10N("setup_free", n=FREE_START),
            L10N("setup_total", n=total_segments),
        ]
        for i, line in enumerate(info):
            color = (200, 200, 200) if i < 4 else (255, 180, 80)
            s = font_small.render(line, True, color)
            screen.blit(s, (20, 500 + i * 18))

        cd_color = (100, 255, 100) if left >= 10 else (255, 100, 100)
        cd = font_huge.render(str(left), True, cd_color)
        screen.blit(cd, (WINDOW_W - 150, WINDOW_H - 130))
        pygame.display.flip()


def main():
    if not os.path.exists(VIDEO_PATH):
        print(L10N("console_no_video", p=VIDEO_PATH))
        return

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(L10N("console_bad_video"))
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_seconds = total_frames / fps if fps > 0 else 0
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_segments = int(total_seconds // SEGMENT_SECONDS) + 1

    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        print(f"[AUDIO] mixer init OK: {pygame.mixer.get_init()}")
    except pygame.error as e:
        print(f"[AUDIO] mixer init FAILED: {e}")

    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("TOTP Bad Apple Unlock")
    clock = pygame.time.Clock()

    font_big = pygame.font.SysFont("consolas,couriernew,monospace", 26, bold=True)
    font_med = pygame.font.SysFont("consolas,couriernew,monospace", 18, bold=True)
    font_small = pygame.font.SysFont("consolas,couriernew,monospace", 14)
    font_huge = pygame.font.SysFont("consolas,couriernew,monospace", 42, bold=True)

    lang = language_select_screen(screen, clock, (font_big, font_small))
    if lang is None:
        pygame.quit()
        return
    L10N.set(lang)

    print(L10N("console_video", w=vw, h=vh, fps=fps, dur=total_seconds))
    print(L10N("console_segments", n=SEGMENT_SECONDS, cnt=total_segments))

    audio_path = None
    for ext in AUDIO_EXTS:
        cand = os.path.splitext(VIDEO_PATH)[0] + ext
        exists = os.path.exists(cand)
        print(f"[AUDIO] ищу {cand} -> {'найден' if exists else 'нет'}")
        if exists and audio_path is None:
            audio_path = cand

    has_audio = False
    if audio_path:
        try:
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.set_volume(0.7)
            has_audio = True
            print(f"[AUDIO] загружен: {audio_path}")
        except Exception as e:
            print(f"[AUDIO] ошибка загрузки: {type(e).__name__}: {e}")
    else:
        print("[AUDIO] аудиофайл не найден")

    secret = random_secret()
    uri = (f"otpauth://totp/VideoUnlock:user"
           f"?secret={secret}&issuer=VideoUnlock&period={TOTP_PERIOD}")
    qr_surf = make_qr_surface(uri, size=280)
    print(L10N("console_secret", s=secret))

    ok = setup_screen(screen, clock,
                      (font_big, font_med, font_small, font_huge),
                      secret, qr_surf, total_segments)
    if not ok:
        pygame.quit()
        return

    unlocked_seconds = float(FREE_START)
    frame_idx = 0
    state = "playing"
    typed = ""
    last_surf = None
    flash_until = 0.0
    flash_color = (0, 0, 0)
    codes_entered = 0

    controls = Controls()

    if has_audio:
        try:
            pygame.mixer.music.set_volume(controls.volume)
            pygame.mixer.music.play()
            print(f"[AUDIO] play() запущен, busy={pygame.mixer.music.get_busy()}")
        except Exception as e:
            print(f"[AUDIO] play error: {e}")
            has_audio = False

    print(L10N("console_start"))

    running = True
    while running:
        clock.tick(int(fps))

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
                continue

            if state in ("playing", "waiting"):
                if controls.handle_event(ev):
                    if has_audio:
                        if controls.paused:
                            pygame.mixer.music.pause()
                        else:
                            if state == "playing":
                                pygame.mixer.music.unpause()
                    continue

            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                    continue

                if state in ("playing", "waiting"):
                    if ev.key == pygame.K_UP:
                        controls.adjust_volume(0.1)
                        continue
                    if ev.key == pygame.K_DOWN:
                        controls.adjust_volume(-0.1)
                        continue
                    if ev.key == pygame.K_SPACE and state == "playing":
                        controls.paused = not controls.paused
                        if has_audio:
                            if controls.paused:
                                pygame.mixer.music.pause()
                            else:
                                pygame.mixer.music.unpause()
                        continue

                if state == "waiting":
                    if ev.key == pygame.K_BACKSPACE:
                        typed = typed[:-1]
                    elif ev.unicode.isdigit() and len(typed) < 6:
                        typed += ev.unicode
                        if len(typed) == 6:
                            if verify_code(secret, typed):
                                unlocked_seconds += SEGMENT_SECONDS
                                codes_entered += 1
                                typed = ""
                                state = "playing"
                                if has_audio:
                                    pygame.mixer.music.unpause()
                                flash_until = time.time() + 0.25
                                flash_color = (0, 100, 0)
                                print(L10N("console_ok", n=unlocked_seconds))
                            else:
                                typed = ""
                                flash_until = time.time() + 0.5
                                flash_color = (140, 0, 0)
                                print(L10N("console_fail"))

        if state == "playing":
            if not controls.paused:
                current_time = frame_idx / fps
                if current_time >= unlocked_seconds:
                    state = "waiting"
                    if has_audio:
                        pygame.mixer.music.pause()
                    continue

                ret, frame = cap.read()
                if not ret:
                    state = "finished"
                    continue

                frame_idx += 1
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = frame_rgb.shape[:2]
                scale = min(WINDOW_W / w, (WINDOW_H - CONTROL_H) / h)
                nw, nh = int(w * scale), int(h * scale)
                frame_rgb = cv2.resize(frame_rgb, (nw, nh))

                surf = pygame.image.frombuffer(frame_rgb.tobytes(),
                                                (nw, nh), "RGB")
                last_surf = surf

        if state == "playing":
            screen.fill((0, 0, 0))
            if last_surf:
                screen.blit(last_surf,
                            ((WINDOW_W - last_surf.get_width()) // 2,
                             (WINDOW_H - CONTROL_H - last_surf.get_height()) // 2))
            if controls.paused:
                t = font_big.render("||", True, (255, 255, 255))
                screen.blit(t, (WINDOW_W // 2 - t.get_width() // 2,
                                WINDOW_H // 2 - t.get_height() // 2))

        elif state == "waiting":
            screen.fill((0, 0, 0))
            if last_surf:
                dim = last_surf.copy()
                dim.fill((90, 90, 90), special_flags=pygame.BLEND_RGB_MULT)
                screen.blit(dim,
                            ((WINDOW_W - last_surf.get_width()) // 2,
                             (WINDOW_H - CONTROL_H - last_surf.get_height()) // 2))

            overlay = pygame.Surface((WINDOW_W, 240))
            overlay.set_alpha(215)
            overlay.fill((0, 0, 0))
            screen.blit(overlay, (0, WINDOW_H // 2 - 120))

            t = font_big.render(L10N("play_enter"), True, (255, 200, 100))
            screen.blit(t, (WINDOW_W // 2 - t.get_width() // 2,
                            WINDOW_H // 2 - 95))

            typed_show = typed + "_" * (6 - len(typed))
            code_surf = font_huge.render(typed_show, True, (100, 255, 100))
            screen.blit(code_surf,
                        (WINDOW_W // 2 - code_surf.get_width() // 2,
                         WINDOW_H // 2 - 30))

            hint = font_small.render(L10N("play_hint", seg=SEGMENT_SECONDS),
                                     True, (200, 200, 200))
            screen.blit(hint, (WINDOW_W // 2 - hint.get_width() // 2,
                                WINDOW_H // 2 + 70))

        elif state == "finished":
            screen.fill((0, 25, 0))
            t = font_big.render(L10N("finish_title"), True, (100, 255, 100))
            screen.blit(t, (WINDOW_W // 2 - t.get_width() // 2,
                            WINDOW_H // 2 - 60))
            t2 = font_med.render(L10N("finish_codes", n=codes_entered),
                                 True, (200, 200, 200))
            screen.blit(t2, (WINDOW_W // 2 - t2.get_width() // 2,
                             WINDOW_H // 2 + 10))
            t3 = font_small.render(L10N("finish_exit"), True, (150, 150, 150))
            screen.blit(t3, (WINDOW_W // 2 - t3.get_width() // 2,
                             WINDOW_H // 2 + 50))

        if state in ("playing", "waiting"):
            hud = font_small.render(
                L10N("play_status", cur=unlocked_seconds, total=total_seconds,
                     codes=codes_entered),
                True, (220, 220, 220))
            screen.blit(hud, (10, 10))

            now = time.time()
            left_t = TOTP_PERIOD - int(now) % TOTP_PERIOD
            tc = (255, 100, 100) if left_t < 5 else (150, 150, 150)
            tt = font_small.render(L10N("play_totp", n=left_t), True, tc)
            screen.blit(tt, (10, 30))

            controls.draw(screen)

        if time.time() < flash_until:
            fl = pygame.Surface((WINDOW_W, WINDOW_H))
            fl.set_alpha(120)
            fl.fill(flash_color)
            screen.blit(fl, (0, 0))

        pygame.display.flip()

    pygame.quit()
    cap.release()


if __name__ == "__main__":
    main()
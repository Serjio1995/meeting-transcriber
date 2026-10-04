"""Основное окно: статус, уровни сигнала, транскрипт, мастер, настройки."""

import logging
import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import scrolledtext, ttk

import pyperclip

from . import audio, engine, models, wizard
from .config import CFG, TRANSCRIPT_DIR, save_config
from .constants import STATUS_COLORS, TAG_MIC, TAG_SYS
from .state import STATE, UI_Q
from .tray import notify, set_color

log = logging.getLogger(__name__)


class App:
    def __init__(self, root: tk.Tk, minimized: bool):
        self.root = root
        root.title("Транскрибатор конференций")
        root.geometry("820x640")
        root.minsize(560, 460)
        self._devices = []
        self._mics = []
        self._flash_after = None
        self._last_color = None
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.after(150, self._poll)
        if minimized:
            root.withdraw()

    # ------------------------------ интерфейс ------------------------------
    def _build(self):
        top = ttk.Frame(self.root, padding=(10, 8, 10, 2))
        top.pack(fill="x")
        self.status_lbl = tk.Label(top, text="Запуск…", anchor="w",
                                   font=("Segoe UI", 12, "bold"), fg="#555")
        self.status_lbl.pack(fill="x")

        # прогресс скачивания моделей
        self.dl_frame = ttk.Frame(top)
        self.dl_lbl = ttk.Label(self.dl_frame, text="", foreground="#1565c0")
        self.dl_lbl.pack(side="left")
        self.dl_bar = ttk.Progressbar(self.dl_frame, length=240, maximum=100)
        self.dl_bar.pack(side="left", padx=8)

        self.conf_lbl = tk.Label(top, text="", anchor="w", fg="#777")
        self.conf_lbl.pack(fill="x")
        self.src_lbl = tk.Label(top, text="", anchor="w", fg="#777")
        self.src_lbl.pack(fill="x")
        self.hint_lbl = tk.Label(top, text="", anchor="w", fg="#b26a00",
                                 wraplength=780, justify="left")
        self.hint_lbl.pack(fill="x")

        lvl = ttk.Frame(top)
        lvl.pack(fill="x", pady=(6, 0))
        ttk.Label(lvl, text="Уровень:", foreground="#555").pack(side="left")
        ttk.Label(lvl, text="  👥").pack(side="left")
        self.bar_sys = ttk.Progressbar(lvl, length=170, maximum=100)
        self.bar_sys.pack(side="left")
        ttk.Label(lvl, text="  🎤").pack(side="left", padx=(10, 0))
        self.bar_mic = ttk.Progressbar(lvl, length=170, maximum=100)
        self.bar_mic.pack(side="left")

        self.txt = scrolledtext.ScrolledText(self.root, wrap="word", padx=10,
                                             pady=6, font=("Consolas", 10),
                                             state="disabled")
        self.txt.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        btns = ttk.Frame(self.root, padding=(10, 6))
        btns.pack(fill="x")
        ttk.Button(btns, text="📋 Копировать весь текст",
                   command=self.copy_all).pack(side="left")
        self.toggle_btn = ttk.Button(btns, text="▶ Запись вручную",
                                     command=self.toggle)
        self.toggle_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="📁 Открыть папку",
                   command=self.open_folder).pack(side="left")
        ttk.Button(btns, text="🧙 Настройка",
                   command=self.open_wizard).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text="⚙ Дополнительно",
                   command=self.toggle_settings).pack(side="right")

        self._build_settings()

        bottom = ttk.Frame(self.root, padding=(10, 2, 10, 8))
        bottom.pack(fill="x")
        self.flash_lbl = tk.Label(bottom, text="", anchor="w", fg="#1565c0")
        self.flash_lbl.pack(side="left")
        self.path_lbl = tk.Label(bottom, text="", anchor="e", fg="#999")
        self.path_lbl.pack(side="right")

    def _build_settings(self):
        f = ttk.LabelFrame(self.root,
                           text="Дополнительные настройки (применяются после "
                                "«Сохранить» + перезапуска)",
                           padding=10)
        self.set_frm = f

        def lbl(r, text):
            ttk.Label(f, text=text).grid(row=r, column=0, sticky="w", pady=2)

        lbl(0, "Пресет качества:")
        self._q_keys = list(models.QUALITY.keys())
        self.q_cb = ttk.Combobox(f, width=52, state="readonly",
                                 values=[models.QUALITY[k] for k in self._q_keys])
        self.q_cb.current(self._q_keys.index(CFG.get("quality", "balanced")))
        self.q_cb.grid(row=0, column=1, sticky="w")

        lbl(1, "Движок:")
        self.eng_cb = ttk.Combobox(f, width=12, state="readonly",
                                   values=["auto", "whisper", "vosk"])
        self.eng_cb.set(CFG.get("engine", "auto"))
        self.eng_cb.grid(row=1, column=1, sticky="w")

        lbl(2, "Модель Whisper:")
        self.model_cb = ttk.Combobox(f, width=18, state="readonly", values=[
            "auto", "tiny", "base", "small", "medium",
            "large-v3", "large-v3-turbo"])
        self.model_cb.set(CFG["model"])
        self.model_cb.grid(row=2, column=1, sticky="w")

        lbl(3, "Устройство ИИ:")
        self.compute_cb = ttk.Combobox(f, width=18, state="readonly",
                                       values=["auto", "cpu", "cuda"])
        self.compute_cb.set(CFG["compute"])
        self.compute_cb.grid(row=3, column=1, sticky="w")

        lbl(4, "Язык:")
        self.lang_cb = ttk.Combobox(f, width=10,
                                    values=["ru", "en", "auto", "de", "fr",
                                            "es", "uk"])
        self.lang_cb.set(CFG["language"])
        self.lang_cb.grid(row=4, column=1, sticky="w")

        lbl(5, "Источник звука:")
        self.src_map = {"dual": "Оба: участники + вы",
                        "loopback": "Системный звук (участники)",
                        "mic": "Микрофон (вы)"}
        self.src_cb = ttk.Combobox(f, width=28, state="readonly",
                                   values=list(self.src_map.values()))
        self.src_cb.set(self.src_map.get(CFG["source"], self.src_map["dual"]))
        self.src_cb.grid(row=5, column=1, sticky="w")

        lbl(6, "Сист. аудиоустройство:")
        self.dev_cb = ttk.Combobox(f, width=44, state="readonly")
        self.dev_cb.grid(row=6, column=1, sticky="w")
        ttk.Button(f, text="⟳", width=3,
                   command=self.refresh_devices).grid(row=6, column=2, padx=4)

        lbl(7, "Микрофон:")
        self.mic_dev_cb = ttk.Combobox(f, width=44, state="readonly")
        self.mic_dev_cb.grid(row=7, column=1, sticky="w")

        lbl(8, "Стоп после тишины (сек):")
        self.sil_ent = ttk.Entry(f, width=8)
        self.sil_ent.insert(0, str(CFG["silence_timeout"]))
        self.sil_ent.grid(row=8, column=1, sticky="w")

        lbl(9, "Триггер автостарта:")
        self.trig_map = {"process+sound": "Процесс ВКС + звук",
                         "sound": "Только звук"}
        self.trig_cb = ttk.Combobox(f, width=28, state="readonly",
                                    values=list(self.trig_map.values()))
        self.trig_cb.set(self.trig_map.get(CFG["trigger"],
                                           self.trig_map["process+sound"]))
        self.trig_cb.grid(row=9, column=1, sticky="w")

        lbl(10, "Подсказка модели:")
        self.prompt_ent = ttk.Entry(f, width=52)
        self.prompt_ent.insert(0, CFG.get("prompt", ""))
        self.prompt_ent.grid(row=10, column=1, columnspan=2, sticky="w")

        self.auto_var = tk.BooleanVar(value=CFG["auto_start"])
        self.autocopy_var = tk.BooleanVar(value=CFG["auto_copy"])
        self.browsers_var = tk.BooleanVar(value=CFG["include_browsers"])
        ttk.Checkbutton(f, text="Автостарт при конференции",
                        variable=self.auto_var).grid(row=11, column=0,
                                                     columnspan=2, sticky="w")
        ttk.Checkbutton(f, text="Копировать каждую фразу в буфер",
                        variable=self.autocopy_var).grid(row=12, column=0,
                                                         columnspan=2, sticky="w")
        ttk.Checkbutton(f, text="Считать браузеры платформой ВКС",
                        variable=self.browsers_var).grid(row=13, column=0,
                                                         columnspan=2, sticky="w")
        ttk.Button(f, text="💾 Сохранить",
                   command=self.apply_settings).grid(row=14, column=0,
                                                     columnspan=3, pady=6)
        for c in (1, 2):
            f.columnconfigure(c, weight=1)

    def toggle_settings(self):
        if self.set_frm.winfo_ismapped():
            self.set_frm.pack_forget()
        else:
            self.refresh_devices()
            self.set_frm.pack(fill="x", padx=10, pady=(0, 4))

    def open_wizard(self):
        wizard.Wizard(self.root)

    def refresh_devices(self):
        try:
            import soundcard as sc
            all_devs = sc.all_microphones(include_loopback=True)
        except Exception:
            all_devs = []
        self._devices = [
            (f"{'🔈 сист.' if d.isloopback else '🎙 микроф.'} | {d.name[:50]}", i)
            for i, d in enumerate(all_devs)]
        self._mics = audio.list_mic_devices()

        self.dev_cb["values"] = (["По умолчанию"] +
                                 [n for n, _ in self._devices])
        did = CFG.get("device_id")
        didx = did + 1 if isinstance(did, int) and did < len(self._devices) else 0
        self.dev_cb.current(didx)

        self.mic_dev_cb["values"] = (["По умолчанию"] +
                                     [n for n, _ in self._mics])
        mid = CFG.get("mic_device_id")
        midx = mid + 1 if isinstance(mid, int) and mid < len(self._mics) else 0
        self.mic_dev_cb.current(midx)

    def apply_settings(self):
        CFG["quality"] = self._q_keys[self.q_cb.current()]
        CFG["engine"] = self.eng_cb.get()
        CFG["model"] = self.model_cb.get()
        CFG["compute"] = self.compute_cb.get()
        CFG["language"] = self.lang_cb.get().strip() or "ru"
        CFG["source"] = {v: k for k, v in self.src_map.items()}[self.src_cb.get()]
        sel = self.dev_cb.current()
        CFG["device_id"] = None if sel <= 0 else self._devices[sel - 1][1]
        msel = self.mic_dev_cb.current()
        CFG["mic_device_id"] = None if msel <= 0 else self._mics[msel - 1][1]
        try:
            CFG["silence_timeout"] = max(30, int(self.sil_ent.get()))
        except ValueError:
            pass
        CFG["trigger"] = {v: k for k, v in self.trig_map.items()}[self.trig_cb.get()]
        CFG["prompt"] = self.prompt_ent.get().strip()
        CFG["auto_start"] = self.auto_var.get()
        CFG["auto_copy"] = self.autocopy_var.get()
        CFG["include_browsers"] = self.browsers_var.get()
        save_config()
        models.reset_engine()
        self.flash("💾 Сохранено. Перезапустите приложение (трей → Выход)")

    # ------------------------------ действия ------------------------------
    def toggle(self):
        if STATE.recording:
            engine.request_manual_stop()
            self.flash("⏹ Останавливаю запись…")
        else:
            with STATE.lock:
                STATE.cooldown_until = 0
            engine.start_recording("manual")

    def copy_all(self):
        text = self.txt.get("1.0", "end-1c").strip()
        if not text:
            return self.flash("Пока нечего копировать")
        try:
            pyperclip.copy(text)
            self.flash(f"✅ Скопировано {len(text)} символов в буфер обмена")
        except Exception as exc:
            self.flash(f"⚠ Буфер обмена недоступен: {exc}")

    def open_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(TRANSCRIPT_DIR)                      # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(TRANSCRIPT_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(TRANSCRIPT_DIR)])
        except Exception as exc:
            self.flash(f"⚠ {exc}")

    def hide(self):
        self.root.withdraw()
        notify("Транскрибатор", "Приложение работает в фоне. Иконка в трее.")

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def quit_app(self):
        from .state import STOP
        STOP.set()
        from . import tray
        tray.shutdown()
        self.root.destroy()

    # ------------------------------ служебные ------------------------------
    def flash(self, text: str):
        self.flash_lbl.config(text=text)
        if self._flash_after:
            self.root.after_cancel(self._flash_after)
        self._flash_after = self.root.after(
            5000, lambda: self.flash_lbl.config(text=""))

    def _append(self, text: str):
        self.txt.config(state="normal")
        self.txt.insert("end", text + "\n")
        self.txt.see("end")
        self.txt.config(state="disabled")

    def _show_download(self, d: dict):
        if d.get("error"):
            self.dl_frame.pack_forget()
            return self.flash(f"⚠ Загрузка модели: {d['error']}")
        if d.get("done"):
            self.dl_frame.pack_forget()
            return
        self.dl_frame.pack(fill="x", pady=2)
        self.dl_lbl.config(text=f"⏳ {d['name']}")
        pct = d.get("pct")
        if pct is None:
            self.dl_bar.config(mode="indeterminate")
            self.dl_bar.start(12)
        else:
            self.dl_bar.stop()
            self.dl_bar.config(mode="determinate", value=pct)

    def _current_status(self):
        if STATE.model_loading:
            return "⏳ Загрузка модели…", STATUS_COLORS["load"]
        if STATE.recording:
            return "🔴 Идёт транскрибация конференции", STATUS_COLORS["rec"]
        with STATE.lock:
            conf = bool(STATE.conf_names)
        if conf and CFG.get("auto_start", True):
            return "🟠 Платформа ВКС запущена — жду речь…", STATUS_COLORS["wait"]
        if not STATE.audio_ok:
            return "⚠ Проблема с аудиоустройством", STATUS_COLORS["rec"]
        return "⚪ Ожидание конференции…", STATUS_COLORS["idle"]

    def _poll(self):
        try:
            while True:
                kind, data = UI_Q.get_nowait()
                if kind == "line":
                    self._append(data)
                elif kind == "header":
                    self._append("\n" + data)
                elif kind == "file":
                    self.path_lbl.config(text="💾 " + os.path.basename(data))
                elif kind == "notify":
                    notify(*data)
                elif kind == "clip":
                    try:
                        pyperclip.copy(data)
                    except Exception:
                        pass
                elif kind == "flash":
                    self.flash(data)
                elif kind == "download":
                    self._show_download(data)
                elif kind == "toggle":
                    self.toggle()
                elif kind == "copy":
                    self.copy_all()
                elif kind == "show":
                    self.show()
                elif kind == "wizard":
                    self.open_wizard()
                elif kind == "exit":
                    self.quit_app()
                    return
        except queue.Empty:
            pass

        with STATE.lock:
            lv_sys = min(100.0, STATE.levels.get(TAG_SYS, 0.0) * 800)
            lv_mic = min(100.0, STATE.levels.get(TAG_MIC, 0.0) * 800)
        self.bar_sys["value"] = lv_sys
        self.bar_mic["value"] = lv_mic

        text, color = self._current_status()
        self.status_lbl.config(text=text, fg=color)
        if color != self._last_color:
            set_color(color)
            self._last_color = color
        with STATE.lock:
            conf = ", ".join(sorted(STATE.conf_names))[:70]
        self.conf_lbl.config(
            text=f"Обнаружены платформы: {conf}" if conf
            else "Платформы ВКС не запущены")
        if STATE.active_sources:
            self.src_lbl.config(text="Захват: " + " | ".join(STATE.active_sources))
        if STATE.blackhole_hint:
            self.hint_lbl.config(text="⚠ macOS: установите BlackHole "
                                      "(existential.audio/blackhole) для захвата "
                                      "системного звука")
        self.toggle_btn.config(
            text="⏹ Остановить запись" if STATE.recording else "▶ Запись вручную")
        self.root.after(150, self._poll)
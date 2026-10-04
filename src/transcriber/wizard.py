"""Мастер первой настройки: микрофон -> качество -> загрузка модели."""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk

from . import audio, models
from .config import CFG, save_config
from .state import STATE

MIC_WARN = ("Микрофон молчит. Проверьте:\n"
            "1) Параметры Windows → Конфиденциальность → Микрофон → "
            "доступ включён и для классических приложений\n"
            "2) Уровень микрофона: Win+R → mmsys.cpl → вкладка «Запись»")

MANUAL_HINT = ("Если загрузка не идёт: скачайте 4 файла (config.json, model.bin, "
               "tokenizer.json, vocabulary.txt) браузером со страницы "
               "hf-mirror.com/Systran/faster-whisper-small (или huggingface.co) "
               "и положите их в папку моделей (кнопка ниже), затем «Повторить».")


class Wizard(tk.Toplevel):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.title("Первоначальная настройка")
        self.geometry("680x480")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._probe_stop = None
        self._dl_thread = None
        self._dl_state = {"done": False, "error": None}
        self._lvl = 0.0
        self._zero_since = None
        self._bar_running = False
        self._quality = tk.StringVar(value=CFG.get("quality", "balanced"))
        self._lang = tk.StringVar(value=CFG.get("language", "ru"))

        head = ttk.Frame(self, padding=10)
        head.pack(fill="x")
        self.title_lbl = ttk.Label(head, text="", font=("Segoe UI", 13, "bold"))
        self.title_lbl.pack(anchor="w")
        self.sub_lbl = ttk.Label(head, text="", foreground="#555",
                                 wraplength=640, justify="left")
        self.sub_lbl.pack(anchor="w")

        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill="both", expand=True)

        foot = ttk.Frame(self, padding=10)
        foot.pack(fill="x")
        self.back_btn = ttk.Button(foot, text="← Назад", command=self.go_back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(foot, text="Далее →", command=self.go_next)
        self.next_btn.pack(side="right")
        self.step = 1
        self.show_step(1)
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------- навигация -------------------------
    def go_back(self):
        if self.step == 2:
            self.show_step(1)

    def go_next(self):
        if self.step == 1:
            self.apply_mic()
            self.show_step(2)
        elif self.step == 2:
            CFG["quality"] = self._quality.get()
            CFG["language"] = self._lang.get()
            save_config()
            self.show_step(3)
            self.start_download()
        elif self.step == 3 and self._dl_state["done"]:
            CFG["setup_done"] = True
            save_config()
            self.close()

    def close(self):
        if self._probe_stop:
            self._probe_stop()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _clear(self):
        if self._probe_stop:
            self._probe_stop()
            self._probe_stop = None
        for w in self.body.winfo_children():
            w.destroy()
        self.back_btn.config(state="normal")
        self.next_btn.config(state="normal", text="Далее →")
        self._bar_running = False

    # ------------------------- шаг 1: микрофон -------------------------
    def show_step(self, n: int):
        self._clear()
        self.step = n
        if n == 1:
            self.title_lbl.config(text="Шаг 1 из 3 — Микрофон")
            self.sub_lbl.config(text="Выберите микрофон и скажите что-нибудь: "
                                      "полоска должна колыхаться.")
            self._build_mic_page()
        elif n == 2:
            self.title_lbl.config(text="Шаг 2 из 3 — Качество распознавания")
            self.sub_lbl.config(text="Модель скачается автоматически. "
                                      "Позже можно сменить в настройках.")
            self._build_quality_page()
        else:
            self.title_lbl.config(text="Шаг 3 из 3 — Загрузка модели")
            self.sub_lbl.config(text="Один раз. Прогресс ниже.")
            self._build_download_page()

    def _build_mic_page(self):
        f = self.body
        ttk.Label(f, text="Микрофон:").grid(row=0, column=0, sticky="w", pady=4)
        self.mic_cb = ttk.Combobox(f, width=55, state="readonly")
        self.mic_cb.grid(row=0, column=1, sticky="w")
        ttk.Button(f, text="⟳", width=3,
                   command=self._fill_mics).grid(row=0, column=2, padx=4)
        self.mic_cb.bind("<<ComboboxSelected>>", lambda e: self._start_probe())

        ttk.Label(f, text="Уровень сигнала:").grid(row=1, column=0,
                                                   sticky="w", pady=10)
        self.lvl_bar = ttk.Progressbar(f, length=340, maximum=100)
        self.lvl_bar.grid(row=1, column=1, sticky="w")
        self.warn_lbl = tk.Label(f, text="", fg="#c62828", justify="left",
                                 wraplength=620)
        self.warn_lbl.grid(row=2, column=0, columnspan=3, sticky="w")
        self._zero_since = None
        self._fill_mics()
        self._start_probe()

    def _fill_mics(self):
        self._mics = audio.list_mic_devices()
        self.mic_cb["values"] = (["По умолчанию (системный)"] +
                                 [n for n, _ in self._mics]) or ["— нет —"]
        did = CFG.get("mic_device_id")
        idx = did + 1 if isinstance(did, int) and 0 <= did < len(self._mics) else 0
        self.mic_cb.current(min(idx, max(0, len(self.mic_cb["values"]) - 1)))

    def _start_probe(self):
        if self._probe_stop:
            self._probe_stop()
            self._probe_stop = None
        idx = None
        if getattr(self, "_mics", None) and self.mic_cb.current() > 0:
            idx = self._mics[self.mic_cb.current() - 1][1]
        self._probe_stop = audio.probe_level(idx, self._on_level)
        self._poll_level()

    def _on_level(self, v):
        self._lvl = v

    def _poll_level(self):
        if not self.winfo_exists() or self.step != 1:
            return
        v = self._lvl
        if v < 0:
            self.lvl_bar["value"] = 0
            self.warn_lbl.config(text="Устройство не открывается — выберите другое")
        else:
            self.lvl_bar["value"] = v * 100
            if v > 0.02:
                self._zero_since = None
                self.warn_lbl.config(text="")
            else:
                if self._zero_since is None:
                    self._zero_since = time.time()
                elif time.time() - self._zero_since > 4:
                    self.warn_lbl.config(text=MIC_WARN)
        self.after(120, self._poll_level)

    def apply_mic(self):
        if getattr(self, "_mics", None) and self.mic_cb.current() > 0:
            CFG["mic_device_id"] = self._mics[self.mic_cb.current() - 1][1]
        else:
            CFG["mic_device_id"] = None
        CFG["source"] = "dual"
        save_config()

    # ------------------------- шаг 2: качество -------------------------
    def _build_quality_page(self):
        f = self.body
        ttk.Label(f, text="Качество распознавания:").grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        for i, (key, label) in enumerate(models.QUALITY.items()):
            ttk.Radiobutton(f, text=label, value=key,
                            variable=self._quality).grid(
                row=i + 1, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(f, text="Язык конференции:").grid(
            row=5, column=0, sticky="w", pady=(16, 0))
        ttk.Combobox(f, textvariable=self._lang, width=10, state="readonly",
                     values=["ru", "en", "de", "fr", "es", "uk"]).grid(
            row=5, column=1, sticky="w", pady=(16, 0))
        self.next_btn.config(text="Загрузить модель →")

    # ------------------------- шаг 3: загрузка -------------------------
    def _build_download_page(self):
        f = self.body
        self.dl_lbl = ttk.Label(f, text="Подготовка…")
        self.dl_lbl.grid(row=0, column=0, sticky="w")
        self.dl_bar = ttk.Progressbar(f, length=440, maximum=100)
        self.dl_bar.grid(row=1, column=0, sticky="w", pady=10)
        self.dl_err = tk.Label(f, text="", fg="#c62828", wraplength=620,
                               justify="left")
        self.dl_err.grid(row=2, column=0, columnspan=3, sticky="w")

        btnrow = ttk.Frame(f)
        btnrow.grid(row=3, column=0, sticky="w", pady=6)
        self.retry_btn = ttk.Button(btnrow, text="↻ Повторить",
                                    command=self.start_download)
        self.retry_btn.pack(side="left")
        ttk.Button(btnrow, text="📂 Папка моделей",
                   command=self._open_models).pack(side="left", padx=6)
        self.back_btn.config(state="disabled")
        self.next_btn.config(state="disabled")

    def _open_models(self):
        try:
            os.startfile(models.MODELS_DIR)                   # noqa
        except Exception:
            pass

    def start_download(self):
        self.dl_err.config(text="")
        self.next_btn.config(state="disabled")
        self._dl_state = {"done": False, "error": None}
        self.dl_lbl.config(text="Подготовка…")
        self._dl_thread = threading.Thread(target=self._download, daemon=True)
        self._dl_thread.start()
        self._poll_progress()

    def _download(self):
        try:
            models.reset_engine()
            models.resolve()
            models.get_engine()
            self._dl_state["done"] = True
        except Exception as exc:
            self._dl_state["error"] = str(exc)

    def _poll_progress(self):
        """Живой прогресс: читает STATE.last_download, обновляет бар в мастере."""
        if not self.winfo_exists() or self.step != 3:
            return
        alive = self._dl_thread and self._dl_thread.is_alive()

        with STATE.lock:
            d = dict(STATE.last_download)
        if d and not d.get("done") and not d.get("error") and alive:
            pct = d.get("pct")
            if pct is None:
                self.dl_lbl.config(text=f"⏳ {d.get('name', '')} — соединение…")
                if not self._bar_running:
                    self.dl_bar.config(mode="indeterminate")
                    self.dl_bar.start(12)
                    self._bar_running = True
            else:
                if self._bar_running:
                    self.dl_bar.stop()
                    self.dl_bar.config(mode="determinate")
                    self._bar_running = False
                self.dl_bar.config(value=pct)
                self.dl_lbl.config(text=f"⏳ {d.get('name', '')} — {pct}%")

        if alive:
            self.after(300, self._poll_progress)
            return

        # поток завершился
        if self._bar_running:
            self.dl_bar.stop()
            self.dl_bar.config(mode="determinate")
            self._bar_running = False
        if self._dl_state["done"]:
            self.dl_bar.config(value=100)
            self.dl_lbl.config(text="✅ Модель загружена и готова")
            self.next_btn.config(state="normal", text="Готово ✓")
        elif self._dl_state["error"]:
            self.dl_bar.config(value=0)
            self.dl_lbl.config(text="Ошибка загрузки")
            self.dl_err.config(text=f"{self._dl_state['error']}\n\n{MANUAL_HINT}")
        else:
            self.after(300, self._poll_progress)   # ещё стартует
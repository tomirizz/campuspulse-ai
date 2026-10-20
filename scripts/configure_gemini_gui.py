"""Local, masked owner credential entry. Never sends or prints the key."""
from pathlib import Path
import os

from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parents[1]


def save_key(value, destination=None):
    value = value.strip()
    if len(value) < 20 or any(char.isspace() for char in value):
        raise ValueError("Вставьте полный ключ из Google AI Studio, без пробелов.")
    path = Path(destination) if destination else ROOT / ".env"
    if not path.exists():
        path.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    model = dotenv_values(path).get("GEMINI_MODEL") or "gemini-3.8-flash"
    for name, content in {"GEMINI_API_KEY": value, "GEMINI_MODEL": model, "AGENT_MODE": "gemini"}.items():
        set_key(str(path), name, content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def main():
    import tkinter as tk
    from tkinter import messagebox

    window = tk.Tk()
    window.title("CampusPulse — подключить Gemini")
    window.geometry("650x330")
    window.resizable(False, False)
    window.configure(bg="#f8f6ff")
    window.attributes("-topmost", True)
    panel = tk.Frame(window, bg="#f8f6ff", padx=28, pady=24)
    panel.pack(fill="both", expand=True)
    tk.Label(panel, text="Подключим Gemini", bg="#f8f6ff", fg="#292238",
             font=("Segoe UI", 20, "bold")).pack(anchor="w")
    tk.Label(panel, text="Вставь API-ключ из Google AI Studio. Ввод скрыт звёздочками.",
             bg="#f8f6ff", fg="#5b5367", font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 16))
    entry = tk.Entry(panel, show="*", font=("Segoe UI", 13), relief="solid", borderwidth=1)
    entry.pack(fill="x", ipady=8)
    status = tk.StringVar(value="Ключ сохранится в локальном .env и не появится в чате.")
    tk.Label(panel, textvariable=status, bg="#f8f6ff", fg="#5b5367",
             font=("Segoe UI", 10), wraplength=580, justify="left").pack(anchor="w", pady=12)
    actions = tk.Frame(panel, bg="#f8f6ff")
    actions.pack(fill="x")

    def paste():
        try:
            value = window.clipboard_get()
            entry.delete(0, "end")
            entry.insert(0, value.strip())
            status.set("Ключ вставлен. Теперь нажми «Сохранить».")
        except tk.TclError:
            status.set("Буфер пуст или не содержит текст. Сначала скопируй ключ в AI Studio.")
        entry.focus_set()

    def save():
        try:
            save_key(entry.get())
        except ValueError as exc:
            status.set(str(exc))
            return
        except OSError:
            status.set("Не удалось сохранить .env. Закрой редактор этого файла и попробуй ещё раз.")
            return
        entry.delete(0, "end")
        messagebox.showinfo("CampusPulse", "Ключ сохранён!\nНапиши в Codex «сохранён» — проверим подключение.", parent=window)
        window.destroy()

    tk.Button(actions, text="Вставить из буфера", command=paste, font=("Segoe UI", 11),
              padx=16, pady=8).pack(side="left")
    tk.Button(actions, text="Сохранить", command=save, font=("Segoe UI", 11, "bold"),
              bg="#7655d9", fg="white", activebackground="#6544c8", activeforeground="white",
              padx=24, pady=8).pack(side="right")
    tk.Label(panel, text="Для бесплатной работы оставь проект ключа на Free tier, без billing.",
             bg="#f8f6ff", fg="#756b83", font=("Segoe UI", 9)).pack(anchor="w", pady=(16, 0))
    window.bind("<Return>", lambda event: save())
    window.after(100, entry.focus_force)
    window.mainloop()


if __name__ == "__main__":
    main()

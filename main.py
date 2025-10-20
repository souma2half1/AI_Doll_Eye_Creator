"""AI Doll Eye Creator desktop application."""
from __future__ import annotations

import base64
import os
import queue
import threading
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from io import BytesIO

from dotenv import load_dotenv
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, ttk, filedialog

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / "config" / "chatgpt_settings.env")

APP_TITLE = "AI Doll Eye Creator"
WINDOW_SIZE = "480x620"
OUTPUT_DIR = Path("output")
PROMPT_MODEL = os.getenv("PROMPT_MODEL", "gpt-5-preview")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")


class MissingDependencyError(RuntimeError):
    """Raised when an optional dependency is required but missing."""


@dataclass
class EyeDesignConfig:
    color: str
    shape: str
    motif: str
    texture: str
    gloss: str
    extra: str

    def to_prompt_instructions(self) -> str:
        return (
            f"Color: {self.color}. Shape: {self.shape}. Motif: {self.motif}. "
            f"Texture: {self.texture}. Gloss level: {self.gloss}. "
            f"Additional instructions: {self.extra or 'None'}"
        )


class PromptBuilder:
    """Builds English prompts using the GPT language model."""

    def __init__(self, client_factory):
        self._client_factory = client_factory

    def build_prompt(self, config: EyeDesignConfig) -> str:
        client = self._client_factory()
        if client is None:
            raise MissingDependencyError(
                "The OpenAI client is not available. Install the 'openai' package."
            )

        system_prompt = (
            "You are a creative prompt engineer that converts structured design cues "
            "into vivid English descriptions for AI-generated doll eyes."
        )
        user_prompt = (
            "Convert the following design specification into an evocative, single-paragraph "
            "English prompt suitable for an image generation model. Include references to "
            "color, shape, motif, texture, and gloss intensity. Avoid bullet points.\n\n"
            f"Design specification:\n{config.to_prompt_instructions()}"
        )

        response = client.responses.create(
            model=PROMPT_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_output_tokens=250,
        )

        content = getattr(response, "output_text", None)
        if not content:
            try:
                content = response.output[0].content[0].text  # type: ignore[attr-defined]
            except (AttributeError, IndexError, KeyError, TypeError) as exc:
                raise RuntimeError("Failed to parse prompt from model response.") from exc
        return content.strip()


class ImageGenerator:
    """Generates an eye design image using the OpenAI Images API."""

    def __init__(self, client_factory):
        self._client_factory = client_factory

    def generate_image(self, prompt: str) -> Image.Image:
        client = self._client_factory()
        if client is None:
            raise MissingDependencyError(
                "The OpenAI client is not available. Install the 'openai' package."
            )

        result = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality="high",
        )
        try:
            image_base64 = result.data[0].b64_json  # type: ignore[attr-defined]
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise RuntimeError("Failed to parse image payload from API response.") from exc
        image_bytes = base64.b64decode(image_base64)
        buffer = BytesIO(image_bytes)
        image = Image.open(buffer)
        image.load()
        buffer.close()
        return image


class FileManager:
    """Handles output directory management and file saving."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_image(self, image: Image.Image, config: EyeDesignConfig) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        sanitized_color = config.color.replace(" ", "")
        sanitized_shape = config.shape.replace(" ", "")
        filename = f"eye_{sanitized_color}_{sanitized_shape}_{timestamp}.png"
        filepath = self.base_dir / filename
        image.save(filepath, format="PNG")
        return filepath


class ProgressTracker:
    """Tracks progress updates in a thread-safe manner."""

    def __init__(self):
        self._queue: queue.Queue[tuple[float, str]] = queue.Queue()

    def set_progress(self, value: float, message: str) -> None:
        self._queue.put((value, message))

    def get_latest(self) -> Optional[tuple[float, str]]:
        latest: Optional[tuple[float, str]] = None
        try:
            while True:
                latest = self._queue.get_nowait()
        except queue.Empty:
            pass
        return latest


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.resizable(False, False)

        self._client_cache = None
        self.prompt_builder = PromptBuilder(self._get_client)
        self.image_generator = ImageGenerator(self._get_client)
        self.file_manager = FileManager(OUTPUT_DIR)
        self.progress_tracker = ProgressTracker()
        self._worker_thread: Optional[threading.Thread] = None
        self.last_output_path: Optional[Path] = None

        self._photo_image: Optional[ImageTk.PhotoImage] = None
        self._build_ui()

    # region UI construction
    def _build_ui(self) -> None:
        padding = {"padx": 10, "pady": 5}

        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True)

        self.color_var = tk.StringVar(value="青")
        self.shape_var = tk.StringVar(value="丸")
        self.motif_var = tk.StringVar(value="なし")
        self.texture_var = tk.StringVar(value="アニメ調")
        self.gloss_var = tk.StringVar(value="中")
        self.extra_text = tk.Text(main_frame, height=4, width=40)

        dropdowns = [
            ("色", self.color_var, ["青", "赤", "紫", "ピンク", "緑", "金", "銀"]),
            ("形状", self.shape_var, ["丸", "楕円", "縦長", "横長"]),
            ("モチーフ", self.motif_var, ["なし", "星", "ハート", "ウサギ", "月"]),
            (
                "質感",
                self.texture_var,
                ["アニメ調", "ガラスアイ", "宝石風", "メタリック"],
            ),
            ("光沢レベル", self.gloss_var, ["低", "中", "高"]),
        ]

        for label_text, variable, options in dropdowns:
            row = ttk.Frame(main_frame)
            row.pack(fill="x", **padding)
            ttk.Label(row, text=label_text, width=12).pack(side="left")
            combo = ttk.Combobox(row, textvariable=variable, values=options, state="readonly")
            combo.pack(side="left", fill="x", expand=True)

        instructions_frame = ttk.LabelFrame(main_frame, text="詳細指示")
        instructions_frame.pack(fill="both", **padding)
        self.extra_text.pack(in_=instructions_frame, fill="both", expand=True, padx=5, pady=5)

        self.firealpaca_path = tk.StringVar()
        firealpaca_frame = ttk.Frame(main_frame)
        firealpaca_frame.pack(fill="x", **padding)
        ttk.Label(firealpaca_frame, text="FireAlpaca パス", width=12).pack(side="left")
        ttk.Entry(firealpaca_frame, textvariable=self.firealpaca_path).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(firealpaca_frame, text="参照", command=self._select_firealpaca).pack(side="left", padx=5)

        self.generate_button = ttk.Button(main_frame, text="AI 生成開始", command=self._on_generate)
        self.generate_button.pack(fill="x", padx=10, pady=(5, 0))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(main_frame, maximum=100, variable=self.progress_var)
        self.progress_bar.pack(fill="x", padx=10, pady=5)

        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(main_frame, textvariable=self.status_var).pack(fill="x", padx=10)

        preview_frame = ttk.LabelFrame(main_frame, text="プレビュー")
        preview_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(fill="both", expand=True)

        ttk.Button(main_frame, text="FireAlpaca で開く", command=self._open_in_firealpaca).pack(
            fill="x", padx=10, pady=(0, 10)
        )

        self.after(200, self._poll_progress)

    # endregion

    def _select_firealpaca(self) -> None:
        path = filedialog.askopenfilename(title="FireAlpaca 実行ファイルを選択")
        if path:
            self.firealpaca_path.set(path)

    def _get_client(self):
        if OpenAI is None:
            return None
        if self._client_cache is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise MissingDependencyError("OPENAI_API_KEY is not set in the environment.")
            self._client_cache = OpenAI(api_key=api_key)
        return self._client_cache

    def _on_generate(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("処理中", "現在画像を生成しています。完了までお待ちください。")
            return

        config = EyeDesignConfig(
            color=self.color_var.get(),
            shape=self.shape_var.get(),
            motif=self.motif_var.get(),
            texture=self.texture_var.get(),
            gloss=self.gloss_var.get(),
            extra=self.extra_text.get("1.0", "end").strip(),
        )

        self.progress_tracker.set_progress(5, "プロンプトを準備しています…")
        self._set_busy_state(True)

        self._worker_thread = threading.Thread(
            target=self._run_generation, args=(config,), daemon=True
        )
        self._worker_thread.start()

    def _run_generation(self, config: EyeDesignConfig) -> None:
        try:
            prompt = self.prompt_builder.build_prompt(config)
            self.progress_tracker.set_progress(35, "画像を生成しています…")
            image = self.image_generator.generate_image(prompt)
            self.progress_tracker.set_progress(65, "画像を保存しています…")
            path = self.file_manager.save_image(image, config)
            self.progress_tracker.set_progress(90, "プレビューを更新しています…")
            self.after(0, lambda img=image: self._update_preview(img))
            self.after(0, lambda p=path: setattr(self, "last_output_path", p))
            self.progress_tracker.set_progress(100, f"生成完了: {path.name}")
        except MissingDependencyError as exc:
            self._handle_error(str(exc))
        except Exception as exc:  # pragma: no cover - runtime error reporting
            self._handle_error(f"生成に失敗しました: {exc}")
        finally:
            self._worker_thread = None
            self._set_busy_state(False)

    def _update_preview(self, image: Image.Image) -> None:
        max_size = (400, 400)
        image_copy = image.copy()
        image_copy.thumbnail(max_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(image_copy)
        self._photo_image = photo
        self.preview_label.configure(image=photo)

    def _handle_error(self, message: str) -> None:
        self.progress_tracker.set_progress(0, message)

        def show_error() -> None:
            self.status_var.set(message)
            messagebox.showerror("エラー", message)

        self.after(0, show_error)

    def _set_busy_state(self, busy: bool) -> None:
        def toggle_state():
            state = "disabled" if busy else "normal"
            self.generate_button.configure(state=state)

        self.after(0, toggle_state)

    def _poll_progress(self) -> None:
        latest = self.progress_tracker.get_latest()
        if latest:
            value, message = latest
            self.progress_var.set(value)
            self.status_var.set(message)
        self.after(200, self._poll_progress)

    def _open_in_firealpaca(self) -> None:
        path = self.firealpaca_path.get()
        if not path:
            messagebox.showinfo("FireAlpaca", "FireAlpaca の実行ファイルパスを設定してください。")
            return

        latest_file = self._get_latest_output_file()
        if not latest_file:
            messagebox.showinfo("FireAlpaca", "まだ生成された画像がありません。")
            return

        try:
            import subprocess

            subprocess.Popen([path, str(latest_file)])
        except Exception as exc:  # pragma: no cover - OS dependent
            messagebox.showerror("FireAlpaca", f"起動に失敗しました: {exc}")

    def _get_latest_output_file(self) -> Optional[Path]:
        if self.last_output_path and self.last_output_path.exists():
            return self.last_output_path
        png_files = sorted(OUTPUT_DIR.glob("*.png"), reverse=True)
        return png_files[0] if png_files else None


def main() -> None:
    def show_message(title: str, message: str) -> None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()

    if OpenAI is None:
        show_message(
            "依存関係エラー",
            "'openai' パッケージがインストールされていません。requirements.txt を確認してください。",
        )
        return

    try:
        app = Application()
        app.mainloop()
    except MissingDependencyError as exc:
        show_message("設定エラー", str(exc))


if __name__ == "__main__":
    main()

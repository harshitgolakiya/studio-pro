"""Recipe library window: apply, save, duplicate, delete, import and export."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

import customtkinter as ctk

from recipes import (
    RECIPE_EXTENSION,
    Recipe,
    RecipeError,
    delete_recipe,
    duplicate_recipe,
    export_recipe,
    find_recipe,
    import_recipe,
    list_recipes,
    save_recipe,
)

_MUTED = ("#607181", "#91A0AE")
_ROW = ("#FFFFFF", "#11161D")
_ROW_ACTIVE = ("#D8F3EF", "#123A36")


class RecipeManagerDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: Any,
        collect_settings: Callable[[], dict[str, Any]],
        apply_settings: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(master)
        self.title("Processing Recipes")
        self.geometry("620x520")
        self.minsize(520, 400)
        self.transient(master)

        self._collect = collect_settings
        self._apply = apply_settings
        self._selected: str | None = None
        self._rows: dict[str, ctk.CTkFrame] = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 6))
        ctk.CTkLabel(header, text="Saved recipes", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Save current as…", width=140, height=30, command=self._save_current).pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=8, pady=4)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(6, 14))
        self.apply_btn = ctk.CTkButton(actions, text="Apply", width=90, height=30, command=self._apply_selected)
        self.apply_btn.pack(side="left", padx=(0, 6))
        self.dup_btn = ctk.CTkButton(actions, text="Duplicate", width=90, height=30, fg_color="transparent", border_width=1, command=self._duplicate_selected)
        self.dup_btn.pack(side="left", padx=(0, 6))
        self.del_btn = ctk.CTkButton(actions, text="Delete", width=80, height=30, fg_color="transparent", border_width=1, command=self._delete_selected)
        self.del_btn.pack(side="left", padx=(0, 6))
        self.export_btn = ctk.CTkButton(actions, text="Export…", width=90, height=30, fg_color="transparent", border_width=1, command=self._export_selected)
        self.export_btn.pack(side="right")
        ctk.CTkButton(actions, text="Import…", width=90, height=30, fg_color="transparent", border_width=1, command=self._import).pack(side="right", padx=(0, 6))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.refresh()

    # -- list --------------------------------------------------------------

    def refresh(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._rows.clear()

        recipes = list_recipes()
        if not recipes:
            ctk.CTkLabel(
                self.list_frame,
                text="No recipes yet. Set up the conversion the way you like it, then click “Save current as…”.",
                text_color=_MUTED,
                wraplength=520,
            ).pack(pady=30)
        for recipe in recipes:
            self._rows[recipe.name] = self._build_row(recipe)

        if self._selected not in self._rows:
            self._selected = next(iter(self._rows), None)
        self._highlight()

    def _build_row(self, recipe: Recipe) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list_frame, corner_radius=8, fg_color=_ROW)
        row.pack(fill="x", padx=6, pady=2)
        ctk.CTkLabel(row, text=recipe.name, anchor="w", font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", padx=10, pady=(7, 0))
        s = recipe.settings
        parts = [s["target_format"]]
        if s["target_format"].upper() in ("WEBP", "AVIF", "HEIC", "JPEG") and not s["lossless"]:
            parts.append(f"quality {s['quality']}")
        if s["lossless"]:
            parts.append("lossless")
        if s["enable_resize"]:
            cond = str(s.get("resize_condition", "always")).strip().lower()
            if cond and cond != "always":
                cond_label = cond.replace("only_", "").replace("_", " ")
                parts.append(f"max {s['max_dimension_text']}px ({cond_label})")
            else:
                parts.append(f"max {s['max_dimension_text']}px")
        if s["enable_target_size"]:
            parts.append(f"target {s['target_size_val']} {s['target_size_unit']}")
        if s["enable_watermark"]:
            parts.append("watermark")
        if s["strip_metadata"]:
            parts.append("strip EXIF")
        summary = "  ·  ".join(parts)
        if recipe.description:
            summary = f"{recipe.description}\n{summary}"
        ctk.CTkLabel(row, text=summary, anchor="w", justify="left", font=ctk.CTkFont(size=11), text_color=_MUTED, wraplength=540).pack(fill="x", padx=10, pady=(0, 7))

        def select(_e: Any = None, name: str = recipe.name) -> None:
            self._selected = name
            self._highlight()

        def activate(_e: Any = None, name: str = recipe.name) -> None:
            self._selected = name
            self._apply_selected()

        for widget in (row, *row.winfo_children()):
            widget.bind("<Button-1>", select)
            widget.bind("<Double-Button-1>", activate)
        return row

    def _highlight(self) -> None:
        for name, row in self._rows.items():
            row.configure(fg_color=_ROW_ACTIVE if name == self._selected else _ROW)
        state = "normal" if self._selected else "disabled"
        for btn in (self.apply_btn, self.dup_btn, self.del_btn, self.export_btn):
            btn.configure(state=state)

    # -- actions -----------------------------------------------------------

    def _ask_name(self, title: str, prompt: str, initial: str = "") -> str | None:
        dialog = ctk.CTkInputDialog(title=title, text=prompt)
        if initial:
            try:
                dialog._entry.insert(0, initial)
            except Exception:
                pass
        value = dialog.get_input()
        if value is None:
            return None
        value = value.strip()
        return value or None

    def _save_current(self) -> None:
        name = self._ask_name("Save recipe", "Name for this recipe:")
        if not name:
            return
        if find_recipe(name) and not messagebox.askyesno("Replace recipe?", f"A recipe named “{name}” already exists. Replace it?", parent=self):
            return
        save_recipe(Recipe(name=name, settings=self._collect()))
        self._selected = name
        self.refresh()

    def _apply_selected(self) -> None:
        if not self._selected:
            return
        recipe = find_recipe(self._selected)
        if recipe is None:
            self.refresh()
            return
        self._apply(recipe.settings)
        self.destroy()

    def _duplicate_selected(self) -> None:
        if not self._selected:
            return
        name = self._ask_name("Duplicate recipe", "Name for the copy:", f"{self._selected} copy")
        if not name:
            return
        try:
            duplicate_recipe(self._selected, name)
        except RecipeError as exc:
            messagebox.showerror("Duplicate failed", str(exc), parent=self)
            return
        self._selected = name
        self.refresh()

    def _delete_selected(self) -> None:
        if not self._selected:
            return
        if messagebox.askyesno("Delete recipe?", f"Delete “{self._selected}”? This can't be undone.", parent=self):
            delete_recipe(self._selected)
            self._selected = None
            self.refresh()

    def _import(self) -> None:
        path = filedialog.askopenfilename(
            title="Import recipe",
            filetypes=[("Shadow recipe", f"*{RECIPE_EXTENSION}"), ("JSON", "*.json"), ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        try:
            recipe = import_recipe(Path(path))
        except RecipeError as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)
            return
        self._selected = recipe.name
        self.refresh()

    def _export_selected(self) -> None:
        if not self._selected:
            return
        path = filedialog.asksaveasfilename(
            title="Export recipe",
            defaultextension=RECIPE_EXTENSION,
            initialfile=f"{self._selected}{RECIPE_EXTENSION}",
            filetypes=[("Shadow recipe", f"*{RECIPE_EXTENSION}")],
            parent=self,
        )
        if not path:
            return
        try:
            export_recipe(self._selected, Path(path))
        except RecipeError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

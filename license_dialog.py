from __future__ import annotations

import os
from urllib.parse import urlparse
import webbrowser

import customtkinter as ctk

from accessibility import enable_keyboard_navigation
from font_loader import DISPLAY_FONT
from licensing import activate_license, deactivate_license, get_license_info

# Set this in the release environment or replace the empty default with the
# product's final checkout page.  Never send customers to a marketplace home
# page that cannot actually complete their purchase.
PURCHASE_URL = os.environ.get("SHADOW_PURCHASE_URL", "").strip()


def valid_purchase_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


class LicenseDialog(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, on_status_changed: object | None = None) -> None:
        super().__init__(parent)
        self.title("Shadow Media Studio Pro - License Manager")
        self.geometry("560x520")
        self.minsize(520, 480)
        from ui_dispatch import set_dialog_owner
        set_dialog_owner(self, parent)
        self.on_status_changed = on_status_changed
        self._grab_after_id: str | None = self.after(50, self._grab_when_viewable)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(self, corner_radius=14, fg_color=("#ffffff", "#191c20"))
        card.grid(row=0, column=0, padx=24, pady=24, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        # Header Badge
        info = get_license_info()
        is_pro = info["is_pro"]
        is_vip = info.get("is_vip", False)

        if is_vip:
            badge_color = "#D4A03C"
            badge_text_color = "#171308"
            badge_text = "VIP MASTER ACTIVATED"
        elif is_pro:
            badge_color = "#16a34a"
            badge_text_color = "#ffffff"
            badge_text = "PRO LIFETIME ACTIVATED"
        else:
            badge_color = "#d97706"
            badge_text_color = "#171308"
            badge_text = "FREE EVALUATION MODE"

        ctk.CTkLabel(
            card,
            text=badge_text,
            fg_color=badge_color,
            text_color=badge_text_color,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            width=200,
            height=26,
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            card,
            text="Shadow Media Studio Pro",
            font=ctk.CTkFont(family=DISPLAY_FONT, size=21, weight="bold"),
            text_color=("#101828", "#f2f4f7"),
        ).pack()

        # Pro Benefits list
        benefits = (
            "• Unlimited batch file processing (Free limited to 5 files)\n"
            "• High-performance Video (MP4/WebM) & Audio (MP3/Opus) suite\n"
            "• Smart Target Size Solver (compress to exact KB/MB)\n"
            "• Batch Watermarking & SEO Slugification\n"
            "• Windows Explorer Context Menu integration\n"
            "• VIP Power Feature: Media Stream Downloader (YouTube/Vimeo)"
        )
        ctk.CTkLabel(
            card,
            text=benefits,
            justify="left",
            text_color=("#667085", "#98a2b3"),
            font=ctk.CTkFont(size=12),
        ).pack(pady=(12, 14), padx=24, anchor="w")

        # License Key entry (paste-friendly multi-line box; keys are long)
        self.entry = ctk.CTkTextbox(
            card,
            height=90,
            font=ctk.CTkFont(size=12, family="Consolas"),
            wrap="char",
        )
        self.entry.pack(fill="x", padx=28, pady=(0, 10))
        self.entry.insert("1.0", info.get("key", ""))
        ctk.CTkLabel(
            card,
            text="Paste your full key: PRO-XXXXXXXX-... or VIP-XXXXXXXX-...",
            font=ctk.CTkFont(size=10),
            text_color=("#98a2b3", "#667085"),
        ).pack(padx=28, anchor="w")

        self.msg_label = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#d92d20",
        )
        self.msg_label.pack(pady=(0, 12))

        # Actions
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(pady=(0, 18))

        if not is_pro:
            ctk.CTkButton(
                actions,
                text="Activate Key",
                command=self._do_activate,
                width=120,
                height=34,
                fg_color="#12877A",
                hover_color="#17A594",
            ).pack(side="left", padx=6)
            ctk.CTkButton(
                actions,
                text="Buy License",
                command=self._open_purchase_page,
                width=130,
                height=34,
                fg_color="transparent",
                border_width=1,
                border_color=("#d0d5dd", "#475467"),
                text_color=("#344054", "#f2f4f7"),
            ).pack(side="left", padx=6)
        else:
            ctk.CTkButton(
                actions,
                text="Deactivate",
                command=self._do_deactivate,
                width=120,
                height=34,
                fg_color="gray40",
            ).pack(side="left", padx=6)

        ctk.CTkButton(
            actions,
            text="Close",
            command=self.destroy,
            width=90,
            height=34,
            fg_color="transparent",
            border_width=1,
            border_color=("#d0d5dd", "#475467"),
            text_color=("#344054", "#f2f4f7"),
        ).pack(side="left", padx=6)

        enable_keyboard_navigation(self)

    def _grab_when_viewable(self) -> None:
        self._grab_after_id = None
        if self.winfo_exists() and self.winfo_viewable():
            self.grab_set()

    def _open_purchase_page(self) -> None:
        if not valid_purchase_url(PURCHASE_URL):
            self.msg_label.configure(
                text="The purchase page has not been configured. Contact the publisher for a license.",
                text_color="#d97706",
            )
            return
        if not webbrowser.open_new_tab(PURCHASE_URL):
            self.msg_label.configure(
                text="Could not open the purchase page in your browser.",
                text_color="#d92d20",
            )

    def destroy(self) -> None:
        pending = getattr(self, "_grab_after_id", None)
        if pending is not None:
            self._grab_after_id = None
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        super().destroy()

    def _do_activate(self) -> None:
        key = self.entry.get("1.0", "end").strip()
        ok, msg = activate_license(key)
        if ok:
            self.msg_label.configure(text=msg, text_color="#16a34a")
            if callable(self.on_status_changed):
                self.on_status_changed()
            self.after(1200, self.destroy)
        else:
            self.msg_label.configure(text=msg, text_color="#d92d20")

    def _do_deactivate(self) -> None:
        deactivate_license()
        self.entry.delete("1.0", "end")
        self.msg_label.configure(text="License deactivated.", text_color="#d97706")
        if callable(self.on_status_changed):
            self.on_status_changed()
        self.after(1000, self.destroy)

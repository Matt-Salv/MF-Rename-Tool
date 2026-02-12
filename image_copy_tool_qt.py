# ---------------- STANDARD LIBRARY ----------------
import sys
import re
import shutil
import logging
from pathlib import Path

# ---------------- THIRD-PARTY ----------------
import pandas as pd
import requests
import webbrowser
from PIL import Image

# ---------------- QT ----------------
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QPushButton,
    QLineEdit,
    QComboBox,
    QLabel,
    QCheckBox,
    QDialog,
    QTextEdit,
    QProgressDialog,
    QProgressBar,
)

APP_VERSION = "1.0.0"

# ---------------- UTILS ----------------
def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def convert_image(src: Path, dst: Path):
    """
    Convert image at src to dst format using Pillow.
    """
    with Image.open(src) as img:
        # Convert to RGB for formats like JPG that don't support alpha
        if dst.suffix.lower() in {".jpg", ".jpeg"}:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.save(dst, format="JPEG", quality=95, subsampling=0)
        else:
            img.save(dst)
            
def get_safe_dest_path(dest_path: Path) -> Path:
    """
    If dest_path exists, append _1, _2, etc. until a free name is found.
    """
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent

    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1

class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: Path, dest_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Preview")
        self.resize(500, 600)

        layout = QVBoxLayout(self)

        # Image preview
        pixmap = QPixmap(str(image_path))
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)

        if not pixmap.isNull():
            img_label.setPixmap(
                pixmap.scaled(450, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            img_label.setText("Unable to preview image")

        layout.addWidget(img_label)

        # Info text
        stat = image_path.stat()
        info = (
            f"Source: {image_path}\n"
            f"Destination: {dest_path.name}\n\n"
            f"Resolution: {pixmap.width()} x {pixmap.height()}\n"
            f"File size: {stat.st_size / 1024:.1f} KB\n"
            f"Type: {image_path.suffix}"
        )

        info_box = QTextEdit()
        info_box.setReadOnly(True)
        info_box.setText(info)
        info_box.setFixedHeight(140)
        layout.addWidget(info_box)

        # Buttons
        btn_row = QHBoxLayout()

        approve = QPushButton("Approve")
        skip = QPushButton("Skip")
        cancel = QPushButton("Cancel All")

        approve.clicked.connect(lambda: self.done(1))
        skip.clicked.connect(lambda: self.done(0))
        cancel.clicked.connect(lambda: self.done(-1))

        btn_row.addStretch()
        btn_row.addWidget(approve)
        btn_row.addWidget(skip)
        btn_row.addWidget(cancel)

        layout.addLayout(btn_row)

def check_for_updates():
    url = "https://raw.githubusercontent.com/Matt-Salv/MF-Rename-Tool/main/version.txt"
    
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        latest_version = response.text.strip()

        if latest_version != APP_VERSION:
            return latest_version

    except Exception:
        # Silent fail — don't block app if offline
        return None

    return None

# ---------------- UTILS END ----------------        

# ---------------- MAIN WINDOW ----------------
class ImageTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Copy & Rename Tool")
        self.resize(900, 600)
        self.convert_all_mode = False
        self.settings = QSettings("Mayflower", "ImageTool")
        self.df = None
        self.columns = []
        self._build_ui()
        self.preferred_ext = ".jpg"
        self.fallback_mode = "convert"  # "none" | "copy" | "convert"
        self.load_settings()
        self.convert_all_mode = False
        self.cancel_all_mode = False
        latest = check_for_updates()
        if latest:
            reply = QMessageBox.question(
                self,
                "Update Available",
                f"A new version ({latest}) is available.\n\n"
                f"You are running {APP_VERSION}.\n\n"
                "Would you like to download it?",
                QMessageBox.Yes | QMessageBox.No
            )

        if reply == QMessageBox.Yes:
            webbrowser.open("https://raw.githubusercontent.com/Matt-Salv/MF-Rename-Tool/main/version.txt")

  
    # ---------------- UI ----------------
    def _build_ui(self):
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        # -------- MAIN TAB --------
        main_tab = QWidget()
        tabs.addTab(main_tab, "Main")

        main_layout = QVBoxLayout(main_tab)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setSpacing(12)

        # Excel
        self.excel_edit = QLineEdit()
        excel_btn = QPushButton("Browse")
        excel_btn.clicked.connect(self.select_excel)

        excel_row = QHBoxLayout()
        excel_row.addWidget(self.excel_edit)
        excel_row.addWidget(excel_btn)
        form.addRow("Excel Spreadsheet", excel_row)

        # Base Image Folder
        self.base_edit = QLineEdit()
        base_btn = QPushButton("Browse")
        base_btn.clicked.connect(self.select_base)

        base_row = QHBoxLayout()
        base_row.addWidget(self.base_edit)
        base_row.addWidget(base_btn)
        form.addRow("Base Image Folder (Optional)", base_row)

        # Output Folder
        self.out_edit = QLineEdit()
        out_btn = QPushButton("Browse")
        out_btn.clicked.connect(self.select_output)

        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit)
        out_row.addWidget(out_btn)
        form.addRow("Output Folder", out_row)

        main_layout.addLayout(form)

        main_layout.addSpacing(20)
        main_layout.addWidget(QLabel("<b>Excel Column Mapping</b>"))

        # Column mapping
        map_form = QFormLayout()
        map_form.setSpacing(10)

        self.image_col = QComboBox()
        self.newname_col = QComboBox()
        self.vendor_col = QComboBox()
        self.vendor_value = QComboBox()
        self.vendor_value.setEnabled(False)
        self.vendor_col.currentTextChanged.connect(self.update_vendor_list)
        self.vendor_value.addItem("All Vendors")
        
        map_form.addRow("Image Path Column", self.image_col)
        map_form.addRow("New Image Name Column (Optional)", self.newname_col)
        map_form.addRow("Vendor Column (Optional)", self.vendor_col)
        map_form.addRow("Vendor to Process", self.vendor_value)

        main_layout.addLayout(map_form)
        main_layout.addStretch()

        run_btn = QPushButton("Run")
        run_btn.setFixedWidth(120)
        run_btn.clicked.connect(self.run)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(run_btn)
        main_layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignLeft)

        self.progress_text = QLabel("")
        self.progress_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)  # since we're using progress_text now

        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_text)
        main_layout.addWidget(self.progress_bar)

        # -------- SETTINGS TAB --------
        settings_tab = QWidget()
        tabs.addTab(settings_tab, "Settings")

        settings_layout = QFormLayout(settings_tab)
        settings_layout.setSpacing(12)
        self.remember_checkbox = QCheckBox("Remember previous inputs")
        settings_layout.addWidget(self.remember_checkbox)
        self.remember_checkbox.setChecked(True)

        # Preferred output type
        self.preferred_type_box = QComboBox()
        self.preferred_type_box.addItems([".jpg", ".png", ".gif"])
        self.preferred_type_box.setCurrentText(".jpg")
        self.preferred_type_box.currentTextChanged.connect(
            lambda v: setattr(self, "preferred_ext", v)
        )

        settings_layout.addRow("Preferred Output Image Type", self.preferred_type_box)

        # Fallback behavior
        self.fallback_box = QComboBox()
        self.fallback_box.addItems([
            "Do nothing (mark not found)",
            "Copy fallback as-is",
            "Convert fallback to preferred type"
        ])
        self.fallback_box.setCurrentIndex(2)

        self.fallback_box.currentTextChanged.connect(self.update_fallback_mode)
        settings_layout.addRow("When Preferred Type Not Found", self.fallback_box)

        # Overwrite / duplicate handling
        self.preview_toggle = QComboBox()
        self.preview_toggle.addItems([
            "Show preview before overwriting",
            "Do not show preview"
        ])
        self.preview_toggle.setCurrentIndex(0)
        self.preview_toggle.currentTextChanged.connect(
            lambda t: setattr(self, "show_preview_on_conflict", t.startswith("Show"))
        )

        settings_layout.addRow("On Filename Conflict", self.preview_toggle)


        self.rename_toggle = QComboBox()
        self.rename_toggle.addItems([
            "Auto-rename duplicates (_1, _2, ...)",
            "Do not auto-rename"
        ])
        self.rename_toggle.setCurrentIndex(0)
        self.rename_toggle.currentTextChanged.connect(
            lambda t: setattr(self, "auto_rename_duplicates", t.startswith("Auto"))
        )

        settings_layout.addRow("Duplicate Filename Handling", self.rename_toggle)
    # ---------------- UI END ----------------

    # ---------------- ACTIONS ----------------
    def select_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if not path:
            return

        self.excel_edit.setText(path)

        try:
            self.df = pd.read_excel(path)

            self.columns = list(self.df.columns)

            for box in (self.image_col, self.newname_col, self.vendor_col):
                box.clear()
                box.addItem("")  # optional
                box.addItems(self.columns)
            
            self.update_vendor_list()

            QMessageBox.information(self, "Loaded", f"Loaded {len(self.df)} rows.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def select_base(self):
        path = QFileDialog.getExistingDirectory(self, "Select Base Image Folder")
        if path:
            self.base_edit.setText(path)

    def select_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.out_edit.setText(path)

    def apply_theme(self):
        # Qt automatically follows OS theme.
        # Manual override left here for future palette customization.
        pass

    def update_vendor_list(self):
        vendor_col = self.vendor_col.currentText()

        self.vendor_value.setEnabled(bool(vendor_col))
        self.vendor_value.clear()
        self.vendor_value.addItem("All Vendors")

        if self.df is None or not vendor_col:
            return

        vendors = (
            self.df[vendor_col]
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
        )

        self.vendor_value.addItems(sorted(vendors))

    def find_image_file(self, stem: str):
        """
        Look up stem in prebuilt index.
        Returns (Path, was_fallback)
        """
        stem = stem.lower()

        if stem not in self.image_index:
            return None, None

        candidates = self.image_index[stem]

        # Preferred match first
        for p in candidates:
            if p.suffix.lower() == self.preferred_ext:
                return p, False

        # Fallback
        fallback_files = sorted(
            candidates,
            key=lambda x: x.stat().st_size,
            reverse=True
        )

        if fallback_files:
            return fallback_files[0], True

        return None, None
        
    def update_fallback_mode(self, text):
        if text.startswith("Do nothing"):
            self.fallback_mode = "none"
        elif text.startswith("Copy"):
            self.fallback_mode = "copy"
        else:
            self.fallback_mode = "convert"

    def resolve_output_path(self, out_dir: Path, base_name: str, ext: str) -> Path:
        """
        Returns a non-overwriting output path by appending _1, _2, etc if needed.
        """
        base_name = sanitize_filename(base_name)
        candidate = out_dir / f"{base_name}{ext}"

        if not candidate.exists():
            return candidate

        i = 1
        while True:
            candidate = out_dir / f"{base_name}_{i}{ext}"
            if not candidate.exists():
                return candidate
            i += 1
    
    def save_settings(self):
        self.settings.setValue("remember", self.remember_checkbox.isChecked())

        if not self.remember_checkbox.isChecked():
            return

        self.settings.setValue("excel_path", self.excel_edit.text())
        self.settings.setValue("base_path", self.base_edit.text())
        self.settings.setValue("output_path", self.out_edit.text())

        self.settings.setValue("image_col", self.image_col.currentText())
        self.settings.setValue("newname_col", self.newname_col.currentText())
        self.settings.setValue("vendor_col", self.vendor_col.currentText())
        self.settings.setValue("vendor_value", self.vendor_value.currentText())

        self.settings.setValue("preferred_ext", self.preferred_ext)
        self.settings.setValue("fallback_mode", self.fallback_mode)

    def load_settings(self):
        remember = self.settings.value("remember", "true") == "true"
        self.remember_checkbox.setChecked(remember)

        if not remember:
            return

        excel_path = self.settings.value("excel_path", "")
        base_path = self.settings.value("base_path", "")
        output_path = self.settings.value("output_path", "")

        self.excel_edit.setText(excel_path)
        self.base_edit.setText(base_path)
        self.out_edit.setText(output_path)

        # Load Excel automatically if it exists
        if excel_path and Path(excel_path).exists():
            try:
                if excel_path and Path(excel_path).exists():
                    xls = pd.ExcelFile(excel_path)
                    self.df = pd.read_excel(excel_path, sheet_name=0)

            except Exception as e:
                logging.error(f"Failed to load saved Excel file: {e}")
                QMessageBox.warning(
                    self,
                    "Excel Load Failed",
                    "The previously loaded Excel file could not be opened.\n\n"
                    "It may be open in Excel or locked by OneDrive."
                )
                self.df = None
                return

            self.columns = list(self.df.columns)

            for box in (self.image_col, self.newname_col, self.vendor_col):
                box.clear()
                box.addItem("")
                box.addItems(self.columns)

            self.update_vendor_list()

            # Restore column mappings
            self.image_col.setCurrentText(self.settings.value("image_col", ""))
            self.newname_col.setCurrentText(self.settings.value("newname_col", ""))
            self.vendor_col.setCurrentText(self.settings.value("vendor_col", ""))
            self.update_vendor_list()
            self.vendor_value.setCurrentText(self.settings.value("vendor_value", ""))

        # Restore preferred extension
        preferred_ext = self.settings.value("preferred_ext", ".jpg")
        self.preferred_ext = preferred_ext
        self.preferred_type_box.setCurrentText(preferred_ext)

        # Restore fallback mode
        fallback_mode = self.settings.value("fallback_mode", "convert")
        self.fallback_mode = fallback_mode

        if fallback_mode == "none":
            self.fallback_box.setCurrentIndex(0)
        elif fallback_mode == "copy":
            self.fallback_box.setCurrentIndex(1)
        else:
            self.fallback_box.setCurrentIndex(2)

    def build_image_index(self):
        base_path = self.base_edit.text().strip()

        if not base_path:
            QMessageBox.warning(self, "Error", "Base image folder is required.")
            return False

        base = Path(base_path)

        if not base.exists():
            QMessageBox.warning(self, "Error", "Base image folder does not exist.")
            return False

        self.status_label.setText("Indexing images...")
        QApplication.processEvents()

        self.image_index = {}

        for file in base.rglob("*"):
            if file.is_file():
                stem = file.stem.lower()
                self.image_index.setdefault(stem, []).append(file)

        self.status_label.setText("Index ready")
        QApplication.processEvents()

        return True

    def run(self):
        self.convert_all_mode = False

        if self.df is None:
            QMessageBox.warning(self, "Error", "Please load an Excel file.")
            return

        img_col = self.image_col.currentText()
        rename_col = self.newname_col.currentText()
        rename_enabled = bool(rename_col and rename_col.strip())

        if not img_col:
            QMessageBox.warning(self, "Error", "Image Path Column is required.")
            return

        if not self.out_edit.text().strip():
            QMessageBox.warning(self, "Error", "Please select an Output Folder.")
            return

        if not self.build_image_index():
            return

        copied_original = 0
        copied_renamed = 0
        converted_original = 0
        converted_renamed = 0
        not_found_rows = []


        out_dir = Path(self.out_edit.text())
        out_dir.mkdir(parents=True, exist_ok=True)

        log_path = out_dir / "process_log.txt"

        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        logging.basicConfig(
            filename=log_path,
            filemode="w",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

        vendor_col = self.vendor_col.currentText()
        selected_vendor = self.vendor_value.currentText()


        rows = self.df

        if vendor_col and selected_vendor != "All Vendors":
            rows = rows[
                rows[vendor_col].astype(str).str.strip() == selected_vendor
            ]

        total = len(rows)

        logging.info("===== New Processing Run =====")
        logging.info(f"Total rows to process: {total}")
        logging.info(f"Preferred extension: {self.preferred_ext}")
        logging.info(f"Rename enabled: {rename_enabled}")
        logging.info(f"Fallback mode: {self.fallback_mode}")

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_text.setText("Starting...")
        QApplication.processEvents()

        for i, (_, row) in enumerate(rows.iterrows(), start=1):

            raw_path = row[img_col]

            if pd.isna(raw_path):
                logging.warning("Row has empty image path — marked not found")
                not_found_rows.append(row)
                continue

            filename = Path(str(raw_path)).name
            original_stem = Path(filename).stem.lower()

            # Determine output stem
            if rename_enabled:
                new_value = row[rename_col]
                if pd.notna(new_value) and str(new_value).strip():
                    output_stem = sanitize_filename(str(new_value).strip())
                else:
                    output_stem = original_stem
            else:
                output_stem = original_stem

            src_path, was_fallback = self.find_image_file(original_stem)

            if src_path:
                dest_path = self.resolve_output_path(
                    out_dir,
                    output_stem,
                    self.preferred_ext
                )

                if not was_fallback:
                    self.progress_text.setText(f"Copying: {dest_path.name}")
                    QApplication.processEvents()

                    logging.info(f"COPY preferred: {src_path} -> {dest_path}")
                    shutil.copy2(src_path, dest_path)

                    if rename_enabled:
                        copied_renamed += 1
                    else:
                        copied_original += 1


                else:
                    logging.info(f"Fallback found: {src_path}")

                    if self.fallback_mode in ("convert", "copy"):

                        # Only show dialog if preview is enabled AND we are not in convert-all mode
                        if (
                            self.fallback_mode == "convert"
                            and not self.convert_all_mode
                            and self.preview_toggle.currentText() == "Show preview before overwriting"
                        ):

                            dialog = ConversionDialog(
                                src_path,
                                dest_path,
                                rename_enabled,
                                self
                            )

                            result = dialog.exec()

                            # Cancel All
                            if result == -1:
                                logging.warning("User cancelled processing")
                                return

                            # Skip
                            elif result == 0:
                                logging.info("User skipped this image")
                                continue

                            # Convert All
                            elif result == 2:
                                logging.info("User selected Convert All")
                                self.convert_all_mode = True

                    if self.fallback_mode == "convert":
                        self.progress_text.setText(
                            f"Converting: {src_path.name} → {dest_path.name}"
                        )
                        QApplication.processEvents()

                        logging.info(f"CONVERT fallback: {src_path} -> {dest_path}")
                        convert_image(src_path, dest_path)

                        if rename_enabled:
                            converted_renamed += 1
                        else:
                            converted_original += 1

                    elif self.fallback_mode == "copy":
                        self.progress_text.setText(f"Copying (fallback): {dest_path.name}")
                        QApplication.processEvents()

                        logging.info(f"COPY fallback as-is: {src_path} -> {dest_path}")
                        shutil.copy2(src_path, dest_path)

                        if rename_enabled:
                            copied_renamed += 1
                        else:
                            copied_original += 1

                    else:
                        self.progress_text.setText(f"Not found: {filename}")
                        QApplication.processEvents()

                        logging.warning(f"NOT FOUND in index: {filename}")
                        not_found_rows.append(row)

            else:
                self.progress_text.setText(f"Not found: {filename}")
                QApplication.processEvents()

                logging.warning(f"NOT FOUND in index: {filename}")
                not_found_rows.append(row)
            self.progress_bar.setValue(i)
            QApplication.processEvents()

        self.progress_text.setText("Finished")
        QApplication.processEvents()
        self.status_label.setText("Finished")
        self.progress_bar.setValue(self.progress_bar.maximum())

        if not_found_rows:
            df_missing = pd.DataFrame(not_found_rows)
            missing_path = out_dir / "not_found_images.xlsx"
            df_missing.to_excel(missing_path, index=False)
        
            # Summary logging
            logging.info("===== Run Complete =====")
            logging.info(f"Total rows processed: {total}")
            logging.info(f"Copied (original name): {copied_original}")
            logging.info(f"Copied (renamed): {copied_renamed}")
            logging.info(f"Converted (original name): {converted_original}")
            logging.info(f"Converted (renamed): {converted_renamed}")
            logging.info(f"Not found: {len(not_found_rows)}")

            QMessageBox.information(
                self,
                "Completed",
                f"""
        Processing complete.

        Total rows processed: {total}

        Copied (original name): {copied_original}
        Copied (renamed): {copied_renamed}

        Converted (original name): {converted_original}
        Converted (renamed): {converted_renamed}

        Not found: {len(not_found_rows)}

        {'Missing rows exported to not_found_images.xlsx' if not_found_rows else ''}
        """.strip()
        )

    def closeEvent(self, event):
        self.save_settings()
        event.accept()

class ImageConflictDialog(QMessageBox):
    def __init__(self, src: Path, dest: Path):
        super().__init__()
        self.setWindowTitle("Image Conflict")

        pixmap = QPixmap(str(src))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio)

        text = (
            f"File already exists:\n\n"
            f"{dest.name}\n\n"
            f"Source:\n{src}\n\n"
            f"Resolution: {pixmap.width()} × {pixmap.height()}"
        )

        self.setText(text)
        if not pixmap.isNull():
            self.setIconPixmap(pixmap)

        self.addButton("Overwrite", QMessageBox.AcceptRole)
        self.addButton("Auto-Rename", QMessageBox.ActionRole)
        self.addButton("Skip", QMessageBox.RejectRole)
        self.load_settings()

class ConversionDialog(QDialog):
    def __init__(self, src: Path, dest: Path, rename_enabled: bool, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Image Conversion Required")
        self.setMinimumWidth(500)

        self.result_code = None

        layout = QVBoxLayout(self)

        # ---- IMAGE PREVIEW ----
        pixmap = QPixmap(str(src))
        image_label = QLabel()

        if not pixmap.isNull():
            pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("Preview not available")

        image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(image_label)

        # ---- IMAGE INFO ----
        convert_text = "Convert && Rename" if rename_enabled else "Convert"

        info_text = (
            f"<b>Source file found:</b><br>"
            f"{src.name}<br><br>"
            f"<b>Destination file:</b><br>"
            f"{dest.name}<br><br>"
            f"This image is not the preferred file type.<br>"
            f"It will be converted to <b>{dest.suffix}</b>."
        )

        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # ---- BUTTONS ----
        button_layout = QHBoxLayout()

        self.convert_btn = QPushButton(convert_text)
        self.convert_all_btn = QPushButton("Convert All")
        self.skip_btn = QPushButton("Skip")
        self.cancel_btn = QPushButton("Cancel All")

        button_layout.addWidget(self.convert_btn)
        button_layout.addWidget(self.convert_all_btn)
        button_layout.addWidget(self.skip_btn)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        # ---- BUTTON SIGNALS ----
        self.convert_btn.clicked.connect(self.convert_clicked)
        self.convert_all_btn.clicked.connect(self.convert_all_clicked)
        self.skip_btn.clicked.connect(self.skip_clicked)
        self.cancel_btn.clicked.connect(self.cancel_clicked)

    def convert_clicked(self):
        self.result_code = 1
        self.accept()

    def convert_all_clicked(self):
        self.result_code = 2
        self.accept()

    def skip_clicked(self):
        self.result_code = 0
        self.reject()

    def cancel_clicked(self):
        self.result_code = -1
        self.reject()

    def exec(self):
        super().exec()
        return self.result_code

# ---------------- RUN ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageTool()
    window.show()
    sys.exit(app.exec())

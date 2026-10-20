"""Persistent preferences and the engine status dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from anyfile.core.registry import Registry
from anyfile.i18n import _
from anyfile.models.conversion import Quality


class Settings:
    def __init__(self) -> None:
        self._s = QSettings("anyfile", "anyfile")

    @property
    def use_custom_dir(self) -> bool:
        return self._s.value("output/custom", False, type=bool)

    @use_custom_dir.setter
    def use_custom_dir(self, value: bool) -> None:
        self._s.setValue("output/custom", value)

    @property
    def custom_dir(self) -> Path | None:
        value = self._s.value("output/dir", "", type=str)
        return Path(value) if value else None

    @custom_dir.setter
    def custom_dir(self, value: Path | None) -> None:
        self._s.setValue("output/dir", str(value) if value else "")

    @property
    def quality(self) -> Quality:
        try:
            return Quality(self._s.value("output/quality", Quality.BALANCED.value, type=str))
        except ValueError:
            return Quality.BALANCED

    @quality.setter
    def quality(self, value: Quality) -> None:
        self._s.setValue("output/quality", value.value)

    @property
    def overwrite(self) -> bool:
        return self._s.value("output/overwrite", False, type=bool)

    @overwrite.setter
    def overwrite(self, value: bool) -> None:
        self._s.setValue("output/overwrite", value)


class EnginesDialog(QDialog):
    """Shows the available engines and how to install the missing ones."""

    def __init__(self, registry: Registry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle(_("Conversion engines"))
        self.resize(560, 320)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Engine"), _("Status"), _("Conversions")])
        self.tree.setRootIsDecorated(False)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.copy_button = QPushButton(_("Copy install command"))
        self.copy_button.clicked.connect(self._copy_command)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        recheck = buttons.addButton(_("Check again"), QDialogButtonBox.ButtonRole.ActionRole)
        recheck.clicked.connect(self._recheck)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addWidget(self.hint)
        layout.addWidget(self.copy_button)
        layout.addWidget(buttons)
        self._populate()

    def _install_command(self) -> str:
        packages = [s.package for s in self.registry.status() if not s.available]
        return f"sudo apt install {' '.join(packages)}" if packages else ""

    def _populate(self) -> None:
        self.tree.clear()
        for s in self.registry.status():
            state = ("✓ " + _("Installed") if s.available
                     else "✗ " + _("Missing {programs}").format(programs=", ".join(s.missing)))
            QTreeWidgetItem(self.tree, [s.label, state, str(s.conversions) if s.available else "—"])
        for col in range(3):
            self.tree.resizeColumnToContents(col)
        command = self._install_command()
        if command:
            self.hint.setText(_("To enable more conversions, install the missing engines:") + f"\n{command}")
        else:
            self.hint.setText(_("All the engines are installed."))
        self.copy_button.setVisible(bool(command))

    def _copy_command(self) -> None:
        QGuiApplication.clipboard().setText(self._install_command())

    def _recheck(self) -> None:
        self.registry.refresh()
        self._populate()

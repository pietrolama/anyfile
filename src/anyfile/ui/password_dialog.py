"""Passwords of protected PDFs: asked before the job starts, never stored."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from anyfile.core.executor import Executor
from anyfile.i18n import _
from anyfile.models.file_info import FileInfo


class PasswordDialog(QDialog):
    """One field to open a file (checked before closing), or two to choose a new password."""

    def __init__(self, parent: QWidget | None, title: str, text: str, *, new: bool = False,
                 check: Callable[[str], bool] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self._check = check

        intro = QLabel(text)
        intro.setWordWrap(True)
        self.field = self._password_field()
        self.repeat = self._password_field() if new else None
        self.error = QLabel()
        self.error.setStyleSheet("color: #da4453;")  # Breeze's negative text
        self.error.setWordWrap(True)
        self.error.hide()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(_("New password:") if new else _("Password:"), self.field)
        if self.repeat is not None:
            form.addRow(_("Repeat:"), self.repeat)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)
        for field in (self.field, self.repeat):
            if field is not None:
                field.textChanged.connect(self._update)
        self._update()

    def _password_field(self) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        show = field.addAction(QIcon.fromTheme("view-visible"), QLineEdit.ActionPosition.TrailingPosition)
        show.setCheckable(True)
        show.setToolTip(_("Show the password"))
        show.toggled.connect(lambda on: field.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        return field

    @property
    def password(self) -> str:
        return self.field.text()

    def _update(self) -> None:
        mismatch = self.repeat is not None and bool(self.repeat.text()) and self.repeat.text() != self.password
        self._show_error(_("The passwords do not match") if mismatch else "")
        complete = bool(self.password) and (self.repeat is None or self.repeat.text() == self.password)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(complete)

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def _accept(self) -> None:
        if self._check is not None and not self._check(self.password):
            self._show_error(_("Wrong password, try again"))
            self.field.selectAll()
            self.field.setFocus()
            return
        self.accept()


def ask_new_password(parent: QWidget | None, names: list[str]) -> str | None:
    text = (_("Choose the password for “{name}”.").format(name=names[0]) if len(names) == 1
            else _("Choose the password for the {n} files.").format(n=len(names)))
    text += " " + _("Without it the file cannot be recovered: keep it somewhere safe.")
    dialog = PasswordDialog(parent, _("Protect PDF"), text, new=True)
    return dialog.password if dialog.exec() == QDialog.DialogCode.Accepted else None


def ask_passwords(parent: QWidget | None, executor: Executor,
                  infos: Iterable[FileInfo]) -> dict[Path, str] | None:
    """Asks the password of each PDF that needs one to be opened. None if the user cancels."""
    passwords: dict[Path, str] = {}
    for info in infos:
        if not executor.needs_password(info):
            continue
        # The same password often protects a whole set of files: try the last one first.
        known = next((p for p in reversed(passwords.values()) if executor.password_ok(info.path, p)), None)
        if known is not None:
            passwords[info.path] = known
            continue
        dialog = PasswordDialog(
            parent, _("Protected PDF"),
            _("“{name}” is protected. Enter its password to open it.").format(name=info.name),
            check=lambda text, path=info.path: executor.password_ok(path, text))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        passwords[info.path] = dialog.password
    return passwords

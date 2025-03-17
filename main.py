import re
import os
import sys
from bisect import bisect_right
from typing import Tuple, List, Optional, cast
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMessageBox,
    QToolBar,
    QMenuBar,
    QHeaderView,
)
from PySide6.QtGui import (
    QAction,
    QIcon,
    QSyntaxHighlighter,
    QPalette,
    QTextCharFormat,
    QColor,
    QFont,
    QTextDocument,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtCore import (
    QRegularExpression,
    QRegularExpressionMatch,
    QRegularExpressionMatchIterator,
    QObject
)


class Token:
    def __init__(
        self,
        token_type: str,
        value: str,
        line: int,
        start_column: int,
        end_column: int,
    ):
        self.token_type = token_type
        self.value = value
        self.line = line
        self.start_column = start_column
        self.end_column = end_column


class LexerError:
    def __init__(self, line: int, column: int, message: str):
        self.line = line
        self.column = column
        self.message = message


class Lexer:
    TOKEN_REGEX = [
        (r"constexpr\b", "CONSTEXPR"),
        (r"const\b", "CONST"),
        (r"int\b", "INT"),
        (r"\s+", "SPACE"),  # Объединяем повторяющиеся пробелы
        (r"=", "ASSIGN"),
        (r"\+", "PLUS"),
        (r"-", "MINUS"),
        (r";", "SEMICOLON"),
        (r"[a-zA-Z_][a-zA-Z0-9_]*", "IDENTIFIER"),
        (r"\d+", "NUMBER"),
    ]

    def __init__(self, input_text: str):
        self.input_text = input_text
        self.newline_positions = [
            i for i, c in enumerate(input_text) if c == "\n"
        ]
        self.tokens: List[Token] = []
        self.errors: List[LexerError] = []
        self.pos = 0
        self.length = len(input_text)

    def get_line_column(self, line_num: int, pos: int) -> int:
        if line_num > 1:
            last_nl_pos = self.newline_positions[line_num - 2]
            column = pos - last_nl_pos
        else:
            column = pos + 1
        return column

    def lex(self) -> Tuple[List[Token], List[LexerError]]:
        while self.pos < self.length:
            line_num = bisect_right(self.newline_positions, self.pos) + 1
            column = self.get_line_column(line_num, self.pos)
            matched = False
            for pattern, token_type in self.TOKEN_REGEX:
                regex = re.compile(pattern)
                match = regex.match(self.input_text, self.pos)
                if match:
                    value = match.group(0)
                    if token_type in ("CONST", "CONSTEXPR", "INT"):
                        next_pos = match.end()
                        if (
                            next_pos < self.length
                            and self.input_text[next_pos].isalnum()
                        ):
                            continue
                    line_num = bisect_right(
                        self.newline_positions, self.pos
                    ) + 1
                    start_column = self.get_line_column(line_num, self.pos)
                    end_pos = match.end()
                    end_column = self.get_line_column(line_num, end_pos - 1)
                    self.tokens.append(
                        Token(
                            token_type,
                            value,
                            line_num,
                            start_column,
                            end_column,
                        )
                    )
                    self.pos = match.end()
                    matched = True
                    break
            if not matched:
                char = self.input_text[self.pos]
                if char in {"\t", "\r"}:
                    self.errors.append(
                        LexerError(
                            line_num,
                            column,
                            f"Недопустимый пробел: {repr(char)}",
                        )
                    )
                    # Добавляем недопустимые символы как токены с типом ERROR
                    self.tokens.append(
                        Token(
                            "ERROR",
                            char,
                            line_num,
                            column,
                            column + 1,
                        )
                    )
                elif char == "\n":
                    pass
                else:
                    self.errors.append(
                        LexerError(
                            line_num,
                            column,
                            f"Недопустимый символ: {repr(char)}",
                        )
                    )
                    # Добавляем недопустимые символы как токены с типом ERROR
                    self.tokens.append(
                        Token(
                            "ERROR",
                            char,
                            line_num,
                            column,
                            column + 1,
                        )
                    )
                self.pos += 1
        return self.tokens, self.errors

class ThemeManager:
    _COLOR_SPEC = {
        "background": (18, 18, 18),
        "foreground": (240, 240, 240),
        "base": (30, 30, 30),
        "alternate_base": (45, 45, 45),

        "accent": (100, 149, 237),
        "accent_light": (135, 206, 250),
        "highlight": (70, 130, 180),

        "button": (50, 50, 50),
        "button_hover": (70, 70, 70),
        "button_pressed": (90, 90, 90),

        "scroll_handle": (90, 90, 90),
        "border": (60, 60, 60),

        "menu_background": (40, 40, 40),
        "menu_foreground": (240, 240, 240),
        "menu_hover": (70, 130, 180),
        "menu_selected": (100, 149, 237),

        "error": (220, 50, 47),
        "warning": (203, 203, 65),
        "success": (80, 200, 120)
    }

    _PALETTE = {k: QColor(*v) for k, v in _COLOR_SPEC.items()}

    _PALETTE_MAP = [
        (QPalette.ColorRole.Window, "background"),
        (QPalette.ColorRole.WindowText, "foreground"),
        (QPalette.ColorRole.Base, "base"),
        (QPalette.ColorRole.AlternateBase, "alternate_base"),
        (QPalette.ColorRole.ToolTipBase, "accent"),
        (QPalette.ColorRole.ToolTipText, "foreground"),
        (QPalette.ColorRole.Text, "foreground"),
        (QPalette.ColorRole.Button, "button"),
        (QPalette.ColorRole.ButtonText, "foreground"),
        (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "base"),
    ]

    _BASE_STYLE = """
        QMainWindow {{
            background-color: {background};
            color: {foreground};
            font-family: 'Segoe UI', sans-serif;
            padding: 6px;
        }}
        QTextEdit {{
            background-color: {base};
            color: {foreground};
            border: 1px solid {border};
            selection-background-color: {accent};
            selection-color: {base};
            font-family: 'Fira Code', 'Consolas', monospace;
            margin: 8px 8px 0 8px;
            padding: 12px;
        }}
        QTextEdit#editor {{
            background-color: {base};
            color: {foreground};
            selection-background-color: {accent};
            selection-color: {base};
        }}
        QTextEdit#editor:focus {{
            border-color: {accent_light};
            outline: none;
        }}
        QTableWidget {{
            background-color: {alternate_base};
            border-color: {accent_light};
            color: {foreground};
            font-family: 'Fira Code', 'Consolas', monospace;
            gridline-color: {border};
            margin: 8px 8px 0 8px;
            outline: none;
        }}
        QHeaderView {{
            background-color: {background};
            color: {foreground};
            font-family: 'Fira Code', 'Consolas', monospace;
            outline: none;
        }}
    """

    _COMPONENT_STYLES = {
        "ToolBar": """
            QToolBar {{
                background-color: {base};
                border-bottom: 1px solid {border};
                spacing: 4px;
                padding: 4px;
            }}
            QToolBar::separator {{
                background: {border};
                width: 1px;
                margin: 0 4px;
            }}
        """,

        "ScrollBars": """
            QScrollBar:vertical {{
                background: {base};
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle};
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                background: none;
            }}
        """,

        "MenuSystem": """
            QMenuBar {{
                background-color: {base};
                color: {foreground};
                padding: 4px 8px;
                border-bottom: 1px solid {border};
            }}
            QMenu {{
                background-color: {menu_background};
                color: {menu_foreground};
                border: 1px solid {border};
                padding: 4px 0;
            }}
            QMenu::icon {{
                margin-left: 8px;
            }}
            QMenu::item {{
                padding: 4px 8px;
                margin: 2px 4px;
                min-width: 160px;
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
            }}
            QMenu::item:pressed {{
                background-color: {menu_selected};
            }}
        """,

        "Buttons": """
            QToolButton {{
                background-color: {button};
                border: 1px solid {border};
                padding: 4px 8px;
                margin: 2px;
            }}
            QToolButton:hover {{
                background-color: {button_hover};
            }}
            QToolButton:pressed {{
                background-color: {button_pressed};
            }}
            QToolButton:disabled {{
                color: {scroll_handle};
                background-color: {alternate_base};
            }}
        """
    }

    def apply_theme(self, window: QMainWindow) -> None:
        palette = QPalette()
        for role, color_key in self._PALETTE_MAP:
            palette.setColor(role, self._PALETTE[color_key])
        window.setPalette(palette)
        window.setStyleSheet(self._build_stylesheet())

    def _build_stylesheet(self) -> str:
        color_map = {k: v.name() for k, v in self._PALETTE.items()}
        styles = [
            self._BASE_STYLE.format(**color_map),
            *[style.format(**color_map) for style in self._COMPONENT_STYLES.values()]
        ]
        return "\n".join(styles).replace("    ", "")


class SyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.highlighting_rules: List[
            Tuple[QRegularExpression, QTextCharFormat]
        ] = []
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor(255, 165, 0))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "int",
            "const",
            "constexpr",
        ]
        for word in keywords:
            pattern = QRegularExpression(
                r"\b" + QRegularExpression.escape(word) + r"\b"
            )
            self.highlighting_rules.append((pattern, keyword_format))

    def highlightBlock(self, text: str):
        for pattern, fmt in self.highlighting_rules:
            match_iterator: QRegularExpressionMatchIterator = (
                pattern.globalMatch(text)
            )
            while match_iterator.hasNext():
                match: QRegularExpressionMatch = match_iterator.next()
                self.setFormat(
                    match.capturedStart(), match.capturedLength(), fmt
                )


class MainWindow(QMainWindow):
    new_action: QAction
    open_action: QAction
    save_action: QAction
    save_as_action: QAction
    exit_action: QAction
    undo_action: QAction
    redo_action: QAction
    cut_action: QAction
    copy_action: QAction
    paste_action: QAction
    delete_action: QAction
    select_all_action: QAction
    run_parser_action: QAction
    help_action: QAction
    about_action: QAction

    def closeEvent(self, event):
            if self._is_modified:
                reply = QMessageBox.question(
                    self,
                    "Несохраненные изменения",
                    "У вас есть несохраненные изменения. Хотите сохранить файл перед закрытием?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save
                )

                if reply == QMessageBox.StandardButton.Save:
                    if not self.save_document():
                        event.ignore()
                        return
                elif reply == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return

            event.accept()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Компилятор")
        self.setGeometry(100, 100, 800, 600)
        self._file_path: Optional[str] = None
        self._is_modified = False
        self._init_ui()
        self._theme_manager = ThemeManager()
        self._theme_manager.apply_theme(self)
        self._create_actions()
        self._setup_toolbar()
        self.menu_manager = MenuManager(self)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.input_edit = QTextEdit()
        self.input_edit.setObjectName("editor")
        self.highlighter = SyntaxHighlighter(
            cast(QTextDocument, self.input_edit.document())
        )

        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(5)
        self.table_widget.setHorizontalHeaderLabels(
            [
                "Тип",
                "Значение",
                "Строка",
                "Позиция (нач)",
                "Позиция (кон)",
            ]
        )
        self.table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        layout.addWidget(self.input_edit)
        layout.addWidget(self.table_widget)

        self.input_edit.textChanged.connect(self._handle_text_changed)

    def _create_actions(self):
        self.new_action = QAction("Создать", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.setIcon(QIcon.fromTheme("document-new"))
        self.new_action.triggered.connect(self.new_document)

        self.open_action = QAction("Открыть", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setIcon(QIcon.fromTheme("document-open"))
        self.open_action.triggered.connect(self.open_document)

        self.save_action = QAction("Сохранить", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setIcon(QIcon.fromTheme("document-save"))
        self.save_action.triggered.connect(self.save_document)

        self.save_as_action = QAction("Сохранить как", self)
        self.save_as_action.triggered.connect(self.save_document_as)
        self.save_as_action.setIcon(QIcon.fromTheme("document-save-as"))

        self.exit_action = QAction("Выход", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.setIcon(QIcon.fromTheme("application-exit"))
        self.exit_action.triggered.connect(self.close)

        self.undo_action = QAction("Отменить", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(QIcon.fromTheme("edit-undo"))
        self.undo_action.triggered.connect(self.undo)

        self.redo_action = QAction("Повторить", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(QIcon.fromTheme("edit-redo"))
        self.redo_action.triggered.connect(self.redo)

        self.cut_action = QAction("Вырезать", self)
        self.cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        self.cut_action.setIcon(QIcon.fromTheme("edit-cut"))
        self.cut_action.triggered.connect(self.cut)

        self.copy_action = QAction("Копировать", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.setIcon(QIcon.fromTheme("edit-copy"))
        self.copy_action.triggered.connect(self.copy)

        self.paste_action = QAction("Вставить", self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.setIcon(QIcon.fromTheme("edit-paste"))
        self.paste_action.triggered.connect(self.paste)

        self.delete_action = QAction("Удалить", self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.setIcon(QIcon.fromTheme("edit-delete"))
        self.delete_action.triggered.connect(self.delete)

        self.select_all_action = QAction("Выделить все", self)
        self.select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.select_all_action.setIcon(QIcon.fromTheme("edit-select-all"))
        self.select_all_action.triggered.connect(self.select_all)

        self.run_parser_action = QAction("Запустить анализатор", self)
        self.run_parser_action.setShortcut(QKeySequence("F5"))
        self.run_parser_action.setIcon(QIcon.fromTheme("system-run"))
        self.run_parser_action.triggered.connect(self.run_parser)

        self.help_action = QAction("Справка", self)
        self.help_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        self.help_action.setIcon(QIcon.fromTheme("help-contents"))
        self.help_action.triggered.connect(self.show_help)

        self.about_action = QAction("О программе", self)
        self.about_action.triggered.connect(self.show_about)
        self.about_action.setIcon(QIcon.fromTheme("help-about"))

    def _setup_toolbar(self):
        self.toolbar_manager = ToolbarManager(self)
        self.toolbar_manager.add_action(self.new_action)
        self.toolbar_manager.add_action(self.open_action)
        self.toolbar_manager.add_action(self.save_action)
        self.toolbar_manager.add_action(self.undo_action)
        self.toolbar_manager.add_action(self.redo_action)
        self.toolbar_manager.add_action(self.cut_action)
        self.toolbar_manager.add_action(self.copy_action)
        self.toolbar_manager.add_action(self.paste_action)
        self.toolbar_manager.add_action(self.run_parser_action)
        self.toolbar_manager.add_action(self.help_action)

    def _handle_text_changed(self):
        if not self._is_modified:
            self._is_modified = True
            self._update_title()

    def _update_title(self):
        base_name = (
            os.path.basename(
                self._file_path) if self._file_path else "Новый файл"
        )
        self.setWindowTitle(
            f"{base_name}{'*' if self._is_modified else ''} - Компилятор"
        )

    def new_document(self):
        self.input_edit.clear()
        self._file_path = None
        self._is_modified = False
        self._update_title()

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл", "", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.input_edit.setPlainText(content)
                self._file_path = path
                self._is_modified = False
                self._update_title()
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Ошибка открытия файла:\n{str(e)}"
                )

    def save_document(self) -> bool:
        if self._file_path:
            return self._save_to_file(self._file_path)
        return self.save_document_as()

    def save_document_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как", "", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            if self._save_to_file(path):
                self._file_path = path
                self._is_modified = False
                self._update_title()
                return True
        return False

    def _save_to_file(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.input_edit.toPlainText())
            return True
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка", f"Ошибка сохранения файла:\n{str(e)}"
            )
            return False

    def run_parser(self):
        input_text = self.input_edit.toPlainText()
        lexer = Lexer(input_text)
        tokens, errors = lexer.lex()

        self.table_widget.setRowCount(len(tokens))
        for row, token in enumerate(tokens):
            self.table_widget.setItem(
                row, 0, QTableWidgetItem(token.token_type))
            self.table_widget.setItem(row, 1, QTableWidgetItem(token.value))
            self.table_widget.setItem(
                row, 2, QTableWidgetItem(str(token.line)))
            self.table_widget.setItem(
                row, 3, QTableWidgetItem(str(token.start_column)))
            self.table_widget.setItem(
                row, 4, QTableWidgetItem(str(token.end_column)))

        if errors:
            error_messages = "\n".join(
                f"[Строка {e.line}, Позиция {e.column}] {e.message}"
                for e in errors
            )
            QMessageBox.warning(self, "Ошибки", error_messages)

    def undo(self):
        self.input_edit.undo()

    def redo(self):
        self.input_edit.redo()

    def cut(self):
        self.input_edit.cut()

    def copy(self):
        self.input_edit.copy()

    def paste(self):
        self.input_edit.paste()

    def delete(self):
        cursor: QTextCursor = self.input_edit.textCursor()
        cursor.removeSelectedText()

    def select_all(self):
        self.input_edit.selectAll()

    def show_help(self):
        QMessageBox.information(
            self,
            "Справка",
            "Редактор для анализа объявления констант в C/C++\n\n"
            "Используйте меню 'Пуск' для запуска лексического анализатора\n"
            "Поддерживаются ключевые слова: const, constexpr, int",
            QMessageBox.StandardButton.Ok,
        )

    def show_about(self):
        QMessageBox.about(
            self,
            "О программе",
            "Текстовый редактор для анализа объявления констант\n"
            "Автор: Студентка 3 курса группы АВТ-214, Трифонова София\n"
            "Преподаватель: Антоньянц Е.Н.\n"
            "Дисциплина: Теория формальных языков и компиляторов",
        )


class ToolbarManager:
    def __init__(self, parent: QMainWindow):
        self.parent = parent
        self.toolbar = QToolBar("Основная панель")
        parent.addToolBar(self.toolbar)

    def add_action(self, action: QAction):
        self.toolbar.addAction(action)


class MenuManager:
    def __init__(self, parent: QMainWindow):
        self.parent = parent
        self.menu_bar = QMenuBar()
        parent.setMenuBar(self.menu_bar)
        self._setup_menus()

    def _setup_menus(self):
        self._create_file_menu()
        self._create_edit_menu()
        self._create_run_menu()
        self._create_help_menu()

    def _create_file_menu(self):
        menu = self.menu_bar.addMenu("Файл")
        menu.addAction(self.parent.new_action)
        menu.addAction(self.parent.open_action)
        menu.addAction(self.parent.save_action)
        menu.addAction(self.parent.save_as_action)
        menu.addSeparator()
        menu.addAction(self.parent.exit_action)

    def _create_edit_menu(self):
        menu = self.menu_bar.addMenu("Правка")
        menu.addAction(self.parent.undo_action)
        menu.addAction(self.parent.redo_action)
        menu.addSeparator()
        menu.addAction(self.parent.cut_action)
        menu.addAction(self.parent.copy_action)
        menu.addAction(self.parent.paste_action)
        menu.addAction(self.parent.delete_action)
        menu.addSeparator()
        menu.addAction(self.parent.select_all_action)

    def _create_run_menu(self):
        menu = self.menu_bar.addMenu("Пуск")
        menu.addAction(self.parent.run_parser_action)

    def _create_help_menu(self):
        menu = self.menu_bar.addMenu("Справка")
        menu.addAction(self.parent.help_action)
        menu.addAction(self.parent.about_action)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

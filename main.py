import os
import re
import sys
import bisect
from queue import PriorityQueue
from typing import (
    List,
    Tuple,
    Callable,
)
from PySide6.QtCore import (
    Qt, QObject,
    QFileSystemWatcher, Signal, QRegularExpression,
)
from PySide6.QtGui import (
    QFont, QIcon, QColor, QKeySequence,
    QTextCharFormat, QAction, QShortcut,
    QSyntaxHighlighter,
)
from PySide6.QtWidgets import (
    QMenu, QWidget, QFileDialog, QHeaderView,
    QMainWindow, QMessageBox, QMenuBar, QToolBar, QTextEdit,
    QTabWidget, QVBoxLayout, QApplication, QTableWidget,
    QPlainTextEdit, QTableWidgetItem,

)


class LexerError:
    def __init__(self, line: int, column: int, message: str):
        self.line = line
        self.column = column
        self.message = message

    def __repr__(self):
        return f"LexerError({self.line}, {self.column}, {self.message})"


class Lexeme:
    def __init__(self, type: str, value: str, line: int, column: int):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Lexeme({self.type}, {self.value}, {self.line}, {self.column})"


class Branch:
    def __init__(self, tokens: List[Lexeme], index: int, current_state: str, edit_count: int, changes: List[tuple]
                 ):
        self.tokens = tokens
        self.index = index
        self.current_state = current_state
        self.edit_count = edit_count
        self.changes = changes

    def __lt__(self, other):
        return self.edit_count < other.edit_count


class Output:
    TOKEN_REGEX = [
        (r'\bconst\b', 'CONST'),
        (r'\bconstexpr\b', 'CONSTEXPR'),
        (r'\bint\b', 'INT'),
        (r'=', 'EQUAL'),
        (r'\+', 'PLUS'),
        (r'-', 'MINUS'),
        (r';', 'SEMICOLON'),
        (r'[a-zA-Z][a-zA-Z0-9]*', 'VARIABLE'),
        (r'\d+', 'VALUE'),
        (r'[^\s]', 'INVALID'),
    ]

    def __init__(self, input_text: str):
        self.input_text = input_text
        self.newline_positions = [
            i for i, c in enumerate(input_text) if c == '\n'
        ]
        self.tokens = []
        self.errors = []
        self.pos = 0
        self.length = len(input_text)

    def get_line_column(
        self,
        pos: int
    ) -> Tuple[int, int]:
        line_num = bisect.bisect_right(
            self.newline_positions,
            pos
        ) + 1
        if line_num > 1:
            column = pos - self.newline_positions[line_num-2]
        else:
            column = pos + 1
        return line_num, column

    def tokenize(self) -> Tuple[List[Lexeme], List[LexerError]]:
        while self.pos < self.length:
            while (
                self.pos < self.length
                and self.input_text[self.pos].isspace()
            ):
                self.pos += 1
            if self.pos >= self.length:
                break

            line, column = self.get_line_column(self.pos)
            matched = False
            for pattern, token_type in self.TOKEN_REGEX:
                regex = re.compile(pattern)
                match = regex.match(self.input_text, self.pos)
                if match:
                    value = match.group(0)
                    if token_type in ('CONST', 'CONSTEXPR', 'INT'):
                        next_pos = match.end()
                        if (
                            next_pos < self.length
                            and self.input_text[next_pos].isalnum()
                        ):
                            continue
                    self.tokens.append(
                        Lexeme(
                            token_type,
                            value,
                            line,
                            column
                        )
                    )
                    self.pos = match.end()
                    matched = True
                    break
            if not matched:
                char = self.input_text[self.pos]
                self.errors.append(
                    LexerError(
                        line,
                        column,
                        f"Неожиданный символ: {repr(char)}"
                    )
                )
                self.pos += 1
        return self.tokens, self.errors


class Lexer:
    MAX_EDIT_COUNT = 15

    REGULAR_LEXEME = [
        (r'const\b', 'CONST'),
        (r'constexpr\b', 'CONSTEXPR'),
        (r'int\b', 'INT'),
        (r'=', 'EQUAL'),
        (r'\+', 'PLUS'),
        (r'-', 'MINUS'),
        (r';', 'SEMICOLON'),
        (r'[a-zA-Z_][^ \t\n\r:;=+]*', 'VARIABLE'),
        (r'\d[^ \t\n\r:;=+]*', 'VALUE'),
        (r'[^\s]', 'INVALID'),
    ]

    DEFAULT_LEXEME_VALUES = {
        'CONST': 'const', 'CONSTEXPR': 'constexpr', 'INT': 'int',
        'EQUAL': '=', 'VARIABLE': 'имя_переменной',
        'PLUS': '+', 'MINUS': '-', 'SEMICOLON': ';',
        'VALUE': 'число'
    }

    TRANSITIONS = {
        'START': {'CONST': 'DATA_TYPE', 'CONSTEXPR': 'DATA_TYPE'},
        'DATA_TYPE': {'INT': 'VARIABLE'},
        'VARIABLE': {'VARIABLE': 'EQUAL'},
        'EQUAL': {'EQUAL': 'VALUE'},
        'VALUE': {
            'VALUE': 'SEMICOLON',
            'MINUS': 'WHOLENUMBER',
            'PLUS': 'WHOLENUMBER'
        },
        'WHOLENUMBER': {'VALUE': 'SEMICOLON'},
        'SEMICOLON': {'SEMICOLON': 'END'},
        'END': {}
    }

    KEYWORDS = {'const', 'constexpr', 'int'}
    KEYWORD_TO_TOKEN = {'const': 'CONST',
                        'constexpr': 'CONSTEXPR', 'int': 'INT'}
    KEYWORD_TOLERANCE = 2

    def __init__(self, input_text: str):
        self.input_text = input_text
        self.newline_positions = [
            i for i, c in enumerate(input_text) if c == '\n']
        self.tokens = []
        self.errors = []
        self.pos = 0
        self.length = len(input_text)

    def get_line_column(self, pos: int) -> Tuple[int, int]:
        line_num = bisect.bisect_right(self.newline_positions, pos) + 1
        if line_num > 1:
            column = pos - self.newline_positions[line_num - 2]
        else:
            column = pos + 1
        return line_num, column

    def create_token(self, token_type: str, reference_token: 'Lexeme', insert_after: bool = False) -> 'Lexeme':
        value = self.DEFAULT_LEXEME_VALUES.get(token_type, token_type)
        if reference_token:
            if insert_after:
                new_pos = reference_token.column + len(reference_token.value)
                return Lexeme(token_type, value, reference_token.line, new_pos)
            return Lexeme(token_type, value, reference_token.line, reference_token.column)

    def _is_keyword_candidate(self, value: str) -> bool:
        value_lower = value.lower()
        for keyword in self.KEYWORDS:
            if len(value) < len(keyword) - self.KEYWORD_TOLERANCE:
                continue
            if self._fuzzy_match(value_lower, keyword):
                return True
        return False

    def _fuzzy_match(self, s: str, target: str) -> bool:
        if not s or not target:
            return False
        if s[0] != target[0]:
            return False
        max_length = max(len(s), len(target))
        matches = 0
        s_idx, t_idx = 0, 0
        while s_idx < len(s) and t_idx < len(target):
            if s[s_idx] == target[t_idx]:
                matches += 1
                s_idx += 1
                t_idx += 1
            else:
                t_idx += 1
        return matches / len(target) >= 0.6

    def _correct_keyword(self, value: str) -> str:
        value_lower = value.lower()
        for keyword in self.KEYWORDS:
            if self._fuzzy_match(value_lower, keyword):
                return keyword
        return ""

    def strtok(self) -> Tuple[List[Lexeme], List[LexerError]]:
        while self.pos < self.length:
            while self.pos < self.length and self.input_text[self.pos].isspace():
                self.pos += 1
            if self.pos >= self.length:
                break

            line, column = self.get_line_column(self.pos)
            matched = False

            for pattern, token_type in self.REGULAR_LEXEME:
                regex = re.compile(pattern)
                match = regex.match(self.input_text, self.pos)
                if match:
                    value = match.group(0)
                    self.pos = match.end()

                    if token_type == 'IDENTIFIER':
                        original = value
                        valid_chars = []
                        has_errors = False

                        if not (original[0].isalpha() or original[0] == '_'):
                            self.errors.append(LexerError(
                                line, column,
                                f"Символ идентификатора {
                                    original[0]} не должен быть первым"
                            ))
                            has_errors = True
                        else:
                            valid_chars.append(original[0])

                        for i in range(1, len(original)):
                            c = original[i]
                            if c.isalnum() or c == '_':
                                valid_chars.append(c)
                            else:
                                has_errors = True

                        valid_value = ''.join(valid_chars) or '_'
                        if valid_value in self.KEYWORDS:
                            keyword_token_type = self.KEYWORD_TO_TOKEN[valid_value]
                            self.tokens.append(
                                Lexeme(keyword_token_type, valid_value, line, column))
                            if has_errors:
                                self.errors.append(LexerError(
                                    line, column,
                                    f"Замените '{original}' на '{
                                        valid_value}'"
                                ))
                        else:
                            self.tokens.append(
                                Lexeme('IDENTIFIER', valid_value, line, column))
                            if has_errors:
                                self.errors.append(LexerError(
                                    line, column,
                                    f"Замените имя переменной: '{
                                        original}' -> '{valid_value}'"
                                ))
                        matched = True
                        break

                    elif token_type == 'NUMBER':
                        original = value
                        cleaned = []
                        has_errors = False
                        for i, c in enumerate(original):
                            if c.isdigit():
                                cleaned.append(c)
                            else:
                                has_errors = True

                        valid_value = ''.join(cleaned) or '0'
                        self.tokens.append(
                            Lexeme('NUMBER', valid_value, line, column))
                        if has_errors:
                            self.errors.append(LexerError(
                                line, column,
                                f"Замените число: '{
                                    original}' -> '{valid_value}'"
                            ))
                        matched = True
                        break

                    else:
                        self.tokens.append(
                            Lexeme(token_type, value, line, column))
                        matched = True
                        break

            if not matched:
                char = self.input_text[self.pos]
                self.errors.append(LexerError(
                    line, column, f"Невалидный символ: {repr(char)}"))
                self.pos += 1

        return self.tokens, self.errors

    def validate_tokens(self) -> Tuple[List[Lexeme], List[LexerError]]:
        queue = PriorityQueue()
        queue.put((
            0,
            Branch(
                self.tokens.copy(), 0, 'START', 0, []
            )
        ))
        best = None

        while not queue.empty():
            _, branch = queue.get()

            if best and best.edit_count <= self.MAX_EDIT_COUNT:
                break

            if branch.index >= len(branch.tokens):
                if branch.current_state in ('END', 'START'):
                    if not best or branch.edit_count < best.edit_count:
                        best = branch
                else:
                    self._process_transitions(
                        queue,
                        branch
                    )
            else:
                current_token = branch.tokens[branch.index]
                allowed = self.TRANSITIONS.get(
                    branch.current_state,
                    {}
                ).keys()

                if current_token.type in allowed:
                    self._handle_valid_transition(
                        queue,
                        branch
                    )
                else:
                    self._generate_repair_branches(
                        queue,
                        branch,
                        current_token,
                        allowed
                    )

        return self._finalize_validation(best)

    def _process_transitions(self, queue, branch):
        current_state = branch.current_state
        allowed = self.TRANSITIONS.get(
            current_state,
            {}
        ).keys()

        for insert_type in allowed:
            line, column = 1, 1
            if branch.tokens:
                last_token = branch.tokens[-1]
                line = last_token.line
                column = last_token.column + len(last_token.value)

            insert_token = Lexeme(
                insert_type,
                self.DEFAULT_LEXEME_VALUES.get(
                    insert_type,
                    insert_type
                ),
                line,
                column
            )
            new_tokens = branch.tokens.copy()
            new_tokens.append(insert_token)
            new_changes = branch.changes.copy()
            new_changes.append(('insert', len(new_tokens)-1, insert_token))
            next_state = self.TRANSITIONS[current_state][insert_type]

            if branch.edit_count + 1 <= self.MAX_EDIT_COUNT:
                new_branch = Branch(
                    tokens=new_tokens,
                    index=len(new_tokens),
                    current_state=next_state,
                    edit_count=branch.edit_count + 1,
                    changes=new_changes
                )
                queue.put((
                    new_branch.edit_count,
                    new_branch
                ))

    def _handle_valid_transition(self, queue, branch):
        current_token = branch.tokens[branch.index]
        next_state = self.TRANSITIONS[branch.current_state][current_token.type]

        new_edit_count = branch.edit_count if next_state != 'END' else 0
        new_state = 'START' if next_state == 'END' else next_state

        new_branch = Branch(
            tokens=branch.tokens,
            index=branch.index + 1,
            current_state=new_state,
            edit_count=new_edit_count,
            changes=branch.changes.copy()
        )
        queue.put((new_branch.edit_count, new_branch))

    def _generate_repair_branches(
        self,
        queue,
        branch,
        current_token,
        allowed
    ):
        self._generate_delete_branch(queue, branch, current_token)
        self._generate_replace_branches(queue, branch, current_token, allowed)
        self._generate_insert_branches(queue, branch, current_token, allowed)

    def _generate_delete_branch(self, queue, branch, current_token):
        new_tokens = branch.tokens.copy()
        del new_tokens[branch.index]
        new_changes = branch.changes.copy()
        new_changes.append((
            'delete',
            branch.index,
            current_token
        ))
        if branch.edit_count + 1 <= self.MAX_EDIT_COUNT:
            new_branch = Branch(
                tokens=new_tokens,
                index=branch.index,
                current_state=branch.current_state,
                edit_count=branch.edit_count + 1,
                changes=new_changes
            )
            queue.put((
                new_branch.edit_count,
                new_branch
            ))

    def _generate_replace_branches(
        self,
        queue,
        branch,
        current_token,
        allowed
    ):
        current_state = branch.current_state
        for replace_type in allowed:
            new_token = self.create_token(replace_type, current_token)
            new_tokens = branch.tokens.copy()
            new_tokens[branch.index] = new_token
            new_changes = branch.changes.copy()
            new_changes.append((
                'replace',
                branch.index,
                current_token,
                new_token
            ))
            next_state = self.TRANSITIONS[current_state][replace_type]
            if branch.edit_count + 1 <= self.MAX_EDIT_COUNT:
                new_branch = Branch(
                    tokens=new_tokens,
                    index=branch.index + 1,
                    current_state=next_state,
                    edit_count=branch.edit_count + 1,
                    changes=new_changes
                )
                queue.put((
                    new_branch.edit_count,
                    new_branch
                ))

    def _generate_insert_branches(
        self,
        queue,
        branch,
        current_token,
        allowed
    ):
        current_state = branch.current_state
        for insert_type in allowed:
            insert_token = self.create_token(
                insert_type,
                current_token,
                False
            )
            new_tokens = branch.tokens.copy()
            new_tokens.insert(branch.index, insert_token)
            new_changes = branch.changes.copy()
            new_changes.append(('insert', branch.index, insert_token))
            next_state = self.TRANSITIONS[current_state][insert_type]
            if branch.edit_count + 1 <= self.MAX_EDIT_COUNT:
                new_branch = Branch(
                    tokens=new_tokens,
                    index=branch.index + 1,
                    current_state=next_state,
                    edit_count=branch.edit_count + 1,
                    changes=new_changes
                )
                queue.put((new_branch.edit_count, new_branch))

    def _finalize_validation(self, best):
        if best:
            self.tokens = best.tokens
            errors = self._generate_errors_from_changes(best.changes)
            return self.tokens, errors
        return self.tokens, self.errors + []

    def _generate_errors_from_changes(
        self,
        changes: List[tuple]
    ) -> List[LexerError]:
        errors = []
        for change in changes:
            action = change[0]
            if action == 'delete':
                *_, token = change
                errors.append(
                    LexerError(
                        token.line,
                        token.column,
                        f"Удалить недопустимый символ: '{token.value}'"
                    )
                )
            elif action == 'replace':
                *_, old_token, new_token = change
                errors.append(
                    LexerError(
                        old_token.line,
                        old_token.column,
                        f"Заменить лексему '{old_token.value}' на '{
                            new_token.value}'"
                    )
                )
            elif action == 'insert':
                *_, token = change
                errors.append(
                    LexerError(
                        token.line,
                        token.column,
                        f"Вставить лексему: '{token.value}'"
                    )
                )
        return errors


class SyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.rules = []
        self._init_highlight_rules()

    def _init_highlight_rules(self):
        self._add_rule(["const", "constexpr"], QColor(207, 106, 76),)
        self._add_rule(["int"], QColor(103, 140, 177),)

    def _add_rule(self, keywords, color, bold=False, italic=False):
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        fmt.setFontItalic(italic)

        for word in keywords:
            pattern = QRegularExpression(
                r"\b" + QRegularExpression.escape(word) + r"\b")
            if pattern.isValid():
                self.rules.append((pattern, fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(
                    match.capturedStart(),
                    match.capturedLength(),
                    fmt
                )
        self.setCurrentBlockState(0)


class TextEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.current_line_format = QTextCharFormat()
        self.current_line_format.setBackground(QColor(255, 247, 213))

        self.setup_connections()
        self._update_line_number_width(0)
        self.setFont(QFont("Fira Code", 12))
        self.highlighter = SyntaxHighlighter(self.document())

    def setup_connections(self):
        self.blockCountChanged.connect(self._update_line_number_width)
        self.cursorPositionChanged.connect(self._highlight_current_line)

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 20 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_width(self, _):
        self.setViewportMargins(
            self.line_number_area_width(), 0, 0, 0
        )

    def _highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format = self.current_line_format  # type: ignore
            selection.cursor = self.textCursor()  # type: ignore
            selection.cursor.clearSelection()  # type: ignore
            extra_selections.append(selection)
        self.setExtraSelections(extra_selections)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backspace,
            Qt.Key.Key_Delete
        ):
            self._highlight_current_line()

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self._highlight_current_line()


class DocumentModel(QObject):
    modified = Signal(bool)
    file_path_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._file_path = None
        self._is_modified = False

    @property
    def file_path(self):
        return self._file_path

    @file_path.setter
    def file_path(self, value):
        if not isinstance(
            value,
            (
                str,
                type(None)
            )
        ):
            raise TypeError(
                "Путь должен быть строкой или None"
            )
        old_value = self._file_path
        self._file_path = value
        self.file_path_changed.emit(str(old_value), str(value))

    @property
    def is_modified(self):
        return self._is_modified

    @is_modified.setter
    def is_modified(self, value):
        if not isinstance(
            value,
            bool
        ):
            raise TypeError(
                "Флаг изменения должен быть логическим значением"
            )
        self._is_modified = value
        self.modified.emit(value)


class DocumentWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_connected = False
        self._is_reloading = False
        self._is_saving_internally = False
        self.last_saved_mtime = None

        self.model = DocumentModel()
        self.main_layout = QVBoxLayout(self)

        self.input_edit = TextEditor()
        self.highlighter = SyntaxHighlighter(self.input_edit.document())
        self.output_tabs = QTabWidget()

        self.error_table = QTableWidget()
        self.error_table.setColumnCount(3)
        self.error_table.setHorizontalHeaderLabels(
            [
                "Строка",
                "Позиция",
                "Сообщение"
            ]
        )
        self.error_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        header = self.error_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.file_watcher = QFileSystemWatcher()
        self._update_file_watcher()

        self.token_table = QTableWidget()
        self.token_table.setColumnCount(5)
        self.token_table.setHorizontalHeaderLabels([
            "Строка",
            "Начальная позиция",
            "Конечная позиция",
            "Нетерминал",
            "Терминал"
        ])

        self.token_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        header = self.token_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.output_tabs.addTab(self.token_table, "Вывод")
        self.output_tabs.addTab(self.error_table, "Ошибки")
        self.main_layout.addWidget(self.input_edit)
        self.main_layout.addWidget(self.output_tabs)
        self.input_edit.textChanged.connect(self._handle_text_changed)
        self.model.file_path_changed.connect(self._update_file_watcher)

    def save(self, path):
        try:
            if not path:
                raise ValueError(
                    "Не указан путь для сохранения"
                )

            self._is_saving_internally = True
            if self._is_connected:
                self.file_watcher.fileChanged.disconnect()
                self._is_connected = False

            with open(
                path,
                "w",
                encoding="utf-8"
            ) as f:
                content = self.input_edit.toPlainText()
                if not isinstance(content, str):
                    raise TypeError(
                        "Содержимое должно быть строкой"
                    )
                f.write(content)

            self.model.is_modified = False
            self.last_saved_mtime = os.path.getmtime(path)
            self.file_watcher.addPath(path)
            return True

        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Ошибка сохранения: {str(e)}"
            )
            return False
        finally:
            if not self._is_connected:
                self.file_watcher.fileChanged.connect(
                    self._handle_file_changed
                )
                self._is_connected = True
            self._is_saving_internally = False

    def _update_file_watcher(self, old_path=None, new_path=None):
        if not hasattr(self, 'file_watcher'):
            return

        for path in [old_path, new_path]:
            if path and not isinstance(path, str):
                raise TypeError("Неверный тип пути")

        if old_path and self.file_watcher.files():
            self.file_watcher.removePath(
                old_path
            )
        if new_path:
            self.file_watcher.addPath(
                new_path
            )

        if self._is_connected:
            self.file_watcher.fileChanged.disconnect()
            self._is_connected = False

        self.file_watcher.fileChanged.connect(
            self._handle_file_changed
        )
        self._is_connected = True

    def _handle_file_changed(self, path):
        if self._is_saving_internally or path != self.model.file_path:
            return

        try:
            current_mtime = os.path.getmtime(path)
        except FileNotFoundError:
            QMessageBox.warning(self, "Ошибка", "Файл был удален")
            return

        if current_mtime == self.last_saved_mtime:
            return

        self._is_reloading = True
        reply = QMessageBox.question(self, "Изменение файла", f"Файл '{os.path.basename(
            path)}' ""изменен извне. ""Перезагрузить?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self._reload_file()
            self.last_saved_mtime = current_mtime

        self._is_reloading = False

    def _reload_file(self):
        if (not self.model.file_path or not os.path.exists(self.model.file_path)):
            QMessageBox.critical(self, "Ошибка", "Файл не существует")
            return

        try:
            with open(self.model.file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.input_edit.blockSignals(True)
            self.input_edit.setPlainText(content)
            self.input_edit.blockSignals(False)
            self.model.is_modified = False
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки: {str(e)}")

    def _handle_text_changed(self):
        if not self.model.is_modified:
            self.model.is_modified = True


class ToolbarManager:
    def __init__(self, parent: QMainWindow) -> None:
        self.parent = parent
        self.toolbar = QToolBar("Основная панель")
        parent.addToolBar(self.toolbar)

    def add_action(self, icon_name: str, text: str, callback: Callable) -> QAction:
        action = QAction(QIcon.fromTheme(icon_name), text, self.parent)
        action.triggered.connect(callback)
        self.toolbar.addAction(action)
        return action


class MenuManager:
    def __init__(self, parent: "MainView") -> None:
        self.parent = parent
        self.menu_bar = QMenuBar()
        parent.setMenuBar(self.menu_bar)
        self._setup_menus()

    def _setup_menus(self) -> None:
        self._create_file_menu()
        self._create_edit_menu()
        self._create_run_menu()
        self._create_help_menu()

    def _create_file_menu(self) -> None:
        menu = self.menu_bar.addMenu("Файл")
        actions = [
            (
                "Создать",
                "document-new",
                self.parent.new_document
            ),
            (
                "Открыть",
                "document-open",
                self.parent.open_document
            ),
            (
                "Сохранить",
                "document-save",
                self.parent.save_document
            ),
            (
                "Сохранить как",
                "document-save-as",
                self.parent.save_document_as
            ),
            (
                "Выход",
                "application-exit",
                self.parent.close
            ),
        ]
        self._add_menu_actions(menu, actions)

    def _create_edit_menu(self) -> None:
        menu = self.menu_bar.addMenu("Правка")
        actions = [
            (
                "Увеличить шрифт",
                "zoom-in",
                self.parent.increase_font_size
            ),
            (
                "Уменьшить шрифт",
                "zoom-out",
                self.parent.decrease_font_size
            ),
            (
                "Отменить",
                "edit-undo",
                self.parent.undo
            ),
            (
                "Повторить",
                "edit-redo",
                self.parent.redo
            ),
            (
                "Вырезать",
                "edit-cut",
                self.parent.cut
            ),
            (
                "Копировать",
                "edit-copy",
                self.parent.copy
            ),
            (
                "Вставить",
                "edit-paste",
                self.parent.paste
            ),
            (
                "Удалить",
                "edit-delete",
                self.parent.delete
            ),
            (
                "Выделить все",
                "edit-select-all",
                self.parent.select_all
            ),
        ]
        self._add_menu_actions(menu, actions)

    def _create_run_menu(self) -> None:
        menu = self.menu_bar.addMenu("Анализатор")
        action = QAction(
            "Пуск",
            self.parent
        )
        action.triggered.connect(
            self.parent.run_analizer
        )
        menu.addAction(action)

    def _create_help_menu(self) -> None:
        menu = self.menu_bar.addMenu("Справка")
        actions = [
            (
                "Помощь",
                "help-contents",
                self.parent.show_help
            ),
            (
                "О программе",
                "help-about",
                self.parent.show_about
            ),
        ]
        self._add_menu_actions(menu, actions)

    def _add_menu_actions(self, menu: QMenu, actions: list) -> None:
        for text, icon_name, callback in actions:
            action = QAction(
                QIcon.fromTheme(icon_name),
                text,
                self.parent
            )
            action.triggered.connect(callback)
            menu.addAction(action)


class MainView(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Парсер")
        self.setGeometry(100, 100, 680, 720)
        self.doc_widget = DocumentWidget()
        self.setCentralWidget(self.doc_widget)
        self.menu_manager = MenuManager(self)
        self.toolbar_manager = ToolbarManager(self)
        self._setup_toolbar()
        self._setup_shortcuts()
        self._setup_font_size()

    def _setup_toolbar(self):
        actions = [
            ("document-new", "Новый", self.new_document),
            ("document-open", "Открыть", self.open_document),
            ("document-save", "Сохранить", self.save_document),
            ("edit-undo", "Отменить", self.undo),
            ("edit-redo", "Вернуть", self.redo),
            ("edit-cut", "Вырезать", self.cut),
            ("edit-copy", "Копировать", self.copy),
            ("edit-paste", "Вставить", self.paste),
            ("system-run", "Запуск", self.run_analizer),
            ("help-contents", "Справка", self.show_help),
        ]
        for icon, text, callback in actions:
            self.toolbar_manager.add_action(icon, text, callback)

    def _setup_shortcuts(self):
        shortcuts = {
            "Ctrl+N": self.new_document,
            "Ctrl+O": self.open_document,
            "Ctrl+S": self.save_document,
            "Ctrl+Shift+S": self.save_document_as,
            "Ctrl+Z": self.undo,
            "Ctrl+Y": self.redo,
            "Ctrl+F": self.run_analizer,
            "Ctrl+=": self.increase_font_size,
            "Ctrl+-": self.decrease_font_size,
        }
        for seq, handler in shortcuts.items():
            QShortcut(QKeySequence(seq), self).activated.connect(handler)

    def _setup_font_size(self):
        self.font_size = 12
        self.update_font_size()

    def update_font_size(self):
        font = QFont()
        font.setPointSize(self.font_size)
        self.doc_widget.input_edit.setFont(font)

    def increase_font_size(self):
        self.font_size += 1
        self.update_font_size()

    def decrease_font_size(self):
        if self.font_size > 1:
            self.font_size -= 1
            self.update_font_size()

    def new_document(self):
        self.doc_widget.model.file_path = None
        self.doc_widget.input_edit.clear()
        self.doc_widget.model.is_modified = False

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.doc_widget.input_edit.setPlainText(content)
                self.doc_widget.model.file_path = path
                self.doc_widget.model.is_modified = False
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Ошибка создания файла: {str(e)}")

    def save_document(self):
        if self.doc_widget.model.file_path:
            if self.doc_widget.save(self.doc_widget.model.file_path):
                return True
        return self.save_document_as()

    def save_document_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if path and self.doc_widget.save(path):
            self.doc_widget.model.file_path = path
            return True
        return False

    def insert_text(self, text):
        self.doc_widget.input_edit.insertPlainText(
            f"{text}\n"
        )

    def run_analizer(self):
        doc = self.doc_widget
        input_text = doc.input_edit.toPlainText()
        output = Output(input_text)
        lexeme, _ = output.tokenize()
        lexer = Lexer(input_text)
        _, lexer_errors = lexer.strtok()
        valid_tokens, validation_errors = lexer.validate_tokens()
        all_errors = lexer_errors + validation_errors

        doc.token_table.setRowCount(0)
        doc.token_table.setRowCount(len(valid_tokens))

        for row, token in enumerate(lexeme):
            line = token.line
            start = token.column
            end = start + len(token.value) - 1

            doc.token_table.setItem(row, 0, QTableWidgetItem(str(line)))
            doc.token_table.setItem(row, 1, QTableWidgetItem(str(start)))
            doc.token_table.setItem(row, 2, QTableWidgetItem(str(end)))
            doc.token_table.setItem(row, 3, QTableWidgetItem(token.type))
            doc.token_table.setItem(row, 4, QTableWidgetItem(token.value))

        doc.error_table.setRowCount(0)
        doc.error_table.setHorizontalHeaderLabels(
            [
                "Строка",
                "Столбец",
                "Сообщение"
            ]
        )
        doc.error_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        doc.error_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch
        )
        doc.error_table.setSortingEnabled(True)

        for row, error in enumerate(all_errors):
            doc.error_table.insertRow(row)
            doc.error_table.setItem(row, 0, QTableWidgetItem(str(error.line)))
            doc.error_table.setItem(
                row, 1, QTableWidgetItem(str(error.column)))
            doc.error_table.setItem(row, 2, QTableWidgetItem(error.message))

        input_text = self.doc_widget.input_edit.toPlainText()
        output = Output(input_text)
        lex, _ = output.tokenize()
        lexer = Lexer(input_text)
        _, _ = lexer.strtok()

        self.doc_widget.token_table.setRowCount(0)
        self.doc_widget.token_table.setRowCount(len(lex))

        for row, token in enumerate(lex):
            line = token.line
            start = token.column
            end = start + len(token.value) - 1

            self.doc_widget.token_table.setItem(
                row, 0, QTableWidgetItem(str(line)))
            self.doc_widget.token_table.setItem(
                row, 1, QTableWidgetItem(str(start)))
            self.doc_widget.token_table.setItem(
                row, 2, QTableWidgetItem(str(end)))
            self.doc_widget.token_table.setItem(
                row, 3, QTableWidgetItem(token.type))
            self.doc_widget.token_table.setItem(
                row, 4, QTableWidgetItem(token.value))

    def undo(self):
        self.doc_widget.input_edit.undo()

    def redo(self):
        self.doc_widget.input_edit.redo()

    def cut(self):
        self.doc_widget.input_edit.cut()

    def copy(self):
        self.doc_widget.input_edit.copy()

    def paste(self):
        self.doc_widget.input_edit.paste()

    def delete(self):
        self.doc_widget.input_edit.textCursor().removeSelectedText()

    def select_all(self):
        self.doc_widget.input_edit.selectAll()

    def show_help(self):
        QMessageBox.information(
            self,
            "Помощь",
            "Руководство пользователя:\n"
            "1. Создайте/Откройте документы\n"
            "2. Редактируйте текст\n"
            "3. Запустите парсер\n"
            "4. Сохраните вашу работу",
            QMessageBox.StandardButton.Ok
        )

    def show_about(self):
        QMessageBox.about(
            self,
            "О программе",
            "<b>Название программы:</b> Текстовый редактор для анализа объявления целочисленной константы на языке C/C++<br>"
            "<b>Автор:</b> Студентка 3 курса группы АВТ-214, Трифонова София<br>"
            "<b>Преподаватель:</b> Антоньянц Егор Николаевич<br>"
            "<b>Дисциплина:</b> Теория формальных языков и компиляторов"
        )

    def closeEvent(self, event):
        if self.doc_widget.model.is_modified:
            name = os.path.basename(
                self.doc_widget.model.file_path
            ) if self.doc_widget.model.file_path else "Без имени"
            reply = QMessageBox.question(self, "Несохранённые изменения",
                                         f"Документ '{name}' имеет "
                                         "несохранённые изменения. Сохранить?",
                                         QMessageBox.StandardButton.Yes
                                         | QMessageBox.StandardButton.No
                                         | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Yes:
                if not self.save_document():
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainView()
    window.show()
    sys.exit(app.exec())

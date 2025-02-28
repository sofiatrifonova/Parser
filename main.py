"""
Модульное приложение текстового редактора, реализующее основную функциональность редактирования
с использованием архитектуры MVVM.
"""

import logging
from abc import abstractmethod
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import (
    QObject,
    Qt,
    Signal,
    Slot,
    QSize,
    QSignalBlocker
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QToolBar,
    QWidget
)

logger = logging.getLogger(__name__)


class IUserPrompts:
    """Интерфейс для диалогов взаимодействия с пользователем."""

    @abstractmethod
    def ask_save_changes(self) -> Optional[bool]:
        """Запрос на сохранение изменений перед критическими действиями.

        Возвращает:
            Optional[bool]:
                True для сохранения, False для отмены, None для отмены операции.
        """

    @abstractmethod
    def show_error(self, title: str, message: str) -> None:
        """Отображение диалога с сообщением об ошибке.

        Аргументы:
            title: Заголовок окна диалога
            message: Содержание сообщения об ошибке
        """

    @abstractmethod
    def get_save_path(self) -> Optional[str]:
        """Отображение диалога сохранения файла.

        Возвращает:
            Optional[str]: Выбранный путь или None, если отменено
        """

    @abstractmethod
    def get_open_path(self) -> Optional[str]:
        """Отображение диалога открытия файла.

        Возвращает:
            Optional[str]: Выбранный путь или None, если отменено
        """


class IDocumentModel(QObject):
    """Интерфейс для управления состоянием и сохранением документа."""

    text_changed = Signal(str)
    modification_changed = Signal(bool)

    @abstractmethod
    def load(self, path: str) -> bool:
        """Загрузка документа из файловой системы.

        Аргументы:
            path: Путь к файлу для загрузки

        Возвращает:
            bool: True, если успешно
        """

    @abstractmethod
    def save(self, path: Optional[str] = None) -> bool:
        """Сохранение документа в файловую систему.

        Аргументы:
            path: Целевой путь (используется текущий, если None)

        Возвращает:
            bool: True, если успешно
        """

    @property
    @abstractmethod
    def text(self) -> str:
        """Текущее содержимое документа.

        Возвращает:
            str: Полное текстовое содержимое
        """

    @text.setter
    @abstractmethod
    def text(self, value: str) -> None:
        """Обновление содержимого документа.

        Аргументы:
            value: Новое текстовое содержимое
        """

    @property
    @abstractmethod
    def modified(self) -> bool:
        """Статус изменения документа.

        Возвращает:
            bool: True, если есть несохраненные изменения
        """

    @property
    @abstractmethod
    def file_path(self) -> Optional[str]:
        """Текущий путь к документу в файловой системе.

        Возвращает:
            Optional[str]: Путь к файлу или None, если не сохранен
        """

    @file_path.setter
    @abstractmethod
    def file_path(self, value: Optional[str]) -> None:
        """Обновление пути к документу.

        Аргументы:
            value: Новый путь к файлу
        """


class IHistoryManager(QObject):
    """Интерфейс для управления историей отмены/повтора."""

    undo_available = Signal(bool)
    redo_available = Signal(bool)

    @abstractmethod
    def push(self, state: Tuple[str, int]) -> None:
        """Добавление нового состояния документа в историю.

        Аргументы:
            state: Кортеж текста и позиции курсора
        """

    @abstractmethod
    def undo(self) -> Optional[Tuple[str, int]]:
        """Возврат к предыдущему состоянию.

        Возвращает:
            Optional[Tuple[str, int]]: Предыдущее состояние, если доступно
        """

    @abstractmethod
    def redo(self) -> Optional[Tuple[str, int]]:
        """Повтор следующего состояния.

        Возвращает:
            Optional[Tuple[str, int]]: Следующее состояние, если доступно
        """

    @abstractmethod
    def clear(self) -> None:
        """Сброс истории."""


class DocumentModel(IDocumentModel):
    """Реализация сохранения документа с интеграцией сигналов Qt.

    Управляет содержимым документа, операциями с файлами и состоянием изменения,
    а также отправляет соответствующие сигналы для изменений состояния и ошибок.

    Сигналы:
        text_changed: Изменение содержимого (str)
        file_path_changed: Обновление пути (str)
        modification_changed: Изменение состояния изменений (bool)
        error_occurred: Ошибка операции (str: заголовок, str: сообщение)
    """

    file_path_changed = Signal(str)
    error_occurred = Signal(str, str)

    def __init__(self) -> None:
        """Инициализация нового состояния документа."""
        super().__init__()
        self._text = ""
        self._file_path: Optional[str] = None
        self._modified = False

    @property
    def text(self) -> str:
        """Текущее содержимое документа.

        Возвращает:
            Полное текстовое содержимое в виде строки
        """
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        """Обновление содержимого и отметка документа как измененного.

        Аргументы:
            value: Новое текстовое содержимое
        """
        if self._text != value:
            self._text = value
            self.text_changed.emit(value)
            self.modified = True

    @property
    def file_path(self) -> Optional[str]:
        """Текущее расположение документа в файловой системе.

        Возвращает:
            Путь к файлу или None для несохраненных документов
        """
        return self._file_path

    @file_path.setter
    def file_path(self, value: Optional[str]) -> None:
        """Обновление пути к документу с уведомлением.

        Аргументы:
            value: Новый путь в файловой системе
        """
        if self._file_path != value:
            self._file_path = value
            self.file_path_changed.emit(value or "")

    @property
    def modified(self) -> bool:
        """Статус изменения документа.

        Возвращает:
            True, если есть несохраненные изменения
        """
        return self._modified

    @modified.setter
    def modified(self, value: bool) -> None:
        """Обновление состояния изменений.

        Аргументы:
            value: Новое состояние изменений
        """
        if self._modified != value:
            self._modified = value
            self.modification_changed.emit(value)

    def save(self, path: Optional[str] = None) -> bool:
        """Сохранение документа в файловую систему.

        Аргументы:
            path: Целевой путь (используется текущий путь, если None)

        Возвращает:
            True, если сохранение успешно, иначе False

        Сигналы:
            error_occurred: При ошибке сохранения
        """
        save_path = path or self._file_path
        if not save_path:
            self.error_occurred.emit(
                "Ошибка сохранения",
                "Не указан путь к файлу"
            )
            return False

        try:
            Path(save_path).write_text(self._text, encoding="utf-8")
            self.modified = False
            self.file_path = save_path
            return True
        except Exception as err:
            logger.error("Ошибка сохранения: %s", str(err))
            self.error_occurred.emit("Ошибка сохранения", str(err))
            return False

    def load(self, path: str) -> bool:
        """Загрузка содержимого документа из файловой системы.

        Аргументы:
            path: Путь к исходному файлу

        Возвращает:
            True, если загрузка успешна, иначе False

        Сигналы:
            error_occurred: При ошибке загрузки
        """
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.text = content
            self.file_path = path
            self.modified = False
            return True
        except Exception as err:
            logger.error("Ошибка загрузки: %s", str(err))
            self.error_occurred.emit("Ошибка загрузки", str(err))
            return False


class ThemeManager:
    """Централизованное управление темной темой с учетом доступности.

    Реализует современную темную тему с соблюдением контрастности WCAG
    и единообразным стилем для всех компонентов интерфейса.
    """

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
        /* Стилизация главного окна */
        QMainWindow {{
            background-color: {background};
            color: {foreground};
            font-family: 'Segoe UI', sans-serif;
            padding: 6px;
        }}

        /* Основной текстовый редактор */
        QTextEdit#editor {{
            background-color: {base};
            color: {foreground};
            border: 1px solid {border};
            padding: 12px;
            margin: 8px 8px 0 8px;
            selection-background-color: {accent};
            selection-color: {base};
            font-family: 'Fira Code', 'Consolas', monospace;
        }}

        QTextEdit#editor:focus {{
            border-color: {accent_light};
            outline: none;
        }}

        /* Панель вывода */
        QTextEdit#output {{
            background-color: {alternate_base};
            color: {foreground};
            padding: 12px;
            margin: 0 8px 8px 8px;
            font-family: 'Fira Code', 'Consolas', monospace;
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
        """Применение полной конфигурации темы к окну приложения.

        Устанавливает как цвета палитры, так и правила стилей CSS для создания
        единого визуального опыта для всех компонентов интерфейса.

        Аргументы:
            window: Главное окно приложения для стилизации
        """
        palette = QPalette()

        for role, color_key in self._PALETTE_MAP:
            palette.setColor(role, self._PALETTE[color_key])

        disabled_color = self._PALETTE["scroll_handle"]
        roles = (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.WindowText
        )

        for role in roles:
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                role,
                disabled_color
            )

        window.setPalette(palette)
        window.setStyleSheet(self._build_stylesheet())

    def _build_stylesheet(self) -> str:
        """Компиляция полной таблицы стилей из шаблонных компонентов.

        Возвращает:
            Объединенная строка CSS со всеми правилами стилизации интерфейса
        """
        color_map = {k: v.name() for k, v in self._PALETTE.items()}

        styles = [
            self._BASE_STYLE.format(**color_map),
            *[
                style.format(**color_map)
                for style in self._COMPONENT_STYLES.values()
            ]
        ]

        return "\n".join(styles).replace("    ", "")


class EditorViewModel(QObject):
    """Посредник между компонентами интерфейса и моделью документа с использованием паттерна MVVM.

    Управляет:
    - Операциями жизненного цикла документа
    - Управлением историей отмены/повтора
    - Передачей сигналов между слоями
    - Выполнением бизнес-логики

    Сигналы:
        text_changed(str): Изменение содержимого документа
        cursor_changed(int): Обновление позиции курсора
        document_state_changed(bool): Изменение состояния изменений
        request_application_exit: Запрос на завершение приложения
        parser_result_ready(str): Результаты анализа документа
    """

    text_changed = Signal(str)
    cursor_changed = Signal(int)
    document_state_changed = Signal(bool)
    request_application_exit = Signal()
    parser_result_ready = Signal(str)

    def __init__(
        self,
        model: IDocumentModel,
        history: IHistoryManager,
        prompts: IUserPrompts,
    ) -> None:
        """Инициализация модели представления с основными зависимостями.

        Аргументы:
            model: Управление состоянием и сохранением документа
            history: Обработчик операций отмены/повтора
            prompts: Сервис взаимодействия с пользователем
        """
        super().__init__()
        self._model = model
        self._history = history
        self._prompts = prompts
        self._connect_model_signals()

    def _connect_model_signals(self) -> None:
        """Установление соединений сигналов между моделью и моделью представления."""
        self._model.text_changed.connect(self._on_model_text_changed)
        self._model.modification_changed.connect(
            self.document_state_changed.emit
        )

    def _on_model_text_changed(self, text: str) -> None:
        """Обработка обновлений текста модели и передача изменений.

        Аргументы:
            text: Новое содержимое документа
        """
        self.text_changed.emit(text)
        self.cursor_changed.emit(len(text))

    def handle_view_changes(self, text: str, cursor_pos: int) -> None:
        """Обработка изменений интерфейса и обновление состояния приложения.

        Аргументы:
            text: Текущее содержимое редактора
            cursor_pos: Текущая позиция курсора
        """
        self._model.text = text
        self._history.push((text, cursor_pos))

    @Slot()
    def create_new_document(self) -> None:
        """Обработка создания нового документа."""
        if not self._handle_unsaved_changes():
            return

        self._model.text = ""
        self._model.file_path = None
        self._history.clear()
        self.parser_result_ready.emit("")

    @Slot()
    def open_document(self) -> None:
        """Обработка открытия документа."""
        if not self._handle_unsaved_changes():
            return

        if path := self._prompts.get_open_path():
            if self._model.load(path):
                self._history.clear()
                self.parser_result_ready.emit("")

    @Slot()
    def save_document(self) -> None:
        """Обработка сохранения документа."""
        if not self._model.save():
            self._prompts.show_error("Ошибка сохранения", "Не удалось сохранить документ")

    @Slot()
    def save_document_as(self) -> None:
        """Обработка сохранения документа с новым путем."""
        if path := self._prompts.get_save_path():
            if not self._model.save(path):
                self._prompts.show_error("Ошибка сохранения", "Не удалось выполнить сохранение")

    @Slot()
    def exit_application(self) -> None:
        """Обработка завершения приложения."""
        if not self._handle_unsaved_changes():
            return
        self.request_application_exit.emit()

    @Slot()
    def perform_undo(self) -> None:
        """Возврат к предыдущему состоянию документа."""
        if state := self._history.undo():
            logger.debug("Отмена состояния документа")
            self._apply_historical_state(state)

    @Slot()
    def perform_redo(self) -> None:
        """Повтор следующего состояния документа."""
        if state := self._history.redo():
            logger.debug("Повтор состояния документа")
            self._apply_historical_state(state)

    def _apply_historical_state(self, state: Tuple[str, int]) -> None:
        """Синхронизация модели с историческим состоянием документа.

        Аргументы:
            state: Кортеж, содержащий текстовое содержимое и позицию курсора
        """
        text, position = state
        with QSignalBlocker(self._model):
            self._model.text = text
        self.text_changed.emit(text)
        self.cursor_changed.emit(position)

    @Slot()
    def run_parser(self) -> None:
        """Выполнение анализа документа и передача результатов."""
        if not self._model.text:
            logger.warning("Парсер выполнен на пустом документе")
            self.parser_result_ready.emit("")
            return

        result = f"Анализ документа:\n{self._model.text[:50]}..."
        self.parser_result_ready.emit(result)

    def _handle_unsaved_changes(self) -> bool:
        """Управление процессом несохраненных изменений.

        Возвращает:
            True, если операция должна продолжиться, False для отмены
        """
        if not self._model.modified:
            return True

        response = self._prompts.ask_save_changes()
        if response is None:
            return False
        if response and not self._model.save():
            return False
        return True


class CustomTextEdit(QTextEdit):
    """Улучшенный текстовый редактор с управлением масштабированием и возможностью удаления.

    Особенности:
    - Регулируемый размер шрифта с проверкой границ
    - Сохранение выборочного форматирования текста
    - Интеллектуальное удаление текста
    """

    _MIN_FONT_SIZE = 8
    _DEFAULT_FONT_SIZE = 12

    def __init__(self, *args, **kwargs) -> None:
        """Инициализация редактора с настройками типографики по умолчанию."""
        super().__init__(*args, **kwargs)
        self._init_base_style()

    def _init_base_style(self) -> None:
        """Настройка внешнего вида редактора по умолчанию."""
        font = self.font()
        font.setPointSize(self._DEFAULT_FONT_SIZE)
        self.setFont(font)

    def _apply_font_change(self, size: int) -> None:
        """Изменение размера шрифта для выделения или всего документа.

        Аргументы:
            size: Новый размер шрифта в пунктах
        """
        cursor = self.textCursor()

        if cursor.hasSelection():
            fmt = QTextCharFormat()
            fmt.setFontPointSize(size)
            cursor.mergeCharFormat(fmt)
        else:
            font = self.font()
            font.setPointSize(size)
            self.setFont(font)

    def zoom_in(self) -> None:
        """Увеличение размера шрифта на 1 пункт."""
        self._apply_font_change(self.font().pointSize() + 1)

    def zoom_out(self) -> None:
        """Уменьшение размера шрифта с защитой от нижней границы."""
        current_size = self.font().pointSize()
        new_size = max(self._MIN_FONT_SIZE, current_size - 1)
        self._apply_font_change(new_size)

    def reset_zoom(self) -> None:
        """Восстановление размера шрифта по умолчанию."""
        self._apply_font_change(self._DEFAULT_FONT_SIZE)

    def delete_selected(self) -> None:
        """Удаление выделенного текста или соседнего символа."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            cursor.removeSelectedText()
        elif not self.document().isEmpty():
            cursor.deleteChar()


class ComponentFactory:
    """Централизованная фабрика компонентов интерфейса с обеспечением единообразия стилей.

    Реализует фабричный шаблон для создания стандартизированных виджетов приложения
    с предопределенными настройками стилей и поведения.
    """

    @staticmethod
    def create_editor() -> CustomTextEdit:
        """Создание основного компонента редактирования кода.

        Возвращает:
            CustomTextEdit, настроенный с:
            - Подсветкой синтаксиса
            - Переносом строк
            - Идентификатором редактора по умолчанию
        """
        editor = CustomTextEdit()
        editor.setObjectName("editor")
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        SyntaxHighlighter(editor.document())
        return editor

    @staticmethod
    def create_output_panel() -> QTextEdit:
        """Создание консоли диагностического вывода.

        Возвращает:
            QTextEdit, настроенный как:
            - Только для чтения
            - Без рамки
            - Идентификатор панели вывода
        """
        output = QTextEdit()
        output.setObjectName("output")
        output.setFrameStyle(QFrame.Shape.NoFrame)
        output.setReadOnly(True)
        return output

    @staticmethod
    def create_splitter(
        orientation: Qt.Orientation,
        *widgets: QWidget
    ) -> QSplitter:
        """Создание контейнера с возможностью изменения размера для панелей редактора/вывода.

        Аргументы:
            orientation: Горизонтальная или вертикальная компоновка
            widgets: Дочерние виджеты для добавления

        Возвращает:
            QSplitter, настроенный с:
            - Видимым разделителем
            - Нескладывающимися панелями
            - Прозрачным стилем разделителя
        """
        splitter = QSplitter(orientation)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; }")

        for widget in widgets:
            splitter.addWidget(widget)

        return splitter


class HistoryManager(IHistoryManager):
    """Управление историей состояний документа для операций отмены/повтора.

    Реализует:
    - Навигацию по истории на основе стека
    - Обнаружение изменений для избежания дублирования состояний
    - Шаблон наблюдателя через сигналы Qt
    """

    def __init__(self) -> None:
        """Инициализация с пустыми стеками истории."""
        super().__init__()
        self._undo_stack: list[tuple[str, int]] = []
        self._redo_stack: list[tuple[str, int]] = []
        self._current_state: tuple[str, int] | None = None

    def push(self, state: tuple[str, int]) -> None:
        """Добавление нового состояния в историю и сброс возможности повтора.

        Аргументы:
            state: Текстовое содержимое с позицией курсора
        """
        if state == self._current_state:
            return

        self._undo_stack.append(state)
        self._redo_stack.clear()
        self._current_state = state
        self._update_availability_signals()

    def undo(self) -> tuple[str, int] | None:
        """Возврат к предыдущему состоянию документа.

        Возвращает:
            Кортеж предыдущего состояния, если доступен
        """
        if not self._undo_stack:
            return None

        if self._current_state is not None:
            self._redo_stack.append(self._current_state)

        self._current_state = self._undo_stack.pop()
        self._update_availability_signals()
        return self._current_state

    def redo(self) -> tuple[str, int] | None:
        """Повтор следующего состояния документа.

        Возвращает:
            Кортеж следующего состояния, если доступен
        """
        if not self._redo_stack:
            return None

        if self._current_state is not None:
            self._undo_stack.append(self._current_state)

        self._current_state = self._redo_stack.pop()
        self._update_availability_signals()
        return self._current_state

    def clear(self) -> None:
        """Сброс всей истории."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._current_state = None
        self._update_availability_signals()

    def _update_availability_signals(self) -> None:
        """Уведомление наблюдателей об изменениях возможности отмены/повтора."""
        self.undo_available.emit(bool(self._undo_stack))
        self.redo_available.emit(bool(self._redo_stack))


class ActionManager:
    """Абстрактная фабрика для создания стандартизированных конфигураций QAction.

    Предоставляет базовую функциональность для:
    - Создания действий с единообразным стилем
    - Управления иконками и сочетаниями клавиш
    - Привязки обратных вызовов
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Инициализация фабрики действий.

        Аргументы:
            parent: Родительский виджет для владения действиями
        """
        self.parent = parent
        self.actions: dict[str, QAction] = {}

    def _create_action(
        self,
        icon_name: Optional[str],
        text: str,
        shortcut: Optional[QKeySequence.StandardKey],
        callback: Callable[[], None],
    ) -> QAction:
        """Создание предварительно настроенного экземпляра QAction.

        Аргументы:
            icon_name: Идентификатор иконки темы
            text: Отображаемый текст
            shortcut: Сочетание клавиш
            callback: Обработчик триггера действия (без аргументов, возвращает None)

        Возвращает:
            Настроенный экземпляр QAction
        """
        action = QAction(text, self.parent)

        if icon_name:
            action.setIcon(QIcon.fromTheme(icon_name))

        if shortcut:
            action.setShortcut(QKeySequence(shortcut))

        action.triggered.connect(callback)
        return action


class DocumentActionManager(ActionManager):
    """Управление действиями, связанными с документами, с интеграцией модели представления."""

    _ACTION_SPECS = {
        "new": (
            "document-new",
            "Новый",
            QKeySequence.StandardKey.New,
            "create_new_document"
        ),
        "open": (
            "document-open",
            "Открыть",
            QKeySequence.StandardKey.Open,
            "open_document"
        ),
        "save": (
            "document-save",
            "Сохранить",
            QKeySequence.StandardKey.Save,
            "save_document"
        ),
        "save_as": (
            "document-save-as",
            "Сохранить как",
            QKeySequence.StandardKey.SaveAs,
            "save_document_as"
        ),
        "exit": (
            "application-exit",
            "Выход",
            QKeySequence.StandardKey.Quit,
            "exit_application"
        ),
        "undo": (
            "edit-undo",
            "Отменить",
            QKeySequence.StandardKey.Undo,
            "perform_undo"
        ),
        "redo": (
            "edit-redo",
            "Повторить",
            QKeySequence.StandardKey.Redo,
            "perform_redo"
        ),
        "run_parser": (
            "system-run",
            "Запустить парсер",
            None,
            "run_parser"
        )
    }

    def __init__(self, view_model: EditorViewModel) -> None:
        """Инициализация с ссылкой на модель представления документа.

        Аргументы:
            view_model: Обработчик бизнес-логики редактора
        """
        super().__init__()
        self.view_model = view_model

    def create_actions(self) -> dict[str, QAction]:
        """Генерация набора действий для управления документами.

        Возвращает:
            Отображение имен действий на настроенные QActions
        """
        return {
            key: self._create_action(
                spec[0],
                spec[1],
                spec[2],
                getattr(self.view_model, spec[3])
            )
            for key, spec in self._ACTION_SPECS.items()
        }


class EditorActionManager(ActionManager):
    """Управление действиями редактирования текста с прямой интеграцией в редактор.

    Управляет созданием и настройкой:
    - Базовых команд манипуляции текстом
    - Элементов управления областью просмотра
    - Операций выделения
    """

    _ACTION_SPECS = {
        "cut": (
            "edit-cut",
            "Вырезать",
            QKeySequence.StandardKey.Cut,
            "cut"
        ),
        "copy": (
            "edit-copy",
            "Копировать",
            QKeySequence.StandardKey.Copy,
            "copy"
        ),
        "paste": (
            "edit-paste",
            "Вставить",
            QKeySequence.StandardKey.Paste,
            "paste"
        ),
        "select_all": (
            "edit-select-all",
            "Выделить все",
            QKeySequence.StandardKey.SelectAll,
            "selectAll"
        ),
        "zoom_in": (
            "zoom-in",
            "Увеличить",
            QKeySequence.StandardKey.ZoomIn,
            "zoom_in"
        ),
        "zoom_out": (
            "zoom-out",
            "Уменьшить",
            QKeySequence.StandardKey.ZoomOut,
            "zoom_out"
        ),
        "reset_zoom": (
            "zoom-original",
            "Сбросить масштаб",
            QKeySequence("Ctrl+0"),
            "reset_zoom"
        ),
        "remove": (
            "edit-delete",
            "Удалить",
            QKeySequence(Qt.Key.Key_Delete),
            "delete_selected"
        )
    }

    def __init__(self, editor: CustomTextEdit) -> None:
        """Инициализация с ссылкой на текстовый редактор.

        Аргументы:
            editor: Компонент редактирования текста для управления
        """
        super().__init__()
        self.editor = editor

    def create_actions(self) -> dict[str, QAction]:
        """Генерация набора действий редактора с прямой привязкой методов.

        Возвращает:
            Отображение имен действий на настроенные QActions
        """
        return {
            key: self._create_action(
                spec[0],
                spec[1],
                spec[2],
                getattr(self.editor, spec[3])
            )
            for key, spec in self._ACTION_SPECS.items()
        }


class HelpActionManager(ActionManager):
    """Управление действиями системы помощи с привязкой обратных вызовов."""

    _ACTION_SPECS = {
        "help": (
            "help-contents",
            "Помощь",
            QKeySequence.StandardKey.HelpContents,
            "help_callback"
        ),
        "about": (
            "help-about",
            "О программе",
            None,
            "about_callback"
        )
    }

    def __init__(
        self,
        help_callback: Callable[[], None],
        about_callback: Callable[[], None]
    ) -> None:
        """Инициализация с обратными вызовами для диалогов.

        Аргументы:
            help_callback: Обработчик отображения документации помощи
            about_callback: Обработчик диалога информации о приложении
        """
        super().__init__()
        self.help_callback = help_callback
        self.about_callback = about_callback

    def create_actions(self) -> dict[str, QAction]:
        """Генерация набора действий системы помощи.

        Возвращает:
            Отображение имен действий на настроенные QActions
        """
        return {
            key: self._create_action(
                spec[0],
                spec[1],
                spec[2],
                getattr(self, spec[3])
            )
            for key, spec in self._ACTION_SPECS.items()
        }


class MenuManager:
    """Управление структурой и организацией меню приложения.

    Управляет:
    - Конфигурацией иерархии меню
    - Интеграцией действий
    - Размещением разделителей
    """

    _MENU_STRUCTURE = {
        "&Файл": ["new", "open", "save", "save_as", None, "exit"],
        "&Правка": [
            "undo", "redo", None,
            "cut", "copy", "paste", "remove", None,
            "zoom_in", "zoom_out", "reset_zoom", None,
            "select_all"
        ],
        "&Текст": [
            "problem_statement", "grammar", "grammar_classification",
            "method_of_analysis", "error_diagnosis", "test_case",
            "literature_list", "source_code"
        ],
        "&Запуск": ["run_parser"],
        "&Справка": ["help", "about"]
    }

    def __init__(
            self,
            menu_bar: QMenuBar,
            actions: Dict[str, QAction]
    ) -> None:
        """Инициализация с ссылками на строку меню и действия.

        Аргументы:
            menu_bar: Контейнер строки меню приложения
            actions: Отображение имен действий на экземпляры QAction
        """
        self.menu_bar = menu_bar
        self.actions = actions

    def build_menus(self) -> None:
        """Построение иерархии меню из конфигурации.

        Создает меню и подменю в соответствии с предопределенной структурой,
        интегрируя действия и разделители, как указано.
        """
        for menu_label, action_keys in self._MENU_STRUCTURE.items():
            menu = self.menu_bar.addMenu(menu_label)
            self._populate_menu(menu, action_keys)

    def _populate_menu(
            self,
            menu: QMenu,
            action_keys: list[str | None]
    ) -> None:
        """Добавление элементов в указанное меню.

        Аргументы:
            menu: Целевой виджет меню
            action_keys: Последовательность идентификаторов действий и разделителей
        """
        for key in action_keys:
            if key is None:
                menu.addSeparator()
            else:
                self._add_menu_action(menu, key)

    def _add_menu_action(self, menu: QMenu, action_key: str) -> None:
        """Добавление действия в меню с проверкой.

        Аргументы:
            menu: Целевой виджет меню
            action_key: Идентификатор для поиска действия

        Вызывает:
            KeyError: Если action_key не найден в отображении действий
        """
        if action_key not in self.actions:
            raise KeyError(f"Действие '{action_key}' не найдено")

        menu.addAction(self.actions[action_key])


class MainWindow(QMainWindow, IUserPrompts):
    """Центральное окно приложения, реализующее архитектуру MVVM.

    Обязанности:
    - Управление компонентами интерфейса
    - Применение темы
    - Маршрутизация сигналов
    - Обработка диалогов пользователя
    """

    _DEFAULT_WINDOW_SIZE = (800, 600)
    _STATUS_READY = "Готов"
    _WINDOW_TITLE_BASE = "Текстовый редактор"

    _CUSTOM_ACTIONS = {
        "problem_statement": "Постановка задачи",
        "grammar": "Грамматика",
        "grammar_classification": "Классификация грамматики",
        "method_of_analysis": "Метод анализа",
        "error_diagnosis": "Диагностика и нейтрализация ошибок",
        "test_case": "Тестовый пример",
        "literature_list": "Список литературы",
        "source_code": "Исходный код программы"
    }

    def __init__(self) -> None:
        """Инициализация главного окна с настройками по умолчанию."""
        super().__init__()
        self._view_model: Optional[EditorViewModel] = None
        self._theme_manager = ThemeManager()
        self._components_initialized = False
        self._actions: Dict[str, QAction] = {}

        self._init_window_settings()

    def _init_window_settings(self) -> None:
        """Настройка начальных свойств окна."""
        self.setWindowTitle(self._WINDOW_TITLE_BASE)
        self.setMinimumSize(*self._DEFAULT_WINDOW_SIZE)
        self.statusBar().showMessage(self._STATUS_READY)

    def set_view_model(self, view_model: EditorViewModel) -> None:
        """Подключение модели представления и инициализация компонентов интерфейса.

        Аргументы:
            view_model: Обработчик бизнес-логики
        """
        self._view_model = view_model
        if not self._components_initialized:
            self._initialize_ui_components()
            self._components_initialized = True
        self._establish_signal_connections()

    def _initialize_ui_components(self) -> None:
        """Создание и организация элементов интерфейса."""
        self._create_core_components()
        self._setup_main_layout()
        self._theme_manager.apply_theme(self)
        self._build_interface()

    def _create_core_components(self) -> None:
        """Создание основных виджетов интерфейса."""
        self.editor = ComponentFactory.create_editor()
        self.output = ComponentFactory.create_output_panel()
        self.splitter = ComponentFactory.create_splitter(
            Qt.Orientation.Vertical,
            self.editor,
            self.output
        )

    def _setup_main_layout(self) -> None:
        """Настройка иерархии макета окна."""
        self.setCentralWidget(self.splitter)

    def _build_interface(self) -> None:
        """Построение полного пользовательского интерфейса."""
        self._create_action_set()
        self._construct_menu_system()
        self._build_main_toolbar()

    def _create_action_set(self) -> None:
        """Инициализация всех действий приложения."""
        if self._view_model:
            self._actions.update(
                DocumentActionManager(self._view_model).create_actions()
            )

        self._actions.update(
            EditorActionManager(self.editor).create_actions()
        )
        self._actions.update(
            HelpActionManager(self.show_help, self.show_about).create_actions()
        )
        self._add_custom_actions()

    def _add_custom_actions(self) -> None:
        """Регистрация специфических для приложения действий."""
        for key, text in self._CUSTOM_ACTIONS.items():
            self._actions[key] = QAction(text, self)

    def _construct_menu_system(self) -> None:
        """Построение иерархии меню приложения."""
        MenuManager(self.menuBar(), self._actions).build_menus()

    def _build_main_toolbar(self) -> None:
        """Настройка основной панели инструментов с общими действиями."""
        toolbar = QToolBar("Основная панель инструментов", self)
        toolbar.setIconSize(QSize(24, 24))

        essential_actions = [
            "new", "open", "save", "undo", "redo",
            "copy", "cut", "paste", "run_parser", "help", "about"
        ]
        toolbar.addActions(
            [self._actions[key] for key in essential_actions]
        )

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    def _establish_signal_connections(self) -> None:
        """Подключение сигналов модели представления к обработчикам интерфейса."""
        if not self._view_model:
            return

        connections = [
            (self._view_model.text_changed, self._update_editor_content),
            (self._view_model.cursor_changed, self._update_cursor),
            (self._view_model.document_state_changed, self._update_title),
            (self._view_model.request_application_exit, self.close),
            (self._view_model.parser_result_ready, self._update_output_panel),
            (self.editor.textChanged, self._handle_editor_changes)
        ]

        for signal, handler in connections:
            signal.connect(handler)

    def _update_editor_content(self, text: str) -> None:
        """Синхронизация содержимого редактора с моделью.

        Аргументы:
            text: Текущее содержимое документа
        """
        if self.editor.toPlainText() != text:
            self.editor.setPlainText(text)

    def _update_output_panel(self, result: str) -> None:
        """Отображение результатов парсера в панели вывода.

        Аргументы:
            result: Результаты анализа
        """
        self.output.setPlainText(result)

    def _update_cursor(self, position: int) -> None:
        """Обновление позиции курсора редактора.

        Аргументы:
            position: Новая позиция курсора
        """
        cursor = self.editor.textCursor()
        cursor.setPosition(position)
        self.editor.setTextCursor(cursor)

    def _handle_editor_changes(self) -> None:
        """Передача изменений редактора в модель представления."""
        if self._view_model:
            content = self.editor.toPlainText()
            position = self.editor.textCursor().position()
            self._view_model.handle_view_changes(content, position)

    def _update_title(self, modified: bool) -> None:
        """Обновление заголовка окна с учетом состояния изменений.

        Аргументы:
            modified: Документ имеет несохраненные изменения
        """
        self.setWindowTitle(
            f"{self._WINDOW_TITLE_BASE}{'*' if modified else ''}"
        )

    # IUserPrompts implementation
    def ask_save_changes(self) -> Optional[bool]:
        """Запрос на сохранение несохраненных изменений.

        Возвращает:
            True: Сохранить изменения
            False: Отменить изменения
            None: Отменить операцию
        """
        response = QMessageBox.question(
            self,
            "Несохраненные изменения",
            "Сохранить изменения перед закрытием?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No |
            QMessageBox.StandardButton.Cancel
        )
        return {
            QMessageBox.StandardButton.Yes: True,
            QMessageBox.StandardButton.No: False,
            QMessageBox.StandardButton.Cancel: None
        }.get(response, None)

    def get_save_path(self) -> Optional[str]:
        """Отображение диалога сохранения файла.

        Возвращает:
            Выбранный путь или None
        """
        return self._get_file_path(QFileDialog.getSaveFileName, "Сохранить файл")

    def get_open_path(self) -> Optional[str]:
        """Отображение диалога открытия файла.

        Возвращает:
            Выбранный путь или None
        """
        return self._get_file_path(QFileDialog.getOpenFileName, "Открыть файл")

    def _get_file_path(self, dialog_method, title: str) -> Optional[str]:
        """Универсальный помощник для получения пути к файлу.

        Аргументы:
            dialog_method: Конструктор диалога файла
            title: Заголовок окна диалога

        Возвращает:
            Выбранный путь или None
        """
        path, _ = dialog_method(
            self,
            title,
            "",
            "Текстовые файлы (*.txt);;Все файлы (*)"
        )
        return path if path else None

    def show_error(self, title: str, message: str) -> None:
        """Отображение диалога ошибки.

        Аргументы:
            title: Заголовок диалога
            message: Детали ошибки
        """
        QMessageBox.critical(self, title, message)

    def show_help(self) -> None:
        """Отображение документации помощи."""
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

    def show_about(self) -> None:
        """Отображение информации о приложении."""
        QMessageBox.about(
            self,
            "О программе",
            "<b>Название программы:</b> Текстовый редактор для анализа объявления целочисленной константы на языке C/C++<br>"
            "<b>Автор:</b> Студентка 3 курса группы АВТ-214, Трифонова София<br>"
            "<b>Преподаватель:</b> Антоньянц Егор Николаевич<br>"
            "<b>Дисциплина:</b> Теория формальных языков и компиляторов"
        )


class SyntaxHighlighter(QSyntaxHighlighter):
    """Обеспечивает подсветку синтаксиса Rust с использованием ручного анализа текста.

    Особенности:
    - Обнаружение ключевых слов и типов
    - Подсветка строковых литералов
    - Распознавание чисел
    - Однострочные комментарии
    """

    KEYWORDS = {
        "as", "async", "await", "break", "const", "continue", "crate", "dyn",
        "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in",
        "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
        "self", "Self", "static", "struct", "super", "trait", "true", "type",
        "union", "unsafe", "use", "where", "while",
    }

    TYPES = {
        "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64",
        "u128", "usize", "f32", "f64", "bool", "char", "str", "String",
    }

    STYLES = {
        "keyword": QColor(86, 156, 214),
        "type": QColor(78, 201, 176),
        "string": QColor(206, 145, 120),
        "comment": QColor(106, 153, 85),
        "number": QColor(181, 206, 168),
    }

    def __init__(self, parent: QTextDocument) -> None:
        """Инициализация подсветки синтаксиса с правилами Rust.

        Аргументы:
            parent: Документ для применения правил подсветки
        """
        super().__init__(parent)
        self._formats = self._create_text_formats()

    def _create_text_formats(self) -> dict[str, QTextCharFormat]:
        """Создание текстовых форматов для различных элементов синтаксиса.

        Возвращает:
            Отображение типов синтаксиса на текстовые форматы
        """
        formats = {}
        for style, color in self.STYLES.items():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            formats[style] = fmt
        return formats

    def highlightBlock(self, text: str) -> None:
        """Применение подсветки синтаксиса к текстовому блоку.

        Аргументы:
            text: Содержимое блока для подсветки
        """
        self._highlight_strings(text)
        self._highlight_comments(text)
        self._highlight_numbers(text)
        self._highlight_identifiers(text)
        self.setCurrentBlockState(0)

    def _highlight_strings(self, text: str) -> None:
        """Подсветка строковых литералов в двойных кавычках."""
        start = 0
        while start < len(text):
            if text[start] != '"':
                start += 1
                continue

            end = start + 1
            while end < len(text):
                if text[end] == '"' and text[end-1] != '\\':
                    break
                end += 1

            self.setFormat(start, end - start + 1, self._formats["string"])
            start = end + 1

    def _highlight_comments(self, text: str) -> None:
        """Подсветка однострочных комментариев."""
        comment_start = text.find("//")
        if comment_start >= 0:
            self.setFormat(
                comment_start,
                len(text) - comment_start,
                self._formats["comment"]
            )

    def _highlight_numbers(self, text: str) -> None:
        """Highlight numeric literals."""
        start = 0
        while start < len(text):
            if not text[start].isdigit():
                start += 1
                continue

            end = start
            while end < len(text) and text[end].isdigit():
                end += 1

            self.setFormat(start, end - start, self._formats["number"])
            start = end

    def _highlight_identifiers(self, text: str) -> None:
        """Highlight keywords and type identifiers."""
        buffer = ""
        start_pos = 0

        for pos, char in enumerate(text):
            if char.isalnum() or char == '_':
                if not buffer:
                    start_pos = pos
                buffer += char
            else:
                self._process_identifier(buffer, start_pos, pos)
                buffer = ""

        self._process_identifier(buffer, start_pos, len(text))

    def _process_identifier(self, word: str, start: int, end: int) -> None:
        """Apply formatting to recognized keywords/types."""
        if not word:
            return

        if word in self.KEYWORDS:
            self.setFormat(start, end - start, self._formats["keyword"])
        elif word in self.TYPES:
            self.setFormat(start, end - start, self._formats["type"])


def main() -> None:
    """Application entry point with main window initialization."""
    app = QApplication([])

    window = MainWindow()
    model = DocumentModel()
    history = HistoryManager()

    view_model = EditorViewModel(model, history, window)
    window.set_view_model(view_model)

    window.show()
    app.exec()


if __name__ == "__main__":
    main()

"""
A modular text editor application implementing core editing functionality
with MVVM architecture.
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
    """Interface for user interaction dialogs and prompts."""

    @abstractmethod
    def ask_save_changes(self) -> Optional[bool]:
        """Prompt to save changes before critical actions.

        Returns:
            Optional[bool]:
                True to save, False to discard, None to cancel.
        """

    @abstractmethod
    def show_error(self, title: str, message: str) -> None:
        """Display error message dialog.

        Args:
            title: Dialog window title
            message: Error message content
        """

    @abstractmethod
    def get_save_path(self) -> Optional[str]:
        """Show save file dialog.

        Returns:
            Optional[str]: Selected path or None if canceled
        """

    @abstractmethod
    def get_open_path(self) -> Optional[str]:
        """Show open file dialog.

        Returns:
            Optional[str]: Selected path or None if canceled
        """


class IDocumentModel(QObject):
    """Interface for document persistence and state management."""

    text_changed = Signal(str)
    modification_changed = Signal(bool)

    @abstractmethod
    def load(self, path: str) -> bool:
        """Load document from filesystem.

        Args:
            path: File path to load from

        Returns:
            bool: True if successful
        """

    @abstractmethod
    def save(self, path: Optional[str] = None) -> bool:
        """Save document to filesystem.

        Args:
            path: Target path (uses current if None)

        Returns:
            bool: True if successful
        """

    @property
    @abstractmethod
    def text(self) -> str:
        """Current document content.

        Returns:
            str: The full text content
        """

    @text.setter
    @abstractmethod
    def text(self, value: str) -> None:
        """Update document content.

        Args:
            value: New text content
        """

    @property
    @abstractmethod
    def modified(self) -> bool:
        """Document modification status.

        Returns:
            bool: True if unsaved changes exist
        """

    @property
    @abstractmethod
    def file_path(self) -> Optional[str]:
        """Current document filesystem path.

        Returns:
            Optional[str]: Path string or None if unsaved
        """

    @file_path.setter
    @abstractmethod
    def file_path(self, value: Optional[str]) -> None:
        """Update document path.

        Args:
            value: New file path
        """


class IHistoryManager(QObject):
    """Interface for undo/redo history management."""

    undo_available = Signal(bool)
    redo_available = Signal(bool)

    @abstractmethod
    def push(self, state: Tuple[str, int]) -> None:
        """Add new document state to history.

        Args:
            state: Tuple of text and cursor position
        """

    @abstractmethod
    def undo(self) -> Optional[Tuple[str, int]]:
        """Revert to previous state.

        Returns:
            Optional[Tuple[str, int]]: Previous state if available
        """

    @abstractmethod
    def redo(self) -> Optional[Tuple[str, int]]:
        """Reapply next state.

        Returns:
            Optional[Tuple[str, int]]: Next state if available
        """

    @abstractmethod
    def clear(self) -> None:
        """Reset history tracking."""


class DocumentModel(IDocumentModel):
    """Implements document persistence with Qt signal integration.

    Manages document content, file operations, and modification state while
    emitting relevant signals for state changes and errors.

    Signals:
        text_changed: Content modification (str)
        file_path_changed: Path update (str)
        modification_changed: Dirty state change (bool)
        error_occurred: Operation failure (str: title, str: message)
    """

    file_path_changed = Signal(str)
    error_occurred = Signal(str, str)

    def __init__(self) -> None:
        """Initialize fresh document state."""
        super().__init__()
        self._text = ""
        self._file_path: Optional[str] = None
        self._modified = False

    @property
    def text(self) -> str:
        """Current document content.

        Returns:
            Complete text content as string
        """
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        """Update content and mark document as modified.

        Args:
            value: New text content
        """
        if self._text != value:
            self._text = value
            self.text_changed.emit(value)
            self.modified = True

    @property
    def file_path(self) -> Optional[str]:
        """Current document filesystem location.

        Returns:
            Path string or None for unsaved documents
        """
        return self._file_path

    @file_path.setter
    def file_path(self, value: Optional[str]) -> None:
        """Update document path with notification.

        Args:
            value: New filesystem path
        """
        if self._file_path != value:
            self._file_path = value
            self.file_path_changed.emit(value or "")

    @property
    def modified(self) -> bool:
        """Document modification status.

        Returns:
            True if unsaved changes exist
        """
        return self._modified

    @modified.setter
    def modified(self, value: bool) -> None:
        """Update modification state.

        Args:
            value: New dirty state
        """
        if self._modified != value:
            self._modified = value
            self.modification_changed.emit(value)

    def save(self, path: Optional[str] = None) -> bool:
        """Persist document to filesystem.

        Args:
            path: Target path (uses current path if None)

        Returns:
            True if save successful, False otherwise

        Emits:
            error_occurred: On save failure
        """
        save_path = path or self._file_path
        if not save_path:
            self.error_occurred.emit(
                "Save Error",
                "No file path specified"
            )
            return False

        try:
            Path(save_path).write_text(self._text, encoding="utf-8")
            self.modified = False
            self.file_path = save_path
            return True
        except Exception as err:
            logger.error("Save failed: %s", str(err))
            self.error_occurred.emit("Save Error", str(err))
            return False

    def load(self, path: str) -> bool:
        """Load document content from filesystem.

        Args:
            path: Source file path

        Returns:
            True if load successful, False otherwise

        Emits:
            error_occurred: On load failure
        """
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.text = content
            self.file_path = path
            self.modified = False
            return True
        except Exception as err:
            logger.error("Load failed: %s", str(err))
            self.error_occurred.emit("Load Error", str(err))
            return False


class ThemeManager:
    """Centralized dark theme management with accessibility-focused colors.

    Implements a modern dark theme with WCAG-compliant contrast ratios and
    consistent styling across all UI components.
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
        /* Main window styling */
        QMainWindow {{
            background-color: {background};
            color: {foreground};
            font-family: 'Segoe UI', sans-serif;
            padding: 6px;
        }}

        /* Primary text editor */
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

        /* Output panel */
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
        """Apply complete theme configuration to application window.

        Sets both palette colors and CSS-style stylesheet rules to create
        a cohesive visual experience across all UI components.

        Args:
            window: Main application window to style
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
        """Compile complete stylesheet from template components.

        Returns:
            Combined CSS string with all UI styling rules
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
    """Mediates between UI components and document model using MVVM pattern.

    Handles:
    - Document lifecycle operations
    - Undo/redo history management
    - Signal propagation between layers
    - Business logic execution

    Signals:
        text_changed(str): Document content modification
        cursor_changed(int): Cursor position update
        document_state_changed(bool): Modification state change
        request_application_exit: Application termination request
        parser_result_ready(str): Analysis results from document processing
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
        """Initialize view model with core dependencies.

        Args:
            model: Document persistence and state management
            history: Undo/redo operations handler
            prompts: User interaction service
        """
        super().__init__()
        self._model = model
        self._history = history
        self._prompts = prompts
        self._connect_model_signals()

    def _connect_model_signals(self) -> None:
        """Establish model-to-viewmodel signal connections."""
        self._model.text_changed.connect(self._on_model_text_changed)
        self._model.modification_changed.connect(
            self.document_state_changed.emit
        )

    def _on_model_text_changed(self, text: str) -> None:
        """Handle model text updates and propagate changes.

        Args:
            text: New document content
        """
        self.text_changed.emit(text)
        self.cursor_changed.emit(len(text))

    def handle_view_changes(self, text: str, cursor_pos: int) -> None:
        """Process UI changes and update application state.

        Args:
            text: Current editor content
            cursor_pos: Current caret position
        """
        self._model.text = text
        self._history.push((text, cursor_pos))

    @Slot()
    def create_new_document(self) -> None:
        """Handle new document creation workflow."""
        if not self._handle_unsaved_changes():
            return

        self._model.text = ""
        self._model.file_path = None
        self._history.clear()
        self.parser_result_ready.emit("")

    @Slot()
    def open_document(self) -> None:
        """Handle document opening workflow."""
        if not self._handle_unsaved_changes():
            return

        if path := self._prompts.get_open_path():
            if self._model.load(path):
                self._history.clear()
                self.parser_result_ready.emit("")

    @Slot()
    def save_document(self) -> None:
        """Handle document save operation."""
        if not self._model.save():
            self._prompts.show_error("Save Error", "Document save failed")

    @Slot()
    def save_document_as(self) -> None:
        """Handle save-as operation with new path."""
        if path := self._prompts.get_save_path():
            if not self._model.save(path):
                self._prompts.show_error("Save Error", "Save operation failed")

    @Slot()
    def exit_application(self) -> None:
        """Handle application termination workflow."""
        if not self._handle_unsaved_changes():
            return
        self.request_application_exit.emit()

    @Slot()
    def perform_undo(self) -> None:
        """Revert to previous document state."""
        if state := self._history.undo():
            logger.debug("Undoing document state")
            self._apply_historical_state(state)

    @Slot()
    def perform_redo(self) -> None:
        """Reapply next document state."""
        if state := self._history.redo():
            logger.debug("Redoing document state")
            self._apply_historical_state(state)

    def _apply_historical_state(self, state: Tuple[str, int]) -> None:
        """Synchronize model with historical document state.

        Args:
            state: Tuple containing text content and cursor position
        """
        text, position = state
        with QSignalBlocker(self._model):
            self._model.text = text
        self.text_changed.emit(text)
        self.cursor_changed.emit(position)

    @Slot()
    def run_parser(self) -> None:
        """Execute document analysis and emit results."""
        if not self._model.text:
            logger.warning("Parser executed on empty document")
            self.parser_result_ready.emit("")
            return

        result = f"Document analysis:\n{self._model.text[:50]}..."
        self.parser_result_ready.emit(result)

    def _handle_unsaved_changes(self) -> bool:
        """Manage unsaved changes workflow.

        Returns:
            True if operation should proceed, False to cancel
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
    """Enhanced text editor with zoom controls and deletion capabilities.

    Features:
    - Adjustable font size with bounds checking
    - Selective text formatting preservation
    - Intelligent text deletion handling
    """

    _MIN_FONT_SIZE = 8
    _DEFAULT_FONT_SIZE = 12

    def __init__(self, *args, **kwargs) -> None:
        """Initialize editor with default typography settings."""
        super().__init__(*args, **kwargs)
        self._init_base_style()

    def _init_base_style(self) -> None:
        """Configure default editor appearance."""
        font = self.font()
        font.setPointSize(self._DEFAULT_FONT_SIZE)
        self.setFont(font)

    def _apply_font_change(self, size: int) -> None:
        """Modify font size for selection or entire document.

        Args:
            size: New font size in points
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
        """Increase font size by 1 point."""
        self._apply_font_change(self.font().pointSize() + 1)

    def zoom_out(self) -> None:
        """Reduce font size with lower bound protection."""
        current_size = self.font().pointSize()
        new_size = max(self._MIN_FONT_SIZE, current_size - 1)
        self._apply_font_change(new_size)

    def reset_zoom(self) -> None:
        """Restore default font size."""
        self._apply_font_change(self._DEFAULT_FONT_SIZE)

    def delete_selected(self) -> None:
        """Remove selected text or adjacent character."""
        cursor = self.textCursor()

        if cursor.hasSelection():
            cursor.removeSelectedText()
        elif not self.document().isEmpty():
            cursor.deleteChar()


class ComponentFactory:
    """Centralized UI component factory with style consistency enforcement.

    Implements factory pattern for creating standardized application widgets
    with predefined styling and behavior configurations.
    """

    @staticmethod
    def create_editor() -> CustomTextEdit:
        """Create primary code editing component.

        Returns:
            CustomTextEdit configured with:
            - Syntax highlighting
            - Line wrapping
            - Default editor ID
        """
        editor = CustomTextEdit()
        editor.setObjectName("editor")
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        SyntaxHighlighter(editor.document())
        return editor

    @staticmethod
    def create_output_panel() -> QTextEdit:
        """Create diagnostic output console.

        Returns:
            QTextEdit configured as:
            - Read-only
            - Frameless
            - Output panel ID
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
        """Create resizable container for editor/output panels.

        Args:
            orientation: Horizontal or vertical layout
            widgets: Child widgets to add

        Returns:
            QSplitter configured with:
            - Visible handle
            - Non-collapsible panes
            - Transparent handle styling
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
    """Manages document state history for undo/redo operations.

    Implements:
    - Stack-based history navigation
    - Change detection to avoid duplicate states
    - Observer pattern via Qt signals
    """

    def __init__(self) -> None:
        """Initialize with empty history stacks."""
        super().__init__()
        self._undo_stack: list[tuple[str, int]] = []
        self._redo_stack: list[tuple[str, int]] = []
        self._current_state: tuple[str, int] | None = None

    def push(self, state: tuple[str, int]) -> None:
        """Add new state to history and reset redo capacity.

        Args:
            state: Text content with cursor position
        """
        if state == self._current_state:
            return

        self._undo_stack.append(state)
        self._redo_stack.clear()
        self._current_state = state
        self._update_availability_signals()

    def undo(self) -> tuple[str, int] | None:
        """Revert to previous document state.

        Returns:
            Previous state tuple if available
        """
        if not self._undo_stack:
            return None

        if self._current_state is not None:
            self._redo_stack.append(self._current_state)

        self._current_state = self._undo_stack.pop()
        self._update_availability_signals()
        return self._current_state

    def redo(self) -> tuple[str, int] | None:
        """Reapply next document state.

        Returns:
            Next state tuple if available
        """
        if not self._redo_stack:
            return None

        if self._current_state is not None:
            self._undo_stack.append(self._current_state)

        self._current_state = self._redo_stack.pop()
        self._update_availability_signals()
        return self._current_state

    def clear(self) -> None:
        """Reset all history tracking."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._current_state = None
        self._update_availability_signals()

    def _update_availability_signals(self) -> None:
        """Notify observers about undo/redo capability changes."""
        self.undo_available.emit(bool(self._undo_stack))
        self.redo_available.emit(bool(self._redo_stack))


class ActionManager:
    """Abstract factory for creating standardized QAction configurations.

    Provides base functionality for:
    - Action creation with consistent styling
    - Icon and shortcut management
    - Callback binding
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Initialize action factory.

        Args:
            parent: Parent widget for action ownership
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
        """Create preconfigured QAction instance.

        Args:
            icon_name: Theme icon identifier
            text: Display text
            shortcut: Keyboard shortcut
            callback: Action trigger handler (no arguments, returns None)

        Returns:
            Configured QAction instance
        """
        action = QAction(text, self.parent)

        if icon_name:
            action.setIcon(QIcon.fromTheme(icon_name))

        if shortcut:
            action.setShortcut(QKeySequence(shortcut))

        action.triggered.connect(callback)
        return action


class DocumentActionManager(ActionManager):
    """Manages document-related actions with view model integration."""

    _ACTION_SPECS = {
        "new": (
            "document-new",
            "New",
            QKeySequence.StandardKey.New,
            "create_new_document"
        ),
        "open": (
            "document-open",
            "Open",
            QKeySequence.StandardKey.Open,
            "open_document"
        ),
        "save": (
            "document-save",
            "Save",
            QKeySequence.StandardKey.Save,
            "save_document"
        ),
        "save_as": (
            "document-save-as",
            "Save As",
            QKeySequence.StandardKey.SaveAs,
            "save_document_as"
        ),
        "exit": (
            "application-exit",
            "Exit",
            QKeySequence.StandardKey.Quit,
            "exit_application"
        ),
        "undo": (
            "edit-undo",
            "Undo",
            QKeySequence.StandardKey.Undo,
            "perform_undo"
        ),
        "redo": (
            "edit-redo",
            "Redo",
            QKeySequence.StandardKey.Redo,
            "perform_redo"
        ),
        "run_parser": (
            "system-run",
            "Run Parser",
            None,
            "run_parser"
        )
    }

    def __init__(self, view_model: EditorViewModel) -> None:
        """Initialize with document view model reference.

        Args:
            view_model: Editor business logic handler
        """
        super().__init__()
        self.view_model = view_model

    def create_actions(self) -> dict[str, QAction]:
        """Generate document management action set.

        Returns:
            Mapping of action names to configured QActions
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
    """Manages text editing actions with direct editor integration.

    Handles creation and configuration of:
    - Basic text manipulation commands
    - Viewport controls
    - Selection operations
    """

    _ACTION_SPECS = {
        "cut": (
            "edit-cut",
            "Cut",
            QKeySequence.StandardKey.Cut,
            "cut"
        ),
        "copy": (
            "edit-copy",
            "Copy",
            QKeySequence.StandardKey.Copy,
            "copy"
        ),
        "paste": (
            "edit-paste",
            "Paste",
            QKeySequence.StandardKey.Paste,
            "paste"
        ),
        "select_all": (
            "edit-select-all",
            "Select All",
            QKeySequence.StandardKey.SelectAll,
            "selectAll"
        ),
        "zoom_in": (
            "zoom-in",
            "Zoom In",
            QKeySequence.StandardKey.ZoomIn,
            "zoom_in"
        ),
        "zoom_out": (
            "zoom-out",
            "Zoom Out",
            QKeySequence.StandardKey.ZoomOut,
            "zoom_out"
        ),
        "reset_zoom": (
            "zoom-original",
            "Reset Zoom",
            QKeySequence("Ctrl+0"),
            "reset_zoom"
        ),
        "remove": (
            "edit-delete",
            "Remove",
            QKeySequence(Qt.Key.Key_Delete),
            "delete_selected"
        )
    }

    def __init__(self, editor: CustomTextEdit) -> None:
        """Initialize with text editor reference.

        Args:
            editor: Text editing component to control
        """
        super().__init__()
        self.editor = editor

    def create_actions(self) -> dict[str, QAction]:
        """Generate editor action set with direct method binding.

        Returns:
            Mapping of action names to configured QActions
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
    """Manages application help system actions with callback binding."""

    _ACTION_SPECS = {
        "help": (
            "help-contents",
            "Help",
            QKeySequence.StandardKey.HelpContents,
            "help_callback"
        ),
        "about": (
            "help-about",
            "About",
            None,
            "about_callback"
        )
    }

    def __init__(
        self,
        help_callback: Callable[[], None],
        about_callback: Callable[[], None]
    ) -> None:
        """Initialize with dialog callbacks.

        Args:
            help_callback: Help documentation display handler
            about_callback: Application info dialog handler
        """
        super().__init__()
        self.help_callback = help_callback
        self.about_callback = about_callback

    def create_actions(self) -> dict[str, QAction]:
        """Generate help system action set.

        Returns:
            Mapping of action names to configured QActions
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
    """Manages application menu structure and organization.

    Handles:
    - Menu hierarchy configuration
    - Action integration
    - Separator placement
    """

    _MENU_STRUCTURE = {
        "&File": ["new", "open", "save", "save_as", None, "exit"],
        "&Edit": [
            "undo", "redo", None,
            "cut", "copy", "paste", "remove", None,
            "zoom_in", "zoom_out", "reset_zoom", None,
            "select_all"
        ],
        "&Text": [
            "problem_statement", "grammar", "grammar_classification",
            "method_of_analysis", "error_diagnosis", "test_case",
            "literature_list", "source_code"
        ],
        "&Launch": ["run_parser"],
        "&Help": ["help", "about"]
    }

    def __init__(
            self,
            menu_bar: QMenuBar,
            actions: Dict[str, QAction]
    ) -> None:
        """Initialize with menu bar and action references.

        Args:
            menu_bar: Application menu bar container
            actions: Mapping of action names to QAction instances
        """
        self.menu_bar = menu_bar
        self.actions = actions

    def build_menus(self) -> None:
        """Construct menu hierarchy from configuration.

        Creates menus and submenus according to predefined structure,
        integrating actions and separators as specified.
        """
        for menu_label, action_keys in self._MENU_STRUCTURE.items():
            menu = self.menu_bar.addMenu(menu_label)
            self._populate_menu(menu, action_keys)

    def _populate_menu(
            self,
            menu: QMenu,
            action_keys: list[str | None]
    ) -> None:
        """Add items to specified menu.

        Args:
            menu: Target menu widget
            action_keys: Sequence of action identifiers and separators
        """
        for key in action_keys:
            if key is None:
                menu.addSeparator()
            else:
                self._add_menu_action(menu, key)

    def _add_menu_action(self, menu: QMenu, action_key: str) -> None:
        """Add action to menu with validation.

        Args:
            menu: Target menu widget
            action_key: Identifier for action lookup

        Raises:
            KeyError: If action_key not found in actions mapping
        """
        if action_key not in self.actions:
            raise KeyError(f"Action '{action_key}' not found")

        menu.addAction(self.actions[action_key])


class MainWindow(QMainWindow, IUserPrompts):
    """Central application window implementing MVVM architecture.

    Responsibilities:
    - UI component management
    - Theme application
    - Signal routing
    - User dialog handling
    """

    _DEFAULT_WINDOW_SIZE = (800, 600)
    _STATUS_READY = "Ready"
    _WINDOW_TITLE_BASE = "Text Editor"

    _CUSTOM_ACTIONS = {
        "problem_statement": "Problem Statement",
        "grammar": "Grammar",
        "grammar_classification": "Grammar Classification",
        "method_of_analysis": "The Method of Analysis",
        "error_diagnosis": "Error Diagnosis and Neutralization",
        "test_case": "A Test Case",
        "literature_list": "The List of Literature",
        "source_code": "The Source Code of the Program"
    }

    def __init__(self) -> None:
        """Initialize main window with default configuration."""
        super().__init__()
        self._view_model: Optional[EditorViewModel] = None
        self._theme_manager = ThemeManager()
        self._components_initialized = False
        self._actions: Dict[str, QAction] = {}

        self._init_window_settings()

    def _init_window_settings(self) -> None:
        """Configure initial window properties."""
        self.setWindowTitle(self._WINDOW_TITLE_BASE)
        self.setMinimumSize(*self._DEFAULT_WINDOW_SIZE)
        self.statusBar().showMessage(self._STATUS_READY)

    def set_view_model(self, view_model: EditorViewModel) -> None:
        """Connect view model and initialize UI components.

        Args:
            view_model: Business logic handler
        """
        self._view_model = view_model
        if not self._components_initialized:
            self._initialize_ui_components()
            self._components_initialized = True
        self._establish_signal_connections()

    def _initialize_ui_components(self) -> None:
        """Create and arrange UI elements."""
        self._create_core_components()
        self._setup_main_layout()
        self._theme_manager.apply_theme(self)
        self._build_interface()

    def _create_core_components(self) -> None:
        """Instantiate primary UI widgets."""
        self.editor = ComponentFactory.create_editor()
        self.output = ComponentFactory.create_output_panel()
        self.splitter = ComponentFactory.create_splitter(
            Qt.Orientation.Vertical,
            self.editor,
            self.output
        )

    def _setup_main_layout(self) -> None:
        """Configure window layout hierarchy."""
        self.setCentralWidget(self.splitter)

    def _build_interface(self) -> None:
        """Construct complete user interface."""
        self._create_action_set()
        self._construct_menu_system()
        self._build_main_toolbar()

    def _create_action_set(self) -> None:
        """Initialize all application actions."""
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
        """Register application-specific actions."""
        for key, text in self._CUSTOM_ACTIONS.items():
            self._actions[key] = QAction(text, self)

    def _construct_menu_system(self) -> None:
        """Build application menu hierarchy."""
        MenuManager(self.menuBar(), self._actions).build_menus()

    def _build_main_toolbar(self) -> None:
        """Configure primary toolbar with common actions."""
        toolbar = QToolBar("Main Toolbar", self)
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
        """Connect view model signals to UI handlers."""
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
        """Synchronize editor content with model.

        Args:
            text: Current document content
        """
        if self.editor.toPlainText() != text:
            self.editor.setPlainText(text)

    def _update_output_panel(self, result: str) -> None:
        """Display parser results in output panel.

        Args:
            result: Analysis results
        """
        self.output.setPlainText(result)

    def _update_cursor(self, position: int) -> None:
        """Update editor cursor position.

        Args:
            position: New caret position
        """
        cursor = self.editor.textCursor()
        cursor.setPosition(position)
        self.editor.setTextCursor(cursor)

    def _handle_editor_changes(self) -> None:
        """Propagate editor changes to view model."""
        if self._view_model:
            content = self.editor.toPlainText()
            position = self.editor.textCursor().position()
            self._view_model.handle_view_changes(content, position)

    def _update_title(self, modified: bool) -> None:
        """Update window title with modification state.

        Args:
            modified: Document has unsaved changes
        """
        self.setWindowTitle(
            f"{self._WINDOW_TITLE_BASE}{'*' if modified else ''}"
        )

    # IUserPrompts implementation
    def ask_save_changes(self) -> Optional[bool]:
        """Prompt to save unsaved changes.

        Returns:
            True: Save changes
            False: Discard changes
            None: Cancel operation
        """
        response = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save changes before closing?",
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
        """Show save file dialog.

        Returns:
            Selected path or None
        """
        return self._get_file_path(QFileDialog.getSaveFileName, "Save File")

    def get_open_path(self) -> Optional[str]:
        """Show open file dialog.

        Returns:
            Selected path or None
        """
        return self._get_file_path(QFileDialog.getOpenFileName, "Open File")

    def _get_file_path(self, dialog_method, title: str) -> Optional[str]:
        """Generic file path acquisition helper.

        Args:
            dialog_method: File dialog constructor
            title: Dialog window title

        Returns:
            Selected path or None
        """
        path, _ = dialog_method(
            self,
            title,
            "",
            "Text Files (*.txt);;All Files (*)"
        )
        return path if path else None

    def show_error(self, title: str, message: str) -> None:
        """Display error dialog.

        Args:
            title: Dialog title
            message: Error details
        """
        QMessageBox.critical(self, title, message)

    def show_help(self) -> None:
        """Display help documentation."""
        QMessageBox.information(
            self,
            "Помощь",
            "User Guide:\n"
            "1. Create/Open documents\n"
            "2. Edit text\n"
            "3. Run parser\n"
            "4. Save your work",
            QMessageBox.StandardButton.Ok
        )

    def show_about(self) -> None:
        """Display application information."""
        QMessageBox.about(
            self,
            "About Text Editor",
            "Text Editor v1.0\n"
            "(c) 2024 University Lab Project"
        )


class SyntaxHighlighter(QSyntaxHighlighter):
    """Provides Rust syntax highlighting using manual text parsing.

    Features:
    - Keyword and type detection
    - String literal highlighting
    - Number recognition
    - Single-line comments
    """

    KEYWORDS = {
            "break", "const", "continue", "else", "enum", "false",
            "for", "if", "return", "static", "struct", "while"
        }

    TYPES = {
            "byte", "double", "unsigned", "float", "bool", "char", "int", "string",
        }


    STYLES = {
        "keyword": QColor(86, 156, 214),
        "type": QColor(78, 201, 176),
        "string": QColor(206, 145, 120),
        "comment": QColor(106, 153, 85),
        "number": QColor(181, 206, 168),
    }

    def __init__(self, parent: QTextDocument) -> None:
        """Initialize highlighter with Rust syntax rules.

        Args:
            parent: Document to apply highlighting rules to
        """
        super().__init__(parent)
        self._formats = self._create_text_formats()

    def _create_text_formats(self) -> dict[str, QTextCharFormat]:
        """Create text formats for different syntax elements.

        Returns:
            Mapping of syntax types to text formats
        """
        formats = {}
        for style, color in self.STYLES.items():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            formats[style] = fmt
        return formats

    def highlightBlock(self, text: str) -> None:
        """Apply syntax highlighting to a text block.

        Args:
            text: Block content to highlight
        """
        self._highlight_strings(text)
        self._highlight_comments(text)
        self._highlight_numbers(text)
        self._highlight_identifiers(text)
        self.setCurrentBlockState(0)

    def _highlight_strings(self, text: str) -> None:
        """Highlight string literals in double quotes."""
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
        """Highlight single-line comments."""
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
